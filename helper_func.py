import base64
import re
import asyncio
import time
from datetime import datetime, timedelta
from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant
from shortzy import Shortzy

from info import OWNER_ID, SHORTLINK_URL, SHORTLINK_API, FSUB_LINK_EXPIRY


# =========================================================
# ENCODE / DECODE (Base64 URL-safe for file store links)
# =========================================================
async def encode(string):
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    return base64_bytes.decode("ascii").strip("=")


async def decode(base64_string):
    base64_string = base64_string.strip("=")
    base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
    string_bytes = base64.urlsafe_b64decode(base64_bytes)
    return string_bytes.decode("ascii")


# =========================================================
# GET MESSAGES FROM DB CHANNEL (batched, handles FloodWait)
# =========================================================
async def get_messages(client, message_ids):
    messages = []
    total = 0
    while total != len(message_ids):
        batch = message_ids[total: total + 200]
        try:
            msgs = await client.get_messages(
                chat_id=client.db_channel.id,
                message_ids=batch
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            msgs = await client.get_messages(
                chat_id=client.db_channel.id,
                message_ids=batch
            )
        except Exception:
            msgs = []
        total += len(batch)
        messages.extend(msgs)
    return messages


# =========================================================
# GET MESSAGE ID FROM FORWARDED MSG OR LINK
# =========================================================
async def get_message_id(client, message):
    if message.forward_from_chat:
        if message.forward_from_chat.id == client.db_channel.id:
            return message.forward_from_message_id
        return 0
    elif message.forward_sender_name:
        return 0
    elif message.text:
        pattern = r"https://t\.me/(?:c/)?(.*)/(\d+)"
        matches = re.match(pattern, message.text)
        if not matches:
            return 0
        channel_id = matches.group(1)
        msg_id = int(matches.group(2))
        if channel_id.isdigit():
            if f"-100{channel_id}" == str(client.db_channel.id):
                return msg_id
        else:
            if channel_id == client.db_channel.username:
                return msg_id
        return 0
    return 0


# =========================================================
# HUMAN-READABLE EXPIRY TIME
# =========================================================
def get_exp_time(seconds):
    periods = [("days", 86400), ("hours", 3600), ("mins", 60), ("secs", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)} {period_name} "
    return result.strip()


# =========================================================
# ADMIN FILTER (Owner + DB-stored admins)
# =========================================================
async def _check_admin(flt, client, update):
    try:
        from database.users_db import db
        user_id = update.from_user.id
        if user_id == OWNER_ID:
            return True
        return await db.fs_admin_exist(user_id)
    except Exception as e:
        print(f"[check_admin error] {e}")
        return False


admin = filters.create(_check_admin)


# =========================================================
# DYNAMIC FORCE-SUB CHECK (DB channels)
# =========================================================
async def is_subscribed(client, user_id):
    from database.users_db import db

    channel_ids = await db.fs_show_channels()
    if not channel_ids:
        return True
    if user_id == OWNER_ID:
        return True

    for cid in channel_ids:
        if not await _is_sub(client, user_id, cid):
            mode = await db.fs_get_channel_mode(cid)
            if mode == "on":
                await asyncio.sleep(2)
                if await _is_sub(client, user_id, cid):
                    continue
            return False
    return True


async def _is_sub(client, user_id, channel_id):
    from database.users_db import db
    try:
        member = await client.get_chat_member(channel_id, user_id)
        return member.status in {
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
        }
    except UserNotParticipant:
        mode = await db.fs_get_channel_mode(channel_id)
        if mode == "on":
            return await db.fs_req_user_exist(channel_id, user_id)
        return False
    except Exception as e:
        print(f"[_is_sub error] {e}")
        return False


async def not_joined_message(client, message, start_arg=""):
    from database.users_db import db
    buttons = []
    all_channels = await db.fs_show_channels()

    for chat_id in all_channels:
        mode = await db.fs_get_channel_mode(chat_id)
        if await _is_sub(client, message.from_user.id, chat_id):
            continue
        try:
            data = await client.get_chat(chat_id)
            name = data.title
            if mode == "on" and not data.username:
                expire_dt = (
                    datetime.utcnow() + timedelta(seconds=FSUB_LINK_EXPIRY)
                    if FSUB_LINK_EXPIRY else None
                )
                invite = await client.create_chat_invite_link(
                    chat_id=chat_id,
                    creates_join_request=True,
                    expire_date=expire_dt,
                )
                link = invite.invite_link
            else:
                if data.username:
                    link = f"https://t.me/{data.username}"
                else:
                    expire_dt = (
                        datetime.utcnow() + timedelta(seconds=FSUB_LINK_EXPIRY)
                        if FSUB_LINK_EXPIRY else None
                    )
                    invite = await client.create_chat_invite_link(
                        chat_id=chat_id, expire_date=expire_dt
                    )
                    link = invite.invite_link
            buttons.append([{"text": name, "url": link}])
        except Exception as e:
            print(f"[not_joined_message error for {chat_id}] {e}")

    from utils import temp as _temp
    bot_uname = _temp.U_NAME or client.username.lstrip("@")
    retry_link = (
        f"https://t.me/{bot_uname}?start={start_arg}"
        if start_arg else f"https://t.me/{bot_uname}?start=start"
    )
    buttons.append([{"text": "♻️ Try Again", "url": retry_link}])

    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(b["text"], url=b["url"])] for row in buttons for b in [row[0]]]
        if buttons else [[]]
    )
    # Rebuild properly (each row is already a list)
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(btn["text"], url=btn["url"])]
            for btn in [r[0] for r in buttons]
        ]
    )
    await message.reply(
        "<b>You need to join our channels to use this bot!</b>",
        reply_markup=markup,
    )


# =========================================================
# SHORTLINK HELPER
# =========================================================
async def get_shortlink(url, api, link):
    shortzy = Shortzy(api_key=api, base_site=url)
    return await shortzy.convert(link)

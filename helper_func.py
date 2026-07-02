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
    if not hasattr(update, "from_user") or update.from_user is None:
        return False
    user_id = update.from_user.id

    # OWNER_ID == 0 means the env var was never configured
    if OWNER_ID == 0:
        try:
            from pyrogram.types import Message, CallbackQuery
            msg = (
                "⚠️ <b>OWNER_ID is not configured!</b>\n\n"
                f"Your Telegram ID is <code>{user_id}</code>\n\n"
                "Add this to your environment variables and restart the bot:\n"
                f"<code>OWNER_ID = {user_id}</code>"
            )
            if isinstance(update, Message):
                await update.reply(msg)
            elif isinstance(update, CallbackQuery):
                await update.answer(f"⚠️ OWNER_ID not set! Add OWNER_ID={user_id} to env vars.", show_alert=True)
        except Exception:
            pass
        return False

    if user_id == OWNER_ID:
        return True

    try:
        from database.users_db import db
        is_admin = await db.fs_admin_exist(user_id)
    except Exception as e:
        print(f"[admin filter error] uid={user_id} err={e}")
        is_admin = False

    if not is_admin:
        try:
            from pyrogram.types import Message, CallbackQuery
            if isinstance(update, Message):
                await update.reply(
                    "⛔ <b>Unauthorized.</b>\n\n"
                    f"Your Telegram ID: <code>{user_id}</code>\n"
                    f"Bot OWNER_ID is set to: <code>{OWNER_ID}</code>\n\n"
                    "If you are the owner, set <b>OWNER_ID</b> in your env vars to "
                    f"<code>{user_id}</code> and restart the bot."
                )
            elif isinstance(update, CallbackQuery):
                await update.answer(
                    f"⛔ Unauthorized. Your ID: {user_id} | Expected: {OWNER_ID}",
                    show_alert=True,
                )
        except Exception:
            pass
        return False

    return True


admin = filters.create(_check_admin)


# =========================================================
# FORCE-SUB HELPERS — thin wrappers around the unified check
# The real logic now lives in utils.check_force_sub().
# These are kept so any remaining external callers don't break.
# =========================================================
async def is_subscribed(client, user_id):
    """
    Deprecated: use utils.check_force_sub() directly.
    Returns True if the user passes all force-sub checks.
    Note: this variant does NOT send a message; it only returns a bool.
    """
    from database.users_db import db
    from pyrogram.enums import ChatMemberStatus
    from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant
    from info import OWNER_ID, AUTH_CHANNEL

    if user_id == OWNER_ID:
        return True

    db_channels = await db.fs_show_channels()
    all_channels = list(AUTH_CHANNEL)
    for cid in db_channels:
        if cid not in all_channels:
            all_channels.append(cid)

    if not all_channels:
        return True

    for cid in all_channels:
        request_mode = False
        if cid in set(db_channels):
            mode = await db.fs_get_channel_mode(cid)
            request_mode = (mode == "on")
        try:
            member = await client.get_chat_member(cid, user_id)
            if member.status not in {
                ChatMemberStatus.OWNER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.MEMBER,
            }:
                return False
        except UserNotParticipant:
            if request_mode:
                await asyncio.sleep(2)
                if await db.fs_req_user_exist(cid, user_id):
                    continue
            return False
        except Exception:
            continue
    return True


async def not_joined_message(client, message, start_arg=""):
    """
    Deprecated: use utils.check_force_sub() directly.
    Delegates to the unified implementation.
    """
    from utils import check_force_sub
    await check_force_sub(client, message, start_arg=start_arg)


# =========================================================
# SHORTLINK HELPER
# =========================================================
async def get_shortlink(url, api, link):
    from utils import temp
    if not temp.SHORTNER_ENABLED:
        return link
    effective_url = temp.SHORTNER_URL or url
    effective_api = temp.SHORTNER_API or api
    shortzy = Shortzy(api_key=effective_api, base_site=effective_url)
    return await shortzy.convert(link)

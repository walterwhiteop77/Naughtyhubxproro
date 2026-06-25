import asyncio
import time
import random
import string as rohit
import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from pyrogram.errors import FloodWait
from pyrogram.enums import ParseMode

from Script import script
from database.users_db import db
from bot_cfg import gcfg
from info import (
    START_PIC, LOG_CHANNEL, PREMIUM_LOGS, FSUB, QR_CODE_IMAGE,
    DAILY_LIMIT, PREMIUM_DAILY_LIMIT, UPI_ID, PROTECT_CONTENT,
    CUSTOM_CAPTION, DISABLE_CHANNEL_BUTTON, SHORTLINK_URL, SHORTLINK_API,
    FS_VERIFY_EXPIRE, IS_VERIFY, CAT_VERIFY_EXPIRE,
)
from utils import temp, check_force_sub
from helper_func import (
    encode, decode, get_messages, get_exp_time,
    get_shortlink,
)
from plugins.verification import verify_user_on_start
from plugins.send_file import send_requested_file
from plugins.refer import refer_on_start
from plugins.fs_player import launch_fs_player, AUTO_DELETE_SECS


# =================================================
# START COMMAND
# =================================================
@Client.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    user_id = message.from_user.id
    mention = message.from_user.mention
    me2 = (await client.get_me()).mention

    argument = message.command[1] if len(message.command) > 1 else None

    # --- Unified force-sub check (env-var + DB channels in one pass) ---
    if not await check_force_sub(client, message, start_arg=argument or ""):
        return

    # ------------------------------------------------------------------
    # Handle verification token (original system)
    # ------------------------------------------------------------------
    if argument and argument.startswith("verify_"):
        await verify_user_on_start(client, message)
        return

    # ------------------------------------------------------------------
    # Handle file-store token verification (fs_verify_ prefix)
    # ------------------------------------------------------------------
    if argument and argument.startswith("fs_verify_"):
        _, token = argument.split("fs_verify_", 1)
        verify_status = await db.fs_get_verify_status(user_id)
        if verify_status.get("verify_token") != token:
            return await message.reply("⚠️ Invalid token. Please /start again.")
        await db.fs_update_verify_status(
            user_id, is_verified=True, verified_time=time.time(),
            verify_token=token
        )
        return await message.reply(
            f"✅ Token verified! Valid for {get_exp_time(FS_VERIFY_EXPIRE)}"
        )

    # ------------------------------------------------------------------
    # Handle category-change token verification (cat_verify_ prefix)
    # ------------------------------------------------------------------
    if argument and argument.startswith("cat_verify_"):
        _, token = argument.split("cat_verify_", 1)
        verify_status = await db.cat_get_verify_status(user_id)
        if verify_status.get("verify_token") != token:
            return await message.reply("⚠️ Invalid or expired token. Please tap 🔄 Change Category again.")
        await db.cat_update_verify_status(
            user_id, is_verified=True, verified_time=time.time(),
            verify_token=token
        )
        return await message.reply(
            f"✅ <b>Verified!</b> You can now use <b>Change Category</b> for {get_exp_time(CAT_VERIFY_EXPIRE)}.\n\n"
            "<i>Go back to your video player and tap 🔄 Change Category.</i>"
        )

    # ------------------------------------------------------------------
    # Static pages
    # ------------------------------------------------------------------
    if argument == "terms":
        return await send_legal_text(client, message, script.TERMS_TXT)
    elif argument == "disclaimer":
        return await send_legal_text(client, message, script.DISCLAIMER_TXT)
    elif argument == "help":
        return await send_legal_text(client, message, script.HELP_TXT)
    elif argument == "about":
        return await send_about_text(client, message)

    # ------------------------------------------------------------------
    # Referral link
    # ------------------------------------------------------------------
    if argument and argument.startswith("reff_"):
        try:
            await refer_on_start(client, message)
            return
        except Exception as e:
            print(f"[Referral Error] {e}")

    # ------------------------------------------------------------------
    # Original video player link (avx- prefix)
    # ------------------------------------------------------------------
    if argument and argument.startswith("avx-"):
        search_id = argument.replace("avx-", "")
        await send_requested_file(client, message, user_id, search_id)
        return

    # ------------------------------------------------------------------
    # File Store link (base64 encoded "get-..." token)
    # ------------------------------------------------------------------
    if argument and not argument.startswith(("verify_", "reff_", "avx-", "terms", "disclaimer", "help", "about")):
        # Try to decode as a file store link
        try:
            decoded = await decode(argument)
            if decoded.startswith("get-"):
                await _handle_file_store_link(client, message, user_id, argument, decoded)
                return
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Register new user
    # ------------------------------------------------------------------
    if not await db.is_user_exist(user_id):
        await db.add_user(user_id, message.from_user.first_name)
        try:
            await client.send_message(LOG_CHANNEL, script.LOG_TEXT.format(me2, user_id, mention))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Normal start message
    # ------------------------------------------------------------------
    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("Get Video"), KeyboardButton("Brazzers")],
            [KeyboardButton("My plan"), KeyboardButton("Subscription")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

    await message.reply_photo(
        photo=gcfg('START_PIC', START_PIC),
        caption=script.START_TXT.format(mention, temp.U_NAME, temp.U_NAME),
        reply_markup=reply_keyboard,
        has_spoiler=True,
    )


# =================================================
# FILE STORE LINK HANDLER (internal helper)
# =================================================
async def _handle_file_store_link(client, message: Message, user_id, argument, decoded):
    # File-store token verification gate
    if gcfg('IS_VERIFY', IS_VERIFY) and gcfg('SHORTLINK_URL', SHORTLINK_URL) and gcfg('SHORTLINK_API', SHORTLINK_API):
        verify_status = await db.fs_get_verify_status(user_id)
        is_premium = await db.has_premium_access(user_id)

        # Expire old verification
        if verify_status.get("is_verified") and FS_VERIFY_EXPIRE < (
            time.time() - verify_status.get("verified_time", 0)
        ):
            await db.fs_update_verify_status(user_id, is_verified=False)
            verify_status = await db.fs_get_verify_status(user_id)

        if not verify_status.get("is_verified") and not is_premium:
            token = "".join(random.choices(rohit.ascii_letters + rohit.digits, k=10))
            await db.fs_update_verify_status(user_id, verify_token=token)
            try:
                link = await get_shortlink(
                    SHORTLINK_URL, SHORTLINK_API,
                    f"https://t.me/{temp.U_NAME}?start=fs_verify_{token}"
                )
            except Exception:
                link = f"https://t.me/{temp.U_NAME}?start=fs_verify_{token}"

            btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("• ᴏᴘᴇɴ ʟɪɴᴋ •", url=link)
            ]])
            return await message.reply(
                f"<b>Your token has expired. Please verify to continue.</b>\n\n"
                f"<b>Token Timeout:</b> {get_exp_time(FS_VERIFY_EXPIRE)}",
                reply_markup=btn,
            )

    # Parse IDs from decoded string  e.g. "get-123456-789012" or "get-123456"
    parts = decoded.split("-")
    ids = []
    try:
        if len(parts) == 3:
            db_ch_id = abs(client.db_channel.id)
            start = int(int(parts[1]) / db_ch_id)
            end = int(int(parts[2]) / db_ch_id)
            ids = list(range(start, end + 1)) if start <= end else list(range(start, end - 1, -1))
        elif len(parts) == 2:
            ids = [int(int(parts[1]) / abs(client.db_channel.id))]
        else:
            return await message.reply("❌ Invalid link.")
    except Exception as e:
        print(f"[FileStore decode error] {e}")
        return await message.reply("❌ Invalid or corrupted link.")

    temp_msg = await message.reply("<b>Please wait...</b>")
    try:
        messages = await get_messages(client, ids)
    except Exception as e:
        print(f"[get_messages error] {e}")
        await temp_msg.delete()
        return await message.reply("❌ Something went wrong fetching files.")
    await temp_msg.delete()

    # Launch file store player
    auto_del = await db.fs_get_del_timer()
    if auto_del <= 0:
        auto_del = AUTO_DELETE_SECS  # default 10 minutes

    await launch_fs_player(
        client=client,
        user_id=user_id,
        messages=messages,
        chat_id=message.chat.id,
        reply_to=message.id,
        argument=argument,
        auto_del_secs=auto_del,
    )


# =================================================
# HELPER HANDLERS
# =================================================
@Client.on_message(filters.command("disclaimer") & filters.private)
async def legal_disclaimer(client, message: Message):
    await send_legal_text(client, message, script.DISCLAIMER_TXT)


@Client.on_message(filters.command("terms") & filters.private)
async def legal_terms(client, message: Message):
    await send_legal_text(client, message, script.TERMS_TXT)


@Client.on_message(filters.command("about") & filters.private)
async def legal_about(client, message: Message):
    await send_about_text(client, message)


@Client.on_message(filters.command("help") & filters.private)
async def legal_help(client, message: Message):
    await send_legal_text(client, message, script.HELP_TXT)


async def send_legal_text(client, message, text):
    await message.reply_text(
        text=text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄʟᴏsᴇ •", callback_data="close_data")]]),
        disable_web_page_preview=True,
    )


async def send_about_text(client, message):
    await message.reply_text(
        text=script.ABOUT_TXT.format(temp.B_NAME, temp.B_LINK),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄʟᴏsᴇ •", callback_data="close_data")]]),
        disable_web_page_preview=True,
    )


# =================================================
# CALLBACK QUERY HANDLER
# =================================================
@Client.on_callback_query(group=1)
async def cb_handler(client: Client, query):
    data = query.data
    user_id = query.from_user.id

    if data == "close_data":
        await query.answer()
        await query.message.delete()

    elif data == "get":
        buttons = [[InlineKeyboardButton("• 𝖢𝗅𝗈𝗌𝖾 •", callback_data="close_data")]]
        await query.message.reply_photo(
            photo=gcfg('QR_CODE_IMAGE', QR_CODE_IMAGE),
            caption=script.SEENBUY_TXT.format(
                gcfg('DAILY_LIMIT', DAILY_LIMIT),
                gcfg('PREMIUM_DAILY_LIMIT', PREMIUM_DAILY_LIMIT),
                gcfg('UPI_ID', UPI_ID),
            ),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML,
        )


# =================================================
# /myid — returns the user's Telegram ID
# =================================================
@Client.on_message(filters.command("myid") & filters.private)
async def myid_cmd(client, message: Message):
    user = message.from_user
    await message.reply(
        f"👤 <b>Your Telegram ID:</b> <code>{user.id}</code>\n"
        f"📛 <b>Name:</b> {user.mention}\n\n"
        f"<i>To enable admin commands, set your <b>ADMINS</b> env var to this ID.</i>"
    )

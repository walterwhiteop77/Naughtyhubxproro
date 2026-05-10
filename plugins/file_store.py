"""
File Store Plugin
-----------------
Features:
  - Admin sends any file in private → copied to DB channel → shareable base64 link returned
  - /genlink  — generate link for a single DB channel post
  - /batch    — generate link for a range of DB channel posts
  - /custom_batch — interactively collect files and create a batch link
"""

import asyncio
from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from pyrogram.errors import FloodWait

from helper_func import encode, get_message_id, admin
from utils import temp


# =========================================================
# EXCLUDED COMMANDS — never intercepted by channel_post
# =========================================================
EXCLUDED_COMMANDS = {
    # Core
    "start", "help", "about", "terms", "disclaimer", "commands",
    # Admin panel
    "owner_cmd",
    # Premium
    "add_premium", "addpremium", "remove_premium", "premium_user",
    "premium_users", "myplan", "buy",
    # User management
    "ban", "unban", "banlist", "blocked", "check_user",
    # Stats & DB
    "stats", "all_users_stats", "deleteall", "users", "count",
    # Broadcasting
    "broadcast", "dbroadcast", "pbroadcast",
    # Indexing
    "index",
    # Codes / redemption
    "code", "allcodes", "delete_redeem", "clearcodes", "redeem", "gencode",
    # File store
    "genlink", "batch", "custom_batch", "dlt_time", "check_dlt_time",
    # Force-sub channels
    "addchnl", "delchnl", "listchnl", "fsub_mode", "delreq",
    # Admin management
    "add_admin", "deladmin", "admins",
    # Video & content
    "getvideo", "brazzers", "bookmarks", "refer",
    # Category
    "categories", "setcategory", "clearcategory", "catchannels",
}

# Keyboard button texts that must NOT trigger file-store
EXCLUDED_BUTTON_TEXTS = {
    "get video", "brazzers", "my plan", "subscription",
    "stop", "yes", "no",
}


# =========================================================
# CHANNEL POST — Auto-store file and return shareable link
# =========================================================
@Client.on_message(filters.private & admin & ~filters.command(list(EXCLUDED_COMMANDS)))
async def channel_post(client: Client, message: Message):
    # Skip keyboard button texts — they are handled by their own handlers
    if message.text and message.text.strip().lower() in EXCLUDED_BUTTON_TEXTS:
        return

    # Only store messages that actually contain content worth archiving:
    # media files (document, video, audio, photo, animation, sticker, voice,
    # video_note) OR forwarded messages OR text messages with explicit intent.
    # Plain unforwarded text that isn't a command is skipped here.
    has_media = any([
        message.document, message.video, message.audio,
        message.photo, message.animation, message.sticker,
        message.voice, message.video_note,
    ])
    is_forwarded = bool(message.forward_date)

    if not has_media and not is_forwarded and message.text:
        # Plain text from admin — not a file store action
        return

    if not client.db_channel:
        return await message.reply("❌ DB Channel is not configured.")

    reply_text = await message.reply_text("Please wait...", quote=True)
    try:
        post_message = await message.copy(
            chat_id=client.db_channel.id,
            disable_notification=True,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value)
        post_message = await message.copy(
            chat_id=client.db_channel.id,
            disable_notification=True,
        )
    except Exception as e:
        print(f"[channel_post error] {e}")
        return await reply_text.edit_text("❌ Something went wrong storing the file.")

    converted_id = post_message.id * abs(client.db_channel.id)
    string = f"get-{converted_id}"
    base64_string = await encode(string)
    bot_username = temp.U_NAME  # No @ prefix
    link = f"https://t.me/{bot_username}?start={base64_string}"

    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]]
    )
    await reply_text.edit(
        f"<b>Here is your link</b>\n\n{link}",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


# =========================================================
# /genlink — Generate link for one DB channel post
# =========================================================
@Client.on_message(filters.private & admin & filters.command("genlink"))
async def link_generator(client: Client, message: Message):
    if not client.db_channel:
        return await message.reply("❌ DB Channel is not configured.")

    while True:
        try:
            channel_message = await client.ask(
                text=(
                    "Forward a message from the DB Channel (with Quotes)…\n"
                    "or send the DB Channel post link."
                ),
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60,
            )
        except asyncio.TimeoutError:
            return
        except Exception:
            return

        msg_id = await get_message_id(client, channel_message)
        if msg_id:
            break
        await channel_message.reply(
            "❌ Error — This is not from my DB Channel or the link is incorrect.",
            quote=True,
        )

    bot_username = temp.U_NAME
    base64_string = await encode(f"get-{msg_id * abs(client.db_channel.id)}")
    link = f"https://t.me/{bot_username}?start={base64_string}"
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]]
    )
    await channel_message.reply_text(
        f"<b>Here is your link</b>\n\n{link}",
        quote=True,
        reply_markup=reply_markup,
    )


# =========================================================
# /batch — Generate link for a range of DB channel posts
# =========================================================
@Client.on_message(filters.private & admin & filters.command("batch"))
async def batch(client: Client, message: Message):
    if not client.db_channel:
        return await message.reply("❌ DB Channel is not configured.")

    # First message
    while True:
        try:
            first_message = await client.ask(
                text=(
                    "Forward the **First** Message from DB Channel (with Quotes)…\n"
                    "or send the DB Channel post link."
                ),
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60,
            )
        except asyncio.TimeoutError:
            return
        except Exception:
            return

        f_msg_id = await get_message_id(client, first_message)
        if f_msg_id:
            break
        await first_message.reply(
            "❌ Error — This post is not from my DB Channel.", quote=True
        )

    # Last message
    while True:
        try:
            second_message = await client.ask(
                text=(
                    "Forward the **Last** Message from DB Channel (with Quotes)…\n"
                    "or send the DB Channel post link."
                ),
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60,
            )
        except asyncio.TimeoutError:
            return
        except Exception:
            return

        s_msg_id = await get_message_id(client, second_message)
        if s_msg_id:
            break
        await second_message.reply(
            "❌ Error — This post is not from my DB Channel.", quote=True
        )

    bot_username = temp.U_NAME
    db_ch_id = abs(client.db_channel.id)
    string = f"get-{f_msg_id * db_ch_id}-{s_msg_id * db_ch_id}"
    base64_string = await encode(string)
    link = f"https://t.me/{bot_username}?start={base64_string}"
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]]
    )
    await second_message.reply_text(
        f"<b>Here is your batch link</b>\n\n{link}",
        quote=True,
        reply_markup=reply_markup,
    )


# =========================================================
# /custom_batch — Collect files interactively and batch them
# =========================================================
@Client.on_message(filters.private & admin & filters.command("custom_batch"))
async def custom_batch(client: Client, message: Message):
    if not client.db_channel:
        return await message.reply("❌ DB Channel is not configured.")

    collected = []
    STOP_KEYBOARD = ReplyKeyboardMarkup([["STOP"]], resize_keyboard=True)

    await message.reply(
        "Send all files/messages you want to include in the batch.\n\n"
        "Press **STOP** when you're done.",
        reply_markup=STOP_KEYBOARD,
    )

    while True:
        try:
            user_msg = await client.ask(
                chat_id=message.chat.id,
                text="Waiting for files… press STOP to finish.",
                timeout=60,
            )
        except asyncio.TimeoutError:
            break
        except Exception:
            break

        if user_msg.text and user_msg.text.strip().upper() == "STOP":
            break

        try:
            sent = await user_msg.copy(client.db_channel.id, disable_notification=True)
            collected.append(sent.id)
        except Exception as e:
            await message.reply(f"❌ Failed to store a message:\n<code>{e}</code>")

    await message.reply("✅ Batch collection complete.", reply_markup=ReplyKeyboardRemove())

    if not collected:
        return await message.reply("❌ No messages were added to the batch.")

    bot_username = temp.U_NAME
    db_ch_id = abs(client.db_channel.id)
    start_id = collected[0] * db_ch_id
    end_id = collected[-1] * db_ch_id
    string = f"get-{start_id}-{end_id}"
    base64_string = await encode(string)
    link = f"https://t.me/{bot_username}?start={base64_string}"

    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔁 Share URL", url=f"https://telegram.me/share/url?url={link}")]]
    )
    await message.reply(
        f"<b>Here is your custom batch link:</b>\n\n{link}",
        reply_markup=reply_markup,
    )

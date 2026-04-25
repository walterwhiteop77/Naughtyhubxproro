from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, InputMediaVideo
from database.users_db import db
from info import PROTECT_CONTENT, DAILY_LIMIT, PREMIUM_DAILY_LIMIT, VERIFICATION_DAILY_LIMIT, FSUB, IS_VERIFY
import asyncio
from plugins.verification import av_x_verification
from plugins.ban_manager import ban_manager
from utils import temp, auto_delete_message, is_user_joined


# ========================= GET VIDEO ========================= #

@Client.on_message(filters.command("getvideo") | filters.regex(r"(?i)get video"))
async def handle_video_request(client, m: Message):

    if not m.from_user:
        return

    if FSUB and not await is_user_joined(client, m):
        return

    user_id = m.from_user.id
    username = m.from_user.username or m.from_user.first_name or "Unknown"

    if await ban_manager.check_ban(client, m):
        return

    is_premium = await db.has_premium_access(user_id)
    current_limit = PREMIUM_DAILY_LIMIT if is_premium else DAILY_LIMIT
    used = await db.get_video_count(user_id) or 0

    # ---------------- LIMIT SYSTEM ---------------- #

    if is_premium:
        if used >= PREMIUM_DAILY_LIMIT:
            return await m.reply("❌ Premium limit reached. Try tomorrow.")
    else:
        if used >= VERIFICATION_DAILY_LIMIT:
            return await m.reply("❌ Limit reached.")
        if used >= DAILY_LIMIT:
            if IS_VERIFY:
                verified = await av_x_verification(client, m)
                if not verified:
                    return
            else:
                return await m.reply("❌ Limit reached.")

    # ---------------- SESSION CHECK ---------------- #

    session = temp.SESSIONS.get(user_id)
    if session:
        if session["expire_time"] > asyncio.get_event_loop().time():
            return await m.reply("⚠️ Your previous session is still active!")

    # ---------------- GET VIDEO ---------------- #

    video_id = await db.get_unseen_video(user_id)
    if not video_id:
        video_id = await db.get_random_video()

    if not video_id:
        return await m.reply("❌ No videos found.")

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏮ Back", callback_data="back"),
            InlineKeyboardButton("⏭ Next", callback_data="next")
        ]
    ])

    sent = await client.send_video(
        chat_id=m.chat.id,
        video=video_id,
        protect_content=PROTECT_CONTENT,
        caption=f"Powered by: {temp.B_LINK}",
        reply_markup=buttons,
        reply_to_message_id=m.id
    )

    temp.SESSIONS[user_id] = {
        "message_id": sent.id,
        "expire_time": asyncio.get_event_loop().time() + 600
    }

    await db.increase_video_count(user_id, username)

    asyncio.create_task(auto_delete_message(m, sent))


# ========================= CALLBACK ========================= #

@Client.on_callback_query(filters.regex("^(next|back)$"))
async def handle_navigation(client, query):

    await query.answer()

    user_id = query.from_user.id
    action = query.data

    session = temp.SESSIONS.get(user_id)

    if not session:
        return await query.answer("❌ Session expired!", show_alert=True)

    # ---------------- GET VIDEO ---------------- #

    if action == "next":
        video_id = await db.get_unseen_video(user_id)
        if not video_id:
            video_id = await db.get_random_video()

    elif action == "back":
        video_id = await db.get_random_video()

    if not video_id:
        return await query.answer("❌ No video available!", show_alert=True)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏮ Back", callback_data="back"),
            InlineKeyboardButton("⏭ Next", callback_data="next")
        ]
    ])

    try:
        await query.message.edit_media(
            media=InputMediaVideo(video_id),
            reply_markup=buttons
        )
    except Exception as e:
        await query.message.reply(f"❌ Error: {e}")

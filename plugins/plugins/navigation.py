from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaVideo
from database.users_db import db
from utils import temp


@Client.on_callback_query(filters.regex("^next$"))
async def next_video(client, query):
    await query.answer("Loading next...")

    user_id = query.from_user.id

    video_id = await db.get_unseen_video(user_id)
    if not video_id:
        video_id = await db.get_random_video()

    if not video_id:
        return await query.answer("No videos!", show_alert=True)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏮ Back", callback_data="back"),
            InlineKeyboardButton("⏭ Next", callback_data="next")
        ]
    ])

    await query.message.edit_media(
        media=InputMediaVideo(video_id),
        reply_markup=buttons
    )


@Client.on_callback_query(filters.regex("^back$"))
async def back_video(client, query):
    await query.answer("Loading previous...")

    user_id = query.from_user.id

    video_id = await db.get_random_video()

    if not video_id:
        return await query.answer("No videos!", show_alert=True)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏮ Back", callback_data="back"),
            InlineKeyboardButton("⏭ Next", callback_data="next")
        ]
    ])

    await query.message.edit_media(
        media=InputMediaVideo(video_id),
        reply_markup=buttons
    )

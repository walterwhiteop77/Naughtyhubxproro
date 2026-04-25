from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaVideo
from database.users_db import db

print("🔥 NAVIGATION PLUGIN LOADED")


@Client.on_callback_query()
async def handle_all_callbacks(client, query):
    print("CLICKED:", query.data)

    await query.answer()

    if query.data == "next":
        video_id = await db.get_random_video()

    elif query.data == "back":
        video_id = await db.get_random_video()

    else:
        return  # ignore other buttons

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

"""
Admin commands for managing video categories.

Commands:
  /setcategory <name>   (reply to an indexed video) — tag that video
  /clearcategory        (reply to an indexed video) — remove its category
  /categories                                       — list configured categories
"""

from pyrogram import Client, filters
from pyrogram.types import Message

from info import ADMINS
from database.player_db import player_db, get_categories


def _is_admin(user_id: int) -> bool:
    return user_id == ADMINS


@Client.on_message(filters.command("categories") & filters.private)
async def list_categories_cmd(client, m: Message):
    if not m.from_user or not _is_admin(m.from_user.id):
        return
    cats = get_categories()
    if not cats:
        return await m.reply(
            "No categories configured. Set the `CATEGORIES` env var, "
            "comma separated. Default: `Desi,Videsi,Leaked,Snaps`."
        )
    txt = "🗂 <b>Configured categories</b>\n\n" + "\n".join(
        f"• <code>{c}</code>" for c in cats
    )
    txt += (
        "\n\n<i>Reply to an indexed video with</i> "
        "<code>/setcategory &lt;name&gt;</code> <i>to tag it.</i>"
    )
    await m.reply(txt)


@Client.on_message(filters.command("setcategory") & filters.private)
async def set_category_cmd(client, m: Message):
    if not m.from_user or not _is_admin(m.from_user.id):
        return

    if not m.reply_to_message or not m.reply_to_message.video:
        return await m.reply(
            "Reply to a video message with `/setcategory <name>`."
        )

    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await m.reply("Usage: `/setcategory <category-name>`")

    category = parts[1].strip()
    valid = get_categories()
    if category not in valid:
        return await m.reply(
            f"Unknown category `{category}`. Configured: "
            + ", ".join(f"`{c}`" for c in valid)
        )

    file_unique_id = m.reply_to_message.video.file_unique_id
    file_id = m.reply_to_message.video.file_id

    existing = await player_db.find_by_unique_id(file_unique_id)
    if not existing:
        return await m.reply(
            "❌ This video is not indexed in the database yet. "
            "Forward / post it through your VIDEO_CHANNEL first."
        )

    await player_db.set_category_by_unique_id(file_unique_id, category)
    await player_db.ensure_video_number(file_id)
    await m.reply(f"✅ Category set to <b>{category}</b>.")


@Client.on_message(filters.command("clearcategory") & filters.private)
async def clear_category_cmd(client, m: Message):
    if not m.from_user or not _is_admin(m.from_user.id):
        return

    if not m.reply_to_message or not m.reply_to_message.video:
        return await m.reply(
            "Reply to a video message with `/clearcategory`."
        )

    file_unique_id = m.reply_to_message.video.file_unique_id
    await player_db.set_category_by_unique_id(file_unique_id, None)
    await m.reply("✅ Category cleared.")

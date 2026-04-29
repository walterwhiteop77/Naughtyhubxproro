"""
Per-category channel indexer.

Configuration (env var, defined alongside the others in your environment —
no info.py changes required):

    CATEGORY_CHANNELS = "Desi:-1001234 Videsi:-1005678 Leaked:-1009999 Snaps:-1002222"

Each entry is `<CategoryName>:<channel_id>`. Entries can be separated by
spaces and/or commas. Category names should also appear in your
`CATEGORIES` env var (default `Desi,Videsi,Leaked,Snaps`) so the player's
category picker shows them.

Behaviour:
- A video posted in any mapped channel is added to the shared `videoz`
  collection (deduplicated by file_unique_id, same as the original
  indexer) and tagged with the corresponding category.
- A stable numeric Video ID is assigned on insert.
- If `SEND_POST=True`, a thumbnail post is cross-posted to `POST_CHANNEL`
  with the same shortlink + thumbnail flow as your existing
  `post_channel.py`, plus a `📂 Category:` line.
- Coexists with the original `post_channel.py` — that file still handles
  `VIDEO_CHANNEL` (uncategorized) and `BRAZZER_CHANNEL`. Do NOT put the
  same channel id in both `VIDEO_CHANNEL` and `CATEGORY_CHANNELS` or the
  video will be cross-posted twice.
"""

import os

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from info import POST_CHANNEL, POST_SHORTLINK, SEND_POST, NO_IMG
from database.users_db import db
from database.player_db import player_db
from utils import temp, get_shortlink, generate_weird_name, generate_thumbnail


def _parse_channels() -> dict:
    raw = os.environ.get("CATEGORY_CHANNELS", "")
    raw = raw.replace(",", " ")
    mapping = {}
    for entry in raw.split():
        if ":" not in entry:
            continue
        name, cid = entry.rsplit(":", 1)
        try:
            mapping[int(cid)] = name.strip()
        except ValueError:
            continue
    return mapping


CATEGORY_CHANNEL_MAP = _parse_channels()


# Only register the handler if the user actually configured channels.
if CATEGORY_CHANNEL_MAP:
    _CHANNEL_IDS = list(CATEGORY_CHANNEL_MAP.keys())

    @Client.on_message(filters.video & filters.chat(_CHANNEL_IDS))
    async def index_category_videos(client, m: Message):
        try:
            category = CATEGORY_CHANNEL_MAP.get(m.chat.id)
            if not category:
                return

            file_id = m.video.file_id
            file_unique_id = m.video.file_unique_id
            file_name = generate_weird_name() + ".mp4"

            # Insert (idempotent) + tag with category + assign numeric id
            is_new = await db.add_video(file_unique_id, file_id)
            await player_db.set_category_by_unique_id(file_unique_id, category)
            video_number = await player_db.ensure_video_number(file_id)

            if is_new:
                print(
                    f"✅ [{category}] New: {file_name} "
                    f"(#{video_number}, msg {m.id})"
                )
            else:
                print(
                    f"♻️ [{category}] Re-tagged: {file_name} "
                    f"(#{video_number})"
                )

            # ----- SEND_POST cross-post -----
            if not SEND_POST:
                return

            if not temp.U_NAME:
                me = await client.get_me()
                temp.U_NAME = me.username

            link = f"https://t.me/{temp.U_NAME}?start=avx-{file_unique_id}"
            shortlink = link
            if POST_SHORTLINK:
                try:
                    shortlink = await get_shortlink(link)
                except Exception as e:
                    print("Shortlink Error:", e)

            caption = (
                f"<b>{file_name}</b>\n"
                f"📂 <b>Category:</b> {category}\n\n"
                f"<i>Tap below to watch.</i>"
            )
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 ɢᴇᴛ ᴠɪᴅᴇᴏ 📂", url=shortlink)]
            ])

            thumb_to_send = NO_IMG
            try:
                if m.video.thumbs:
                    thumb_file = await client.download_media(
                        m.video.thumbs[0].file_id
                    )
                    if thumb_file:
                        thumb_to_send = thumb_file
                else:
                    video_path = await m.download()
                    gen_thumb = await generate_thumbnail(video_path)
                    if gen_thumb:
                        thumb_to_send = gen_thumb
            except Exception as e:
                print("Thumbnail handling error:", e)

            try:
                await client.send_photo(
                    chat_id=POST_CHANNEL,
                    photo=thumb_to_send,
                    caption=caption,
                    reply_markup=btn,
                )
            except Exception as e:
                print("⚠️ Send post failed, falling back to NO_IMG:", e)
                try:
                    await client.send_photo(
                        chat_id=POST_CHANNEL,
                        photo=NO_IMG,
                        caption=caption,
                        reply_markup=btn,
                    )
                except Exception as e2:
                    print("⚠️ NO_IMG fallback failed:", e2)

        except Exception as e:
            print(f"❌ Category indexer error: {e}")

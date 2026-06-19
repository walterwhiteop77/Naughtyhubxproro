"""
Category channels — auto-indexer + diagnostic command.

Category channels are managed via bot commands (stored in MongoDB):
  /addcatchannel <name> <channel_id>   — add a category channel
  /editcatname   <old> <new>           — rename a category (updates all tagged videos)
  /delcatchannel <name>                — remove a category channel
  /catchannels                         — list all configured category channels
  /catindex      <name>                — manually index a channel if auto-index fails

Auto-indexing behaviour:
  - Every video posted to a DB-registered category channel is automatically
    indexed and tagged with that category.
  - Channel lookup is done at message-receive time (no restart needed after
    adding a new channel via /addcatchannel).
  - If auto-indexing ever fails, use /catindex <name> to manually re-index.
"""

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from info import POST_CHANNEL, POST_SHORTLINK, SEND_POST, NO_IMG
from database.users_db import db
from database.player_db import player_db
from utils import temp, get_shortlink, generate_weird_name, generate_thumbnail
from helper_func import admin


# -----------------------------------------------------------------------
# /catchannels  — list all DB-backed category channels
# -----------------------------------------------------------------------
@Client.on_message(filters.command("catchannels") & filters.private & admin)
async def catchannels_cmd(_, m: Message):
    if not m.from_user:
        return

    channels = await player_db.get_cat_channels()

    if not channels:
        return await m.reply(
            "📂 <b>No category channels configured yet.</b>\n\n"
            "Use the command below to add one:\n"
            "<code>/addcatchannel &lt;Name&gt; &lt;channel_id&gt;</code>\n\n"
            "<i>Example:</i>\n"
            "<code>/addcatchannel Desi -1001234567890</code>"
        )

    lines = [f"📂 <b>Category Channels</b> ({len(channels)} total)\n"]
    for ch in channels:
        lines.append(f"• <b>{ch['name']}</b> → <code>{ch['channel_id']}</code>")
    lines.append(
        "\n<i>Auto-indexing is active for all channels above.\n"
        "If it ever fails, use /catindex &lt;name&gt; to index manually.</i>"
    )
    await m.reply("\n".join(lines))


# -----------------------------------------------------------------------
# Auto-indexer — fires on every video posted to any channel.
# Checks at runtime if the sender channel is a registered category channel.
# This means /addcatchannel works instantly without a bot restart.
# -----------------------------------------------------------------------
@Client.on_message(filters.video & filters.channel)
async def auto_index_category_video(client, m: Message):
    try:
        # Check if this channel is one of our registered category channels
        ch = await player_db.get_cat_channel_by_id(m.chat.id)
        if not ch:
            return  # Not a category channel — ignore

        category = ch["name"]
        file_id = m.video.file_id
        file_unique_id = m.video.file_unique_id
        file_name = generate_weird_name() + ".mp4"

        # Insert (idempotent) + tag with category + assign numeric id
        is_new = await db.add_video(file_unique_id, file_id)
        await player_db.set_category_by_unique_id(file_unique_id, category)
        video_number = await player_db.ensure_video_number(file_id)

        if is_new:
            print(f"✅ [AutoIndex/{category}] New: {file_name} (#{video_number}, msg {m.id})")
        else:
            print(f"♻️ [AutoIndex/{category}] Re-tagged: {file_name} (#{video_number})")

        # ----- Optional SEND_POST cross-post -----
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
                print(f"[AutoIndex/{category}] Shortlink error: {e}")

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
                thumb_file = await client.download_media(m.video.thumbs[0].file_id)
                if thumb_file:
                    thumb_to_send = thumb_file
            else:
                video_path = await m.download()
                gen_thumb = await generate_thumbnail(video_path)
                if gen_thumb:
                    thumb_to_send = gen_thumb
        except Exception as e:
            print(f"[AutoIndex/{category}] Thumbnail error: {e}")

        try:
            await client.send_photo(
                chat_id=POST_CHANNEL,
                photo=thumb_to_send,
                caption=caption,
                reply_markup=btn,
            )
        except Exception as e:
            print(f"[AutoIndex/{category}] Post failed, trying NO_IMG fallback: {e}")
            try:
                await client.send_photo(
                    chat_id=POST_CHANNEL,
                    photo=NO_IMG,
                    caption=caption,
                    reply_markup=btn,
                )
            except Exception as e2:
                print(f"[AutoIndex/{category}] NO_IMG fallback also failed: {e2}")

    except Exception as e:
        print(f"❌ [AutoIndex] Error: {e}")

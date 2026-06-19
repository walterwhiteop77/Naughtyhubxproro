"""
Admin commands for managing category channels and video categories.

Commands:
  /addcatchannel <name> <channel_id>   — add a category channel to the DB
  /editcatname   <old_name> <new_name> — rename a category (display name + re-tags all videos)
  /delcatchannel <name>                — remove a category channel from the DB
  /catchannels                         — list all configured category channels  (in category_channels.py)
  /catindex      <name>                — manually index videos from a category channel
  /setcategory   <name>   (reply)      — manually tag a single indexed video
  /clearcategory          (reply)      — remove category tag from a single video
  /categories                          — list all known categories (env + DB)
"""

import asyncio
import time

from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database.player_db import player_db
from database.users_db import db
from utils import temp, get_progress_bar, get_readable_time
from helper_func import admin


# -----------------------------------------------------------------------
# /categories  — list all known category names (env + DB)
# -----------------------------------------------------------------------
@Client.on_message(filters.command("categories") & filters.private & admin)
async def list_categories_cmd(client, m: Message):
    if not m.from_user:
        return

    cats = await player_db.get_categories_merged()
    if not cats:
        return await m.reply(
            "No categories configured yet.\n\n"
            "Add one with: <code>/addcatchannel &lt;Name&gt; &lt;channel_id&gt;</code>"
        )
    txt = "🗂 <b>Configured categories</b>\n\n" + "\n".join(
        f"• <code>{c}</code>" for c in cats
    )
    txt += (
        "\n\n<i>Reply to an indexed video with</i> "
        "<code>/setcategory &lt;name&gt;</code> <i>to tag it.</i>"
    )
    await m.reply(txt)


# -----------------------------------------------------------------------
# /addcatchannel <name> <channel_id>
# -----------------------------------------------------------------------
@Client.on_message(filters.command("addcatchannel") & filters.private & admin)
async def add_cat_channel_cmd(client, m: Message):
    if not m.from_user:
        return

    parts = (m.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await m.reply(
            "Usage: <code>/addcatchannel &lt;Name&gt; &lt;channel_id&gt;</code>\n\n"
            "<i>Example:</i>\n"
            "<code>/addcatchannel Desi -1001234567890</code>"
        )

    name = parts[1].strip()
    raw_id = parts[2].strip()

    try:
        channel_id = int(raw_id)
    except ValueError:
        return await m.reply("❌ Channel ID must be a number (e.g. <code>-1001234567890</code>).")

    # Verify the bot can actually reach this channel
    try:
        chat = await client.get_chat(channel_id)
        if chat.type != enums.ChatType.CHANNEL:
            return await m.reply("❌ That ID is not a channel.")
        chat_title = chat.title
    except Exception as e:
        return await m.reply(
            f"❌ Could not fetch channel <code>{channel_id}</code>.\n"
            f"Make sure the bot is an admin in that channel.\n\n<i>Error: {e}</i>"
        )

    is_new = await player_db.add_cat_channel(name, channel_id)

    if is_new:
        await m.reply(
            f"✅ <b>Category channel added!</b>\n\n"
            f"📂 <b>Name:</b> <code>{name}</code>\n"
            f"🆔 <b>Channel:</b> {chat_title} (<code>{channel_id}</code>)\n\n"
            f"<i>Use /catindex {name} to manually index videos from it.</i>"
        )
    else:
        await m.reply(
            f"♻️ <b>Channel already existed — name updated.</b>\n\n"
            f"📂 <b>New name:</b> <code>{name}</code>\n"
            f"🆔 <b>Channel:</b> {chat_title} (<code>{channel_id}</code>)"
        )


# -----------------------------------------------------------------------
# /editcatname <old_name> <new_name>
# -----------------------------------------------------------------------
@Client.on_message(filters.command("editcatname") & filters.private & admin)
async def edit_cat_name_cmd(client, m: Message):
    if not m.from_user:
        return

    parts = (m.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await m.reply(
            "Usage: <code>/editcatname &lt;old_name&gt; &lt;new_name&gt;</code>\n\n"
            "<i>Example:</i>\n"
            "<code>/editcatname Desi DesiVideos</code>\n\n"
            "This renames the category in the channel list <b>and</b> "
            "re-tags all videos that were tagged with the old name."
        )

    old_name = parts[1].strip()
    new_name = parts[2].strip()

    if old_name == new_name:
        return await m.reply("⚠️ Old and new names are the same.")

    existing = await player_db.get_cat_channel_by_name(old_name)
    if not existing:
        return await m.reply(
            f"❌ No category channel named <b>{old_name}</b> found.\n\n"
            f"Use /catchannels to see all configured channels."
        )

    wait_msg = await m.reply(f"⏳ Renaming <b>{old_name}</b> → <b>{new_name}</b>…")
    updated_videos = await player_db.rename_cat_channel(old_name, new_name)

    await wait_msg.edit(
        f"✅ <b>Category renamed successfully!</b>\n\n"
        f"📂 <b>{old_name}</b>  →  <b>{new_name}</b>\n"
        f"🎬 <b>{updated_videos}</b> video(s) re-tagged with the new name.\n\n"
        f"<i>The updated name will now appear in the category section.</i>"
    )


# -----------------------------------------------------------------------
# /delcatchannel <name>
# -----------------------------------------------------------------------
@Client.on_message(filters.command("delcatchannel") & filters.private & admin)
async def del_cat_channel_cmd(client, m: Message):
    if not m.from_user:
        return

    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await m.reply(
            "Usage: <code>/delcatchannel &lt;name&gt;</code>\n\n"
            "<i>Example:</i>\n"
            "<code>/delcatchannel Desi</code>"
        )

    name = parts[1].strip()
    deleted = await player_db.remove_cat_channel(name)

    if deleted:
        await m.reply(
            f"✅ Category channel <b>{name}</b> has been removed.\n\n"
            f"<i>Note: Videos previously tagged as <b>{name}</b> still keep that tag. "
            f"Use /setcategory to re-tag them if needed.</i>"
        )
    else:
        await m.reply(
            f"❌ No category channel named <b>{name}</b> found.\n\n"
            f"Use /catchannels to see all configured channels."
        )


# -----------------------------------------------------------------------
# /catindex <name>   — manually index from a category channel
# -----------------------------------------------------------------------

_cat_index_lock = asyncio.Lock()
_CAT_INDEX_CACHE: dict = {}


@Client.on_message(filters.command("catindex") & filters.private & admin)
async def catindex_cmd(client, m: Message):
    if not m.from_user:
        return

    if _cat_index_lock.locked():
        return await m.reply("⚠️ Another indexing job is already running. Please wait.")

    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        channels = await player_db.get_cat_channels()
        if not channels:
            return await m.reply(
                "No category channels configured yet.\n"
                "Use <code>/addcatchannel &lt;Name&gt; &lt;channel_id&gt;</code> first."
            )
        channel_list = "\n".join(
            f"• <code>/catindex {ch['name']}</code>" for ch in channels
        )
        return await m.reply(
            f"Usage: <code>/catindex &lt;name&gt;</code>\n\n"
            f"<b>Available channels:</b>\n{channel_list}"
        )

    name = parts[1].strip()
    ch = await player_db.get_cat_channel_by_name(name)
    if not ch:
        return await m.reply(
            f"❌ No category channel named <b>{name}</b> found.\n\n"
            f"Use /catchannels to see all configured channels."
        )

    channel_id = ch["channel_id"]

    try:
        chat = await client.get_chat(channel_id)
        if chat.type != enums.ChatType.CHANNEL:
            return await m.reply("❌ That is not a channel.")
    except Exception as e:
        return await m.reply(
            f"❌ Could not reach channel <code>{channel_id}</code>.\n<i>{e}</i>"
        )

    # Ask for last message id / link
    prompt = await m.reply(
        f"📥 <b>Indexing category: {name}</b>\n\n"
        f"Forward the <b>last message</b> from <b>{chat.title}</b> "
        f"or send its message link (https://t.me/c/...)."
    )
    try:
        link_msg = await client.listen(chat_id=m.chat.id, user_id=m.from_user.id)
    except Exception as e:
        return await m.reply(f"Listener error: {e}")
    await prompt.delete()

    last_msg_id = 0
    if link_msg.text and link_msg.text.startswith("https://t.me"):
        try:
            p = link_msg.text.strip().split("/")
            last_msg_id = int(p[-1])
        except Exception:
            return await m.reply("❌ Invalid message link.")
    elif link_msg.forward_from_chat and link_msg.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = link_msg.forward_from_message_id
    else:
        return await m.reply("❌ Please forward a message from the channel or send its link.")

    skip_prompt = await m.reply("Send the message number to <b>skip from</b> (send <code>0</code> to start from the beginning).")
    try:
        skip_msg = await client.listen(chat_id=m.chat.id, user_id=m.from_user.id)
        skip = int(skip_msg.text.strip())
    except Exception:
        await skip_prompt.delete()
        return await m.reply("❌ Invalid number.")
    await skip_prompt.delete()

    # Confirmation
    _CAT_INDEX_CACHE[m.from_user.id] = {
        "chat": chat.id,
        "lst_msg_id": last_msg_id,
        "skip": skip,
        "category": name,
    }

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Start Indexing", callback_data="catindex#start")],
        [InlineKeyboardButton("❌ Cancel", callback_data="catindex#cancel")],
    ])
    await m.reply(
        f"📂 <b>Ready to index:</b>\n\n"
        f"🏷 <b>Category:</b> <code>{name}</code>\n"
        f"📡 <b>Channel:</b> {chat.title}\n"
        f"📨 <b>Total messages:</b> <code>{last_msg_id}</code>\n"
        f"⏭ <b>Skip:</b> <code>{skip}</code>\n\n"
        f"Videos will be tagged as <b>{name}</b> in the database.",
        reply_markup=buttons,
    )


@Client.on_callback_query(filters.regex(r"^catindex#"))
async def catindex_callback(client, query):
    action = query.data.split("#")[1]
    user_id = query.from_user.id

    if action == "cancel":
        _CAT_INDEX_CACHE.pop(user_id, None)
        return await query.message.edit("🛑 Category indexing cancelled.")

    if action == "start":
        if user_id not in _CAT_INDEX_CACHE:
            return await query.answer("⚠️ Session expired. Use /catindex again.", show_alert=True)

        data = _CAT_INDEX_CACHE[user_id]
        await query.message.edit(
            f"🚀 <b>Category indexing started…</b>\n"
            f"🏷 Category: <b>{data['category']}</b>"
        )
        await _run_catindex(
            client=client,
            chat_id=data["chat"],
            lst_msg_id=data["lst_msg_id"],
            skip=data["skip"],
            category=data["category"],
            status_msg=query.message,
        )
        _CAT_INDEX_CACHE.pop(user_id, None)


async def _run_catindex(client, chat_id, lst_msg_id, skip, category, status_msg):
    """
    Index all videos from a channel and tag them with the given category.
    Uses the shared lock so it cannot run simultaneously with /index.
    """
    start_time = time.time()
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    current = skip + 1
    BATCH_SIZE = 20
    temp.CANCEL = False

    async with _cat_index_lock:
        try:
            while current <= lst_msg_id:
                if temp.CANCEL:
                    elapsed = get_readable_time(time.time() - start_time)
                    await status_msg.edit(
                        f"🛑 Indexing cancelled!\n"
                        f"⏱ Time: {elapsed}\n"
                        f"✅ Saved: {total_files}"
                    )
                    return

                end_id = min(current + BATCH_SIZE, lst_msg_id + 1)
                ids = list(range(current, end_id))
                if not ids:
                    break

                try:
                    messages = await client.get_messages(chat_id, ids)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    messages = await client.get_messages(chat_id, ids)
                except Exception:
                    errors += len(ids)
                    current += BATCH_SIZE
                    continue

                for message in messages:
                    if temp.CANCEL:
                        break
                    try:
                        if not message or message.empty:
                            deleted += 1
                            continue
                        if not message.media:
                            no_media += 1
                            continue
                        if message.media not in [
                            enums.MessageMediaType.VIDEO,
                            enums.MessageMediaType.DOCUMENT,
                        ]:
                            unsupported += 1
                            continue

                        media = getattr(message, message.media.value, None)
                        if not media:
                            unsupported += 1
                            continue

                        file_id = media.file_id
                        file_unique_id = media.file_unique_id

                        is_new = await db.add_video(file_unique_id, file_id)
                        await player_db.set_category_by_unique_id(file_unique_id, category)
                        await player_db.ensure_video_number(file_id)

                        if is_new:
                            total_files += 1
                        else:
                            duplicate += 1

                    except Exception as e:
                        print(f"[catindex] Error: {e}")
                        errors += 1

                current += BATCH_SIZE

                # Live progress update
                percentage = (min(current, lst_msg_id) / lst_msg_id) * 100
                prog_bar = get_progress_bar(percentage)
                elapsed = get_readable_time(time.time() - start_time)

                try:
                    await status_msg.edit(
                        f"📊 <b>Category Indexing Progress</b>\n"
                        f"🏷 <b>{category}</b>\n"
                        f"{prog_bar} {percentage:.1f}%\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"📥 Scanned: <code>{min(current, lst_msg_id)}/{lst_msg_id}</code>\n"
                        f"✅ Saved: <code>{total_files}</code>\n"
                        f"♻️ Duplicates: <code>{duplicate}</code>\n"
                        f"🗑 Skipped: <code>{deleted + no_media + unsupported}</code>\n"
                        f"⚠️ Errors: <code>{errors}</code>\n"
                        f"⏱ Elapsed: <code>{elapsed}</code>",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🛑 Cancel", callback_data="catindex#cancel")]
                        ]),
                    )
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except Exception:
                    pass

            elapsed = get_readable_time(time.time() - start_time)
            await status_msg.edit(
                f"✅ <b>Category Indexing Complete!</b>\n\n"
                f"🏷 <b>Category:</b> {category}\n"
                f"⏱ <b>Time:</b> {elapsed}\n"
                f"📥 <b>Total Scanned:</b> <code>{lst_msg_id}</code>\n"
                f"✅ <b>Saved:</b> <code>{total_files}</code>\n"
                f"♻️ <b>Duplicates:</b> <code>{duplicate}</code>\n"
                f"🗑 <b>Non-Media:</b> <code>{no_media + unsupported}</code>\n"
                f"⚠️ <b>Errors:</b> <code>{errors}</code>"
            )

        except Exception as e:
            await status_msg.edit(f"❌ Critical error: {e}")


# -----------------------------------------------------------------------
# /setcategory <name>   (reply to a video)
# -----------------------------------------------------------------------
@Client.on_message(filters.command("setcategory") & filters.private & admin)
async def set_category_cmd(client, m: Message):
    if not m.from_user:
        return

    if not m.reply_to_message or not m.reply_to_message.video:
        return await m.reply(
            "Reply to a video message with <code>/setcategory &lt;name&gt;</code>."
        )

    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await m.reply("Usage: <code>/setcategory &lt;category-name&gt;</code>")

    category = parts[1].strip()
    valid = await player_db.get_categories_merged()
    if category not in valid:
        return await m.reply(
            f"❌ Unknown category <code>{category}</code>.\n\n"
            f"Configured: " + ", ".join(f"<code>{c}</code>" for c in valid)
        )

    file_unique_id = m.reply_to_message.video.file_unique_id
    file_id = m.reply_to_message.video.file_id

    existing = await player_db.find_by_unique_id(file_unique_id)
    if not existing:
        return await m.reply(
            "❌ This video is not indexed in the database yet. "
            "Index it first using /catindex or /index."
        )

    await player_db.set_category_by_unique_id(file_unique_id, category)
    await player_db.ensure_video_number(file_id)
    await m.reply(f"✅ Category set to <b>{category}</b>.")


# -----------------------------------------------------------------------
# /clearcategory   (reply to a video)
# -----------------------------------------------------------------------
@Client.on_message(filters.command("clearcategory") & filters.private & admin)
async def clear_category_cmd(client, m: Message):
    if not m.from_user:
        return

    if not m.reply_to_message or not m.reply_to_message.video:
        return await m.reply(
            "Reply to a video message with <code>/clearcategory</code>."
        )

    file_unique_id = m.reply_to_message.video.file_unique_id
    await player_db.set_category_by_unique_id(file_unique_id, None)
    await m.reply("✅ Category cleared.")

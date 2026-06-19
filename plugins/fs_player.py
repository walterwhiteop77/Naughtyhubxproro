"""
File Store Player
-----------------
Displays file-store links (single file or batch) in a navigable player.

Controls:
  ⏮ Previous  |  📄 X / N  |  Next ▶️
             ✖️ Close
  📥 Get All Files   (batch only)
  🔗 Share Playlist  (batch only)

- Edits the player message in-place when possible (edit_message_media).
- Falls back to delete + resend for types that can't be edited.
- Auto-deletes after the admin-configured timer; shows "Get file again" button.
- "Get All Files" sends every file at once and auto-deletes them all.
- Opening a new batch link closes any previous open player for that user.
"""

import asyncio
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaAudio,
    InputMediaAnimation,
)
from pyrogram.enums import ParseMode

from info import PROTECT_CONTENT, CUSTOM_CAPTION, DISABLE_CHANNEL_BUTTON
from helper_func import get_exp_time
from utils import temp


# ======================================================================
# Default auto-delete (seconds). Overridden by db.fs_get_del_timer().
# ======================================================================
AUTO_DELETE_SECS = 600  # 10 minutes

# ======================================================================
# In-memory sessions:  user_id → session dict
# ======================================================================
FS_SESSIONS: dict = {}


# ======================================================================
# Keyboard
# ======================================================================
def _kbd(user_id: int, index: int, total: int, argument: str = "") -> InlineKeyboardMarkup:
    has_prev = index > 0
    has_next = index < total - 1

    rows = [
        [
            InlineKeyboardButton(
                "⏮ Previous" if has_prev else "⏮",
                callback_data=f"fsp:back:{user_id}" if has_prev else f"fsp:noop:{user_id}",
            ),
            InlineKeyboardButton(
                f"📄 {index + 1} / {total}",
                callback_data=f"fsp:noop:{user_id}",
            ),
            InlineKeyboardButton(
                "Next ▶️" if has_next else "▶️",
                callback_data=f"fsp:next:{user_id}" if has_next else f"fsp:noop:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton("✖️ Close", callback_data=f"fsp:close:{user_id}"),
        ],
    ]

    if total > 1:
        rows.append([
            InlineKeyboardButton(
                "📥 Get All Files",
                callback_data=f"fsp:getall:{user_id}",
            ),
        ])
        if argument:
            share_url = f"https://t.me/{temp.U_NAME}?start={argument}"
            rows.append([
                InlineKeyboardButton(
                    "🔗 Share Playlist",
                    url=f"https://telegram.me/share/url?url={share_url}",
                ),
            ])

    return InlineKeyboardMarkup(rows)


# ======================================================================
# Caption builder
# ======================================================================
def _build_caption(msg, index: int, total: int, auto_del_secs: int) -> str:
    if CUSTOM_CAPTION and msg.document:
        try:
            orig = msg.caption.html if msg.caption else ""
            fname = msg.document.file_name or ""
            cap = CUSTOM_CAPTION.format(previouscaption=orig, filename=fname)
        except Exception:
            cap = msg.caption.html if msg.caption else ""
    else:
        cap = msg.caption.html if msg.caption else ""

    if total > 1:
        cap += f"\n\n📄 <b>File {index + 1} of {total}</b>"

    if auto_del_secs > 0:
        cap += (
            f"\n<blockquote>⏱ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇs ɪɴ {get_exp_time(auto_del_secs)}. "
            "ꜰᴏʀᴡᴀʀᴅ ᴏʀ sᴀᴠᴇ ɪᴛ ʙᴇꜰᴏʀᴇ ᴛʜᴇɴ.</blockquote>"
        )
    return cap


# ======================================================================
# Send a single file by media type
# ======================================================================
async def _send_file(
    client, chat_id: int, msg, caption: str, reply_markup,
    reply_to: int | None = None,
):
    kw = dict(
        chat_id=chat_id,
        caption=caption,
        parse_mode=ParseMode.HTML,
        protect_content=PROTECT_CONTENT,
        reply_markup=reply_markup,
    )
    if reply_to:
        kw["reply_to_message_id"] = reply_to

    if msg.video:
        return await client.send_video(video=msg.video.file_id, **kw)
    if msg.document:
        return await client.send_document(document=msg.document.file_id, **kw)
    if msg.photo:
        return await client.send_photo(photo=msg.photo.file_id, **kw)
    if msg.audio:
        return await client.send_audio(audio=msg.audio.file_id, **kw)
    if msg.animation:
        return await client.send_animation(animation=msg.animation.file_id, **kw)
    if msg.voice:
        return await client.send_voice(voice=msg.voice.file_id, **kw)
    if msg.video_note:
        return await client.send_video_note(
            video_note=msg.video_note.file_id,
            chat_id=chat_id,
            protect_content=PROTECT_CONTENT,
            reply_markup=reply_markup,
        )
    text = (msg.text.html if msg.text else "📄 File")
    return await client.send_message(
        chat_id=chat_id, text=text,
        parse_mode=ParseMode.HTML, reply_markup=reply_markup,
    )


# ======================================================================
# Edit player message to a different file index
# ======================================================================
async def _edit_player(client, session: dict, user_id: int, new_index: int):
    messages = session["messages"]
    total = len(messages)
    msg = messages[new_index]
    auto_del = session.get("auto_del_secs", AUTO_DELETE_SECS)
    argument = session.get("argument", "")

    cap = _build_caption(msg, new_index, total, auto_del)
    kbd = _kbd(user_id, new_index, total, argument)
    chat_id = session["chat_id"]
    player_msg_id = session["player_msg_id"]

    input_media = None
    if msg.video:
        input_media = InputMediaVideo(
            media=msg.video.file_id, caption=cap, parse_mode=ParseMode.HTML)
    elif msg.document:
        input_media = InputMediaDocument(
            media=msg.document.file_id, caption=cap, parse_mode=ParseMode.HTML)
    elif msg.photo:
        input_media = InputMediaPhoto(
            media=msg.photo.file_id, caption=cap, parse_mode=ParseMode.HTML)
    elif msg.audio:
        input_media = InputMediaAudio(
            media=msg.audio.file_id, caption=cap, parse_mode=ParseMode.HTML)
    elif msg.animation:
        input_media = InputMediaAnimation(
            media=msg.animation.file_id, caption=cap, parse_mode=ParseMode.HTML)

    if input_media:
        try:
            await client.edit_message_media(
                chat_id=chat_id,
                message_id=player_msg_id,
                media=input_media,
                reply_markup=kbd,
            )
            session["index"] = new_index
            return
        except Exception:
            pass

    try:
        await client.delete_messages(chat_id, player_msg_id)
    except Exception:
        pass

    sent = await _send_file(client, chat_id, msg, cap, kbd)
    session["player_msg_id"] = sent.id
    session["index"] = new_index
    _schedule_delete(client, user_id)


# ======================================================================
# Auto-delete background task (single player message)
# ======================================================================
async def _auto_delete_task(
    client, user_id: int, chat_id: int,
    player_msg_id: int, notif_msg_id: int | None,
    argument: str, secs: int,
):
    try:
        await asyncio.sleep(secs)
    except asyncio.CancelledError:
        return

    session = FS_SESSIONS.get(user_id)
    if not session or session.get("player_msg_id") != player_msg_id:
        return

    try:
        await client.delete_messages(chat_id, session["player_msg_id"])
    except Exception:
        pass
    FS_SESSIONS.pop(user_id, None)

    if notif_msg_id and argument:
        reload_url = f"https://t.me/{temp.U_NAME}?start={argument}"
        try:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=notif_msg_id,
                text=(
                    "<b>ʏᴏᴜʀ ꜰɪʟᴇ ᴡᴀs ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ!\n\n"
                    "ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ɪᴛ ᴀɢᴀɪɴ 👇</b>"
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("ɢᴇᴛ ꜰɪʟᴇ ᴀɢᴀɪɴ!", url=reload_url)
                ]]),
            )
        except Exception:
            pass


def _schedule_delete(
    client, user_id: int,
    notif_msg_id: int | None = None,
    argument: str = "",
    secs: int = AUTO_DELETE_SECS,
):
    session = FS_SESSIONS.get(user_id)
    if not session:
        return
    old = session.get("delete_task")
    if old and not old.done():
        old.cancel()
    chat_id = session["chat_id"]
    player_msg_id = session["player_msg_id"]
    session["delete_task"] = asyncio.create_task(
        _auto_delete_task(
            client, user_id, chat_id, player_msg_id,
            notif_msg_id, argument, secs,
        )
    )


# ======================================================================
# Auto-delete background task for "Get All Files" bulk send
# ======================================================================
async def _auto_delete_all_task(client, chat_id: int, msg_ids: list, secs: int):
    try:
        await asyncio.sleep(secs)
        # Delete in batches of 100 (Telegram API limit)
        for i in range(0, len(msg_ids), 100):
            try:
                await client.delete_messages(chat_id, msg_ids[i:i + 100])
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


# ======================================================================
# Send all files at once ("Get All Files" action)
# ======================================================================
async def _send_all_files(
    client, user_id: int, messages: list,
    chat_id: int, auto_del_secs: int, argument: str,
):
    """Send every file in the batch sequentially, then auto-delete them all."""
    total = len(messages)
    reload_url = f"https://t.me/{temp.U_NAME}?start={argument}" if argument else None

    get_again_kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("📥 Get Again", url=reload_url)
    ]]) if reload_url else None

    sent_ids = []
    for i, msg in enumerate(messages):
        try:
            cap = msg.caption.html if msg.caption else ""
            cap += f"\n\n📄 <b>File {i + 1} / {total}</b>"
            if auto_del_secs > 0:
                cap += (
                    f"\n<blockquote>⏱ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇs ɪɴ {get_exp_time(auto_del_secs)}. "
                    "ꜰᴏʀᴡᴀʀᴅ ᴏʀ sᴀᴠᴇ ɪᴛ.</blockquote>"
                )
            sent = await _send_file(client, chat_id, msg, cap, get_again_kbd)
            sent_ids.append(sent.id)
        except Exception as e:
            print(f"[getall] Error sending file {i + 1}: {e}")
        # Small delay to avoid Telegram flood limits
        if i < total - 1:
            await asyncio.sleep(0.6)

    if auto_del_secs > 0 and sent_ids:
        asyncio.create_task(
            _auto_delete_all_task(client, chat_id, sent_ids, auto_del_secs)
        )


# ======================================================================
# PUBLIC: Launch the player  (called from command.py)
# ======================================================================
async def launch_fs_player(
    client,
    user_id: int,
    messages: list,
    chat_id: int,
    reply_to: int | None,
    argument: str,
    auto_del_secs: int,
) -> None:
    """
    Send the first file in player format, store session, schedule auto-delete.
    `messages`      — list of Pyrogram Message objects from the DB channel.
    `argument`      — original base64 start token, used for "Get file again" button.
    `auto_del_secs` — 0 disables auto-delete.

    Any previously open player for this user is closed before launching the new one.
    """
    # ── Close any existing open player for this user ──────────────────
    old_session = FS_SESSIONS.pop(user_id, None)
    if old_session:
        old_task = old_session.get("delete_task")
        if old_task and not old_task.done():
            old_task.cancel()
        try:
            await client.delete_messages(
                old_session["chat_id"], old_session["player_msg_id"]
            )
        except Exception:
            pass

    total = len(messages)
    msg = messages[0]
    cap = _build_caption(msg, 0, total, auto_del_secs)
    kbd = _kbd(user_id, 0, total, argument)

    sent = await _send_file(client, chat_id, msg, cap, kbd, reply_to)

    session = {
        "messages": messages,
        "index": 0,
        "chat_id": chat_id,
        "player_msg_id": sent.id,
        "auto_del_secs": auto_del_secs,
        "argument": argument,
        "delete_task": None,
    }
    FS_SESSIONS[user_id] = session

    notif_msg_id = None
    if auto_del_secs > 0:
        try:
            notif = await client.send_message(
                chat_id=chat_id,
                text=(
                    f"<b>Tʜɪs Fɪʟᴇ ᴡɪʟʟ ʙᴇ Dᴇʟᴇᴛᴇᴅ ɪɴ {get_exp_time(auto_del_secs)}.\n"
                    "Pʟᴇᴀsᴇ sᴀᴠᴇ ᴏʀ ꜰᴏʀᴡᴀʀᴅ ɪᴛ ᴛᴏ ʏᴏᴜʀ Saved Messages.</b>"
                ),
                reply_to_message_id=sent.id,
            )
            notif_msg_id = notif.id
        except Exception:
            pass

    _schedule_delete(client, user_id, notif_msg_id, argument, auto_del_secs)


# ======================================================================
# Callback handler for player buttons
# ======================================================================
@Client.on_callback_query(
    filters.regex(r"^fsp:(next|back|close|noop|getall):\d+$"),
    group=-1,
)
async def fs_player_cb(client, q: CallbackQuery):
    try:
        parts = q.data.split(":")
        action = parts[1]
        owner_id = int(parts[2])

        if q.from_user.id != owner_id:
            await q.answer("This player is not for you.", show_alert=True)
            raise StopPropagation

        if action == "noop":
            await q.answer()
            raise StopPropagation

        session = FS_SESSIONS.get(owner_id)

        # ── Get All Files ──────────────────────────────────────────────
        if action == "getall":
            if not session:
                await q.answer("Session expired. Open the link again.", show_alert=True)
                raise StopPropagation

            # Cancel scheduled delete and close the player
            old_task = session.get("delete_task")
            if old_task and not old_task.done():
                old_task.cancel()
            try:
                await client.delete_messages(session["chat_id"], session["player_msg_id"])
            except Exception:
                pass

            msgs = session["messages"]
            auto_del = session.get("auto_del_secs", AUTO_DELETE_SECS)
            arg = session.get("argument", "")
            ch_id = session["chat_id"]
            FS_SESSIONS.pop(owner_id, None)

            await q.answer(f"📥 Sending all {len(msgs)} files…")
            await _send_all_files(client, owner_id, msgs, ch_id, auto_del, arg)
            raise StopPropagation

        # ── Session validity check (for next / back / close) ──────────
        if not session or session.get("player_msg_id") != q.message.id:
            try:
                await q.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await q.answer(
                "This player has expired. Open the link again.",
                show_alert=True,
            )
            raise StopPropagation

        # ── Close ──────────────────────────────────────────────────────
        if action == "close":
            task = session.get("delete_task")
            if task and not task.done():
                task.cancel()
            try:
                await client.delete_messages(
                    session["chat_id"], session["player_msg_id"]
                )
            except Exception:
                pass
            FS_SESSIONS.pop(owner_id, None)
            await q.answer("Player closed.")
            raise StopPropagation

        # ── Next / Previous ────────────────────────────────────────────
        current = session["index"]
        total = len(session["messages"])

        if action == "next":
            new_index = current + 1
            if new_index >= total:
                await q.answer("You're already at the last file.", show_alert=True)
                raise StopPropagation
        else:  # back
            new_index = current - 1
            if new_index < 0:
                await q.answer("You're already at the first file.", show_alert=True)
                raise StopPropagation

        await q.answer(f"File {new_index + 1} of {total}")
        await _edit_player(client, session, owner_id, new_index)

    except StopPropagation:
        raise
    except Exception as e:
        try:
            await q.answer(f"Error: {e}", show_alert=True)
        except Exception:
            pass
        raise StopPropagation

"""
/bookmarks — list & replay the user's saved videos.

Replaying a bookmarked video is FREE and does NOT consume the daily
limit (it's a re-watch of a video the user explicitly chose to keep).
This rewards the bookmark feature and makes premium tags like Download
even more useful.
"""

from pyrogram import Client, filters, StopPropagation
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)

from database.player_db import player_db, ALL_VIDEOS_LABEL
from info import PROTECT_CONTENT, FSUB
from plugins.ban_manager import ban_manager
from plugins.get_video import (
    ACTIVE_PLAYERS,
    _render_caption,
    _render_keyboard,
    _schedule_auto_delete,
)
from utils import is_user_joined


PAGE_SIZE = 5


# ----------------------------------------------------------------------
# Page renderer
# ----------------------------------------------------------------------
async def _build_page(user_id: int, page: int = 0):
    file_ids = await player_db.list_bookmarks(user_id, limit=200)
    total = len(file_ids)

    if total == 0:
        return (
            "📑 <b>You have no bookmarks yet.</b>\n\n"
            "Open <b>/getvideo</b> and tap <b>📑 Bookmark</b> on any "
            "video in the player to save it here for unlimited replays."
        ), None, 0, 0

    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * PAGE_SIZE
    chunk = file_ids[start:start + PAGE_SIZE]

    rows = []
    for fid in chunk:
        n = await player_db.ensure_video_number(fid)
        cat = (await player_db.get_category(fid)) or ALL_VIDEOS_LABEL
        rows.append([
            InlineKeyboardButton(
                f"▶️ #{n} · 📂 {cat}",
                callback_data=f"bm:play:{user_id}:{fid}",
            ),
            InlineKeyboardButton(
                "🗑",
                callback_data=f"bm:rem:{user_id}:{page}:{fid}",
            ),
        ])

    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                "⬅️", callback_data=f"bm:page:{user_id}:{page - 1}"
            ))
        nav.append(InlineKeyboardButton(
            f"{page + 1}/{pages}", callback_data=f"bm:noop:{user_id}"
        ))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(
                "➡️", callback_data=f"bm:page:{user_id}:{page + 1}"
            ))
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("✖️ Close", callback_data=f"bm:close:{user_id}")
    ])

    text = (
        f"📑 <b>Your Bookmarks</b> ({total})\n"
        f"<i>Tap a video to play it — replays don't count toward your daily limit.</i>"
    )
    return text, InlineKeyboardMarkup(rows), page, pages


# ======================================================================
# /bookmarks
# ======================================================================
@Client.on_message(filters.command("bookmarks"))
async def bookmarks_cmd(client, m: Message):
    if not m.from_user:
        return

    if FSUB and not await is_user_joined(client, m):
        return

    if await ban_manager.check_ban(client, m):
        return

    text, kb, _, _ = await _build_page(m.from_user.id, 0)
    if kb is None:
        return await m.reply(text)
    await m.reply(text, reply_markup=kb, disable_web_page_preview=True)


# ======================================================================
# Callback dispatcher (group=-1 to outrank command.py's catch-all)
# ======================================================================
@Client.on_callback_query(
    filters.regex(r"^bm:(play|rem|page|noop|close):.+$"), group=-1
)
async def bookmark_callback(client, q: CallbackQuery):
    try:
        await _bookmark_callback_impl(client, q)
    except StopPropagation:
        raise
    except Exception as e:
        try:
            await q.answer(f"Error: {e}", show_alert=True)
        except Exception:
            pass
    raise StopPropagation


async def _bookmark_callback_impl(client, q: CallbackQuery):
    parts = q.data.split(":", 4)  # action, owner, [extra1], [extra2/file_id]
    action = parts[1]
    owner_id = int(parts[2])

    if q.from_user.id != owner_id:
        return await q.answer(
            "This bookmarks list isn't for you.", show_alert=True
        )

    if action == "noop":
        return await q.answer()

    # ----- CLOSE -----
    if action == "close":
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("Closed")

    # ----- PAGE -----
    if action == "page":
        page = int(parts[3])
        text, kb, _, _ = await _build_page(owner_id, page)
        try:
            if kb is None:
                await q.message.edit_text(text)
            else:
                await q.message.edit_text(
                    text, reply_markup=kb, disable_web_page_preview=True
                )
        except Exception:
            pass
        return await q.answer()

    # ----- REMOVE -----
    if action == "rem":
        page = int(parts[3])
        file_id = parts[4]
        if await player_db.is_bookmarked(owner_id, file_id):
            await player_db.toggle_bookmark(owner_id, file_id)
        text, kb, _, _ = await _build_page(owner_id, page)
        try:
            if kb is None:
                await q.message.edit_text(text)
            else:
                await q.message.edit_text(
                    text, reply_markup=kb, disable_web_page_preview=True
                )
        except Exception:
            pass
        return await q.answer("🗑 Removed")

    # ----- PLAY -----
    if action == "play":
        file_id = parts[3]

        # Tear down any existing player so we have a single active one
        existing = ACTIVE_PLAYERS.get(owner_id)
        if existing:
            task = existing.get("delete_task")
            if task and not task.done():
                task.cancel()
            for mid in (
                existing.get("message_id"),
                existing.get("cat_menu_msg_id"),
            ):
                if mid:
                    try:
                        await client.delete_messages(existing["chat_id"], mid)
                    except Exception:
                        pass
            try:
                if existing.get("trigger_msg"):
                    await existing["trigger_msg"].delete()
            except Exception:
                pass
            ACTIVE_PLAYERS.pop(owner_id, None)

        # Send a fresh player at this video (replays are FREE — no count++)
        try:
            caption = await _render_caption(file_id)
            kb = await _render_keyboard(
                owner_id, file_id, index=0, history_len=1, category=None
            )
            sent = await client.send_video(
                chat_id=q.message.chat.id,
                video=file_id,
                protect_content=PROTECT_CONTENT,
                caption=caption,
                reply_to_message_id=q.message.id,
                reply_markup=kb,
            )
            ACTIVE_PLAYERS[owner_id] = {
                "client": client,
                "chat_id": q.message.chat.id,
                "message_id": sent.id,
                "trigger_msg": q.message,
                "history": [file_id],
                "index": 0,
                "category": None,
                "cat_menu_msg_id": None,
                "delete_task": None,
            }
            _schedule_auto_delete(owner_id, q.message.chat.id, sent.id)
            return await q.answer("▶️ Playing")
        except Exception as e:
            return await q.answer(f"Failed to play: {e}", show_alert=True)

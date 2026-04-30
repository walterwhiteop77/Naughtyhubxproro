"""
/bookmarks — list & replay the user's saved videos.

Replaying a bookmarked video is FREE and does NOT consume the daily
limit (it's a re-watch of a video the user explicitly chose to keep).
This rewards the bookmark feature and makes premium tags like Download
even more useful.

Caps:
  - Free user:    BOOKMARK_LIMIT_FREE     bookmarks (default 5)
  - Premium user: BOOKMARK_LIMIT_PREMIUM  bookmarks (default 15)

IMPORTANT: callback_data is hard-capped at 64 bytes by Telegram. We
therefore use the short numeric Video ID (`video_number`) as the public
handle inside callbacks, NOT the raw file_id (which is ~70+ chars and
would silently break the buttons).

NOTE: The cross-plugin import of player helpers from `plugins.get_video`
is deferred to inside the Play handler so that any startup hiccup in
get_video can't prevent /bookmarks from listing or removing items.
"""

import traceback

from pyrogram import Client, filters, StopPropagation
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)

from database.users_db import db
from database.player_db import (
    player_db,
    ALL_VIDEOS_LABEL,
    bookmark_limit_free,
    bookmark_limit_premium,
)
from info import PROTECT_CONTENT


PAGE_SIZE = 5


# ----------------------------------------------------------------------
# Page renderer
# ----------------------------------------------------------------------
async def _build_page(user_id: int, page: int = 0):
    file_ids = await player_db.list_bookmarks(user_id, limit=200)
    total = len(file_ids)

    is_premium = await db.has_premium_access(user_id)
    cap = (
        bookmark_limit_premium() if is_premium
        else bookmark_limit_free()
    )

    if total == 0:
        text = (
            "📑 <b>You have no bookmarks yet.</b>\n\n"
            "Open <b>/getvideo</b> and tap <b>📑 Bookmark</b> on any "
            "video in the player to save it here.\n\n"
            f"<i>Slots: 0 / {cap}</i>"
        )
        return text, None, 0, 0

    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * PAGE_SIZE
    chunk = file_ids[start:start + PAGE_SIZE]

    rows = []
    for fid in chunk:
        n = await player_db.ensure_video_number(fid)
        cat = (await player_db.get_category(fid)) or ALL_VIDEOS_LABEL
        # Use the SHORT numeric video_number in callback_data — file_id
        # is too long (Telegram caps callback_data at 64 bytes).
        rows.append([
            InlineKeyboardButton(
                f"▶️ #{n} · 📂 {cat}",
                callback_data=f"bm:p:{user_id}:{n}",
            ),
            InlineKeyboardButton(
                "🗑",
                callback_data=f"bm:r:{user_id}:{page}:{n}",
            ),
        ])

    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                "⬅️", callback_data=f"bm:pg:{user_id}:{page - 1}"
            ))
        nav.append(InlineKeyboardButton(
            f"{page + 1}/{pages}", callback_data=f"bm:n:{user_id}"
        ))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(
                "➡️", callback_data=f"bm:pg:{user_id}:{page + 1}"
            ))
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("✖️ Close", callback_data=f"bm:x:{user_id}")
    ])

    plan = "Premium" if is_premium else "Free"
    text = (
        f"📑 <b>Your Bookmarks</b>\n"
        f"<i>Slots: {total} / {cap}  ·  Plan: {plan}</i>\n\n"
        f"Tap a video to play it — replays don't count toward your daily limit."
    )
    return text, InlineKeyboardMarkup(rows), page, pages


# ======================================================================
# /bookmarks  (also: /mybookmarks, /saved aliases for discoverability)
# ======================================================================
@Client.on_message(filters.command(["bookmarks", "mybookmarks", "saved"]))
async def bookmarks_cmd(client, m: Message):
    # Loud debug so the user can see in logs whether the handler is reached
    try:
        uid = m.from_user.id if m.from_user else "?"
        print(f"[bookmarks] /bookmarks called by user {uid}")
    except Exception:
        pass

    if not m.from_user:
        return

    try:
        text, kb, _, _ = await _build_page(m.from_user.id, 0)
        if kb is None:
            return await m.reply(text, disable_web_page_preview=True)
        await m.reply(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        traceback.print_exc()
        try:
            await m.reply(f"❌ /bookmarks failed: <code>{e}</code>")
        except Exception:
            pass


# ======================================================================
# Callback dispatcher (group=-1 to outrank command.py's catch-all)
# ======================================================================
@Client.on_callback_query(
    filters.regex(r"^bm:(p|r|pg|n|x):.+$"), group=-1
)
async def bookmark_callback(client, q: CallbackQuery):
    try:
        await _bookmark_callback_impl(client, q)
    except StopPropagation:
        raise
    except Exception as e:
        traceback.print_exc()
        try:
            await q.answer(f"Error: {e}", show_alert=True)
        except Exception:
            pass
    raise StopPropagation


async def _bookmark_callback_impl(client, q: CallbackQuery):
    parts = q.data.split(":")
    # parts: ["bm", action, owner_id, ...]
    action = parts[1]
    owner_id = int(parts[2])

    if q.from_user.id != owner_id:
        return await q.answer(
            "This bookmarks list isn't for you.", show_alert=True
        )

    if action == "n":  # noop (page indicator)
        return await q.answer()

    # ----- CLOSE -----
    if action == "x":
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("Closed")

    # ----- PAGE -----
    if action == "pg":
        page = int(parts[3])
        text, kb, _, _ = await _build_page(owner_id, page)
        try:
            if kb is None:
                await q.message.edit_text(text, disable_web_page_preview=True)
            else:
                await q.message.edit_text(
                    text, reply_markup=kb, disable_web_page_preview=True
                )
        except Exception:
            pass
        return await q.answer()

    # ----- REMOVE -----
    if action == "r":
        page = int(parts[3])
        video_number = int(parts[4])
        file_id = await player_db.get_file_id_by_number(video_number)
        if file_id and await player_db.is_bookmarked(owner_id, file_id):
            await player_db.toggle_bookmark(owner_id, file_id)
        text, kb, _, _ = await _build_page(owner_id, page)
        try:
            if kb is None:
                await q.message.edit_text(text, disable_web_page_preview=True)
            else:
                await q.message.edit_text(
                    text, reply_markup=kb, disable_web_page_preview=True
                )
        except Exception:
            pass
        return await q.answer("🗑 Removed")

    # ----- PLAY -----
    if action == "p":
        video_number = int(parts[3])
        file_id = await player_db.get_file_id_by_number(video_number)
        if not file_id:
            return await q.answer(
                "This video is no longer available.", show_alert=True
            )

        # Lazy import so any issue in get_video.py can't prevent the
        # /bookmarks command itself from working.
        try:
            from plugins.get_video import (
                ACTIVE_PLAYERS,
                _render_caption,
                _render_keyboard,
                _schedule_auto_delete,
            )
        except Exception as e:
            traceback.print_exc()
            return await q.answer(
                f"Player unavailable: {e}", show_alert=True
            )

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
            traceback.print_exc()
            return await q.answer(f"Failed to play: {e}", show_alert=True)

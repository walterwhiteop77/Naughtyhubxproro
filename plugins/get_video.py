"""
Rich inline video player.

Caption  : Video ID, % users liked, Category
Buttons  : 👍 Like  / 👎 Dislike / ⬇️ Download
           ⏮ Previous          / Next ▶️
           🔄 Change Category  / 📑 Bookmark
           ✖️ Close

The player edits a single message in place using `edit_message_media`.
Daily limits from `info.py` (DAILY_LIMIT, VERIFICATION_DAILY_LIMIT,
PREMIUM_DAILY_LIMIT) are honored on every Next/Shuffle that fetches a
brand-new video. Going Back through already-shown videos in the session
is free. Download and Change Category are premium-only so the
subscription stays valuable.
"""

from pyrogram import Client, filters, StopPropagation
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
    InputMediaVideo,
)

import asyncio

from database.users_db import db
from database.player_db import player_db, get_categories, ALL_VIDEOS_LABEL
from info import (
    PROTECT_CONTENT,
    DAILY_LIMIT,
    PREMIUM_DAILY_LIMIT,
    VERIFICATION_DAILY_LIMIT,
    FSUB,
    IS_VERIFY,
)
from plugins.verification import av_x_verification
from plugins.ban_manager import ban_manager
from utils import temp, auto_delete_message, is_user_joined


# ======================================================================
# IN-MEMORY ACTIVE PLAYERS  (one per user)
# ----------------------------------------------------------------------
# user_id -> {
#   "client", "chat_id", "message_id", "trigger_msg",
#   "history": [file_id, ...],
#   "index": int,
#   "category": str | None,           # active filter (None = All Videos)
#   "cat_menu_msg_id": int | None,    # category picker side-message
#   "delete_task": asyncio.Task | None
# }
# ======================================================================
ACTIVE_PLAYERS: dict = {}
PLAYER_AUTO_DELETE_SECONDS = 600  # 10 minutes


# ----------------------------------------------------------------------
# Caption / keyboard rendering
# ----------------------------------------------------------------------
async def _render_caption(file_id: str) -> str:
    video_number = await player_db.ensure_video_number(file_id)
    stats = await player_db.get_reaction_stats(file_id)
    category = await player_db.get_category(file_id) or ALL_VIDEOS_LABEL

    if stats["total"] == 0:
        liked_line = "<i>No ratings yet — be the first!</i>"
    else:
        liked_line = (
            f"<b>{stats['percent']}%</b> users liked this "
            f"<i>({stats['likes']} 👍 / {stats['dislikes']} 👎)</i>"
        )

    return (
        f"🎞 <b>Video ID:</b> <code>{video_number}</code>\n"
        f"{liked_line}\n"
        f"📂 <b>Category:</b> {category}\n\n"
        f"<i>Powered By: {temp.B_LINK}</i>\n"
        "<blockquote>"
        "ᴛʜɪꜱ ꜰɪʟᴇ ᴡɪʟʟ ʙᴇ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇᴅ ᴀꜰᴛᴇʀ 10 ᴍɪɴᴜᴛᴇꜱ. "
        "ꜰᴏʀᴡᴀʀᴅ ᴏʀ ꜱᴀᴠᴇ ɪᴛ ʙᴇꜰᴏʀᴇ ᴛʜᴇɴ."
        "</blockquote>"
    )


async def _render_keyboard(
    user_id: int, file_id: str, index: int, history_len: int, category: str | None
) -> InlineKeyboardMarkup:
    user_react = await player_db.get_user_reaction(user_id, file_id)
    is_bm = await player_db.is_bookmarked(user_id, file_id)

    like_label = ("✅ 👍 Like" if user_react == "like" else "👍 Like")
    dislike_label = ("✅ 👎 Dislike" if user_react == "dislike" else "👎 Dislike")
    bookmark_label = ("📑 Saved" if is_bm else "📑 Bookmark")
    cat_label = f"🔄 Category: {category or ALL_VIDEOS_LABEL}"
    has_back = index > 0
    prev_label = "⏮ Previous" if has_back else "⏮"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(like_label, callback_data=f"vp:like:{user_id}"),
            InlineKeyboardButton(dislike_label, callback_data=f"vp:dislike:{user_id}"),
            InlineKeyboardButton("⬇️ Download", callback_data=f"vp:download:{user_id}"),
        ],
        [
            InlineKeyboardButton(
                prev_label,
                callback_data=(
                    f"vp:back:{user_id}" if has_back else f"vp:noop:{user_id}"
                ),
            ),
            InlineKeyboardButton(
                f"🎬 {index + 1}/{history_len}",
                callback_data=f"vp:noop:{user_id}",
            ),
            InlineKeyboardButton("Next ▶️", callback_data=f"vp:next:{user_id}"),
        ],
        [
            InlineKeyboardButton(cat_label, callback_data=f"vp:catmenu:{user_id}"),
            InlineKeyboardButton(bookmark_label, callback_data=f"vp:bookmark:{user_id}"),
        ],
        [
            InlineKeyboardButton("✖️ Close Player", callback_data=f"vp:close:{user_id}"),
        ],
    ])


def _category_picker(user_id: int, current: str | None) -> InlineKeyboardMarkup:
    cats = get_categories()
    options = cats + [ALL_VIDEOS_LABEL]
    rows = []
    row = []
    for idx, name in enumerate(options):
        prefix = "• " if (
            (current is None and name == ALL_VIDEOS_LABEL) or current == name
        ) else ""
        row.append(InlineKeyboardButton(
            f"{prefix}{name}",
            callback_data=f"vp:setcat:{user_id}:{idx}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("✖️ Cancel", callback_data=f"vp:catclose:{user_id}")
    ])
    return InlineKeyboardMarkup(rows)


# ----------------------------------------------------------------------
# Auto-delete helper for the player message
# ----------------------------------------------------------------------
async def _delete_player_after(user_id: int, chat_id: int, message_id: int):
    try:
        await asyncio.sleep(PLAYER_AUTO_DELETE_SECONDS)
    except asyncio.CancelledError:
        return

    session = ACTIVE_PLAYERS.get(user_id)
    if not session or session.get("message_id") != message_id:
        return

    client = session.get("client")
    trigger_msg = session.get("trigger_msg")
    cat_menu_id = session.get("cat_menu_msg_id")

    for cleanup in (
        lambda: client.delete_messages(chat_id, message_id),
        lambda: trigger_msg.delete() if trigger_msg else None,
        lambda: client.delete_messages(chat_id, cat_menu_id) if cat_menu_id else None,
    ):
        try:
            res = cleanup()
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass

    ACTIVE_PLAYERS.pop(user_id, None)


def _schedule_auto_delete(user_id: int, chat_id: int, message_id: int):
    session = ACTIVE_PLAYERS.get(user_id)
    if not session:
        return
    old = session.get("delete_task")
    if old and not old.done():
        old.cancel()
    session["delete_task"] = asyncio.create_task(
        _delete_player_after(user_id, chat_id, message_id)
    )


# ----------------------------------------------------------------------
# Video fetching
# ----------------------------------------------------------------------
async def _fetch_new_video(user_id: int, category: str | None):
    video_id = await player_db.get_unseen_video(user_id, category)
    if not video_id:
        try:
            video_id = await player_db.get_random_video(category)
        except Exception as e:
            print(f"[Random Video Error] {e}")
            return None
    return video_id


# ----------------------------------------------------------------------
# Limit / verification gates
# ----------------------------------------------------------------------
async def _check_limits_for_message(client, m: Message, user_id: int) -> bool:
    is_premium = await db.has_premium_access(user_id)
    used = await db.get_video_count(user_id) or 0

    limit_reached_msg = (
        f"𝖸𝗈𝗎'𝗏𝖾 𝖱𝖾𝖺𝖼𝗁𝖾𝖽 𝖸𝗈𝗎𝗋 𝖣𝖺𝗂𝗅𝗒 𝖫𝗂𝗆𝗂𝗍 𝖮𝖿 {used} 𝖥𝗂𝗅𝖾𝗌.\n\n"
        "𝖳𝗋𝗒 𝖠𝗀𝖺𝗂𝗇 𝖳𝗈𝗆𝗈𝗋𝗋𝗈𝗐!\n"
        "𝖮𝗋 𝖯𝗎𝗋𝖼𝗁𝖺𝗌𝖾 𝖲𝗎𝖻𝗌𝖼𝗋𝗂𝗉𝗍𝗂𝗈𝗇 𝖳𝗈 𝖡𝗈𝗈𝗌𝗍 𝖸𝗈𝗎𝗋 𝖣𝖺𝗂𝗅𝗒 𝖫𝗂𝗆𝗂𝗍"
    )
    buy_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("• 𝖯𝗎𝗋𝖼𝗁𝖺𝗌𝖾 𝖲𝗎𝖻𝗌𝖼𝗋𝗂𝗉𝗍𝗂𝗈𝗇 •", callback_data="get")]
    ])

    if is_premium:
        if used >= PREMIUM_DAILY_LIMIT:
            await m.reply(
                f"𝖸𝗈𝗎'𝗏𝖾 𝖱𝖾𝖺𝖼𝗁𝖾𝖽 𝖸𝗈𝗎𝗋 𝖯𝗋𝖾𝗆𝗂𝗎𝗆 𝖫𝗂𝗆𝗂𝗍 𝖮𝖿 {PREMIUM_DAILY_LIMIT} 𝖥𝗂𝗅𝖾𝗌.\n"
                f"𝖳𝗋𝗒 𝖠𝗀𝖺𝗂𝗇 𝖳𝗈𝗆𝗈𝗋𝗋𝗈𝗐!"
            )
            return False
    else:
        if used >= VERIFICATION_DAILY_LIMIT:
            await m.reply(limit_reached_msg, reply_markup=buy_button)
            return False
        if used >= DAILY_LIMIT:
            if IS_VERIFY:
                verified = await av_x_verification(client, m)
                if not verified:
                    return False
            else:
                await m.reply(limit_reached_msg, reply_markup=buy_button)
                return False
    return True


async def _check_limits_for_callback(client, q: CallbackQuery, session: dict) -> bool:
    user_id = q.from_user.id
    is_premium = await db.has_premium_access(user_id)
    used = await db.get_video_count(user_id) or 0

    if is_premium:
        if used >= PREMIUM_DAILY_LIMIT:
            await q.answer(
                f"You've reached your premium daily limit of {PREMIUM_DAILY_LIMIT}. "
                "Try again tomorrow.",
                show_alert=True,
            )
            return False
        return True

    if used >= VERIFICATION_DAILY_LIMIT:
        await q.answer(
            f"You've reached your daily limit of {used} files. "
            "Try again tomorrow or buy a subscription.",
            show_alert=True,
        )
        return False

    if used >= DAILY_LIMIT:
        if IS_VERIFY:
            await q.answer("Verification required to continue.")
            trigger = session.get("trigger_msg") or q.message
            verified = await av_x_verification(client, trigger)
            if not verified:
                return False
        else:
            await q.answer("Daily limit reached. Try again tomorrow.", show_alert=True)
            return False
    return True


# ----------------------------------------------------------------------
# Premium upsell helper
# ----------------------------------------------------------------------
async def _send_premium_upsell(client, q: CallbackQuery, session: dict, feature: str):
    await q.answer(
        f"👑 {feature} is a Premium-only feature.\n"
        "Upgrade to unlock it.",
        show_alert=True,
    )
    try:
        upsell = await client.send_message(
            chat_id=session["chat_id"],
            text=(
                f"👑 <b>Premium feature: {feature}</b>\n\n"
                "Upgrade to unlock:\n"
                f"• Up to <b>{PREMIUM_DAILY_LIMIT}</b> videos/day "
                f"(vs <b>{VERIFICATION_DAILY_LIMIT}</b> for free users)\n"
                "• <b>Download</b> any video in original quality\n"
                "• <b>Change Category</b> to filter by your taste\n"
                "• No verification step"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "• 𝖯𝗎𝗋𝖼𝗁𝖺𝗌𝖾 𝖲𝗎𝖻𝗌𝖼𝗋𝗂𝗉𝗍𝗂𝗈𝗇 •",
                    callback_data="get",
                )
            ]]),
            reply_to_message_id=session["message_id"],
        )
        trigger = session.get("trigger_msg")
        if trigger:
            asyncio.create_task(auto_delete_message(trigger, upsell))
    except Exception:
        pass


# ======================================================================
# /getvideo  OR  "get video"
# ======================================================================
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

    # If a player is already active, reuse it
    if user_id in ACTIVE_PLAYERS:
        notice = await m.reply(
            "🎬 <b>Your video player is still active.</b>\n\n"
            "Use the <b>⏮ Previous</b> / <b>Next ▶️</b> buttons on it to switch videos."
        )
        asyncio.create_task(auto_delete_message(m, notice))
        return

    # Limits
    if not await _check_limits_for_message(client, m, user_id):
        return

    # Make sure indexes exist for the new collections
    await player_db.ensure_indexes()

    # Initial fetch (no category filter)
    video_id = await _fetch_new_video(user_id, category=None)
    if not video_id:
        return await m.reply("❌ No videos found in the database.")

    try:
        caption = await _render_caption(video_id)
        keyboard = await _render_keyboard(
            user_id, video_id, index=0, history_len=1, category=None
        )

        sent = await client.send_video(
            chat_id=m.chat.id,
            video=video_id,
            protect_content=PROTECT_CONTENT,
            caption=caption,
            reply_to_message_id=m.id,
            reply_markup=keyboard,
        )

        await db.increase_video_count(user_id, username)

        ACTIVE_PLAYERS[user_id] = {
            "client": client,
            "chat_id": m.chat.id,
            "message_id": sent.id,
            "trigger_msg": m,
            "history": [video_id],
            "index": 0,
            "category": None,
            "cat_menu_msg_id": None,
            "delete_task": None,
        }
        _schedule_auto_delete(user_id, m.chat.id, sent.id)

    except Exception as e:
        await m.reply(f"❌ Failed to send video: {str(e)}")


# ======================================================================
# Callback dispatcher  (group=-1 so it runs before command.py's catch-all)
# ======================================================================
@Client.on_callback_query(
    filters.regex(
        r"^vp:(next|back|close|noop|like|dislike|download|bookmark|catmenu|catclose|setcat):.+$"
    ),
    group=-1,
)
async def video_player_callback(client, q: CallbackQuery):
    try:
        await _video_player_callback_impl(client, q)
    except StopPropagation:
        raise
    except Exception as e:
        try:
            await q.answer(f"Player error: {e}", show_alert=True)
        except Exception:
            pass
    raise StopPropagation


async def _video_player_callback_impl(client, q: CallbackQuery):
    parts = q.data.split(":")
    action = parts[1]
    owner_id = int(parts[2])

    if q.from_user.id != owner_id:
        return await q.answer(
            "This player isn't for you. Send /getvideo to start your own.",
            show_alert=True,
        )

    if action == "noop":
        return await q.answer()

    session = ACTIVE_PLAYERS.get(owner_id)
    if not session:
        try:
            await q.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return await q.answer(
            "This player has expired. Send /getvideo to start a new one.",
            show_alert=True,
        )

    # The category-picker buttons live on a different message — only the main
    # ones must match the player message id.
    is_picker_action = action in ("setcat", "catclose")
    if not is_picker_action and session.get("message_id") != q.message.id:
        return await q.answer(
            "This player has expired. Send /getvideo to start a new one.",
            show_alert=True,
        )

    current_file_id = session["history"][session["index"]]

    # ---------------- CLOSE ----------------
    if action == "close":
        task = session.get("delete_task")
        if task and not task.done():
            task.cancel()
        for mid in (session["message_id"], session.get("cat_menu_msg_id")):
            if mid:
                try:
                    await client.delete_messages(session["chat_id"], mid)
                except Exception:
                    pass
        try:
            if session.get("trigger_msg"):
                await session["trigger_msg"].delete()
        except Exception:
            pass
        ACTIVE_PLAYERS.pop(owner_id, None)
        return await q.answer("Player closed")

    # ---------------- LIKE / DISLIKE ----------------
    if action in ("like", "dislike"):
        new_state = await player_db.set_user_reaction(
            owner_id, current_file_id, action
        )
        msg = (
            f"You {action}d this video." if new_state
            else "Reaction removed."
        )
        await q.answer(msg)
        # Refresh caption (percent may have changed) + keyboard (highlight)
        await _refresh_player(client, session, current_file_id)
        return

    # ---------------- BOOKMARK ----------------
    if action == "bookmark":
        is_now_bm = await player_db.toggle_bookmark(owner_id, current_file_id)
        await q.answer(
            "📑 Bookmarked." if is_now_bm else "Bookmark removed."
        )
        await _refresh_player(client, session, current_file_id)
        return

    # ---------------- DOWNLOAD (premium-only) ----------------
    if action == "download":
        is_premium = await db.has_premium_access(owner_id)
        if not is_premium:
            await _send_premium_upsell(client, q, session, "Download")
            return
        try:
            sent = await client.send_video(
                chat_id=session["chat_id"],
                video=current_file_id,
                protect_content=False,
                caption=(
                    "📥 <b>Download copy</b>\n"
                    "<i>Forward / save this within 10 minutes.</i>"
                ),
                reply_to_message_id=session["message_id"],
            )
            trigger = session.get("trigger_msg")
            if trigger:
                asyncio.create_task(auto_delete_message(trigger, sent))
            await q.answer("📥 Download copy sent.")
        except Exception as e:
            await q.answer(f"Download failed: {e}", show_alert=True)
        return

    # ---------------- CHANGE CATEGORY (premium-only) ----------------
    if action == "catmenu":
        is_premium = await db.has_premium_access(owner_id)
        if not is_premium:
            await _send_premium_upsell(client, q, session, "Change Category")
            return
        # Send / replace the picker message
        old_picker = session.get("cat_menu_msg_id")
        if old_picker:
            try:
                await client.delete_messages(session["chat_id"], old_picker)
            except Exception:
                pass
        try:
            picker = await client.send_message(
                chat_id=session["chat_id"],
                text=(
                    f"🔄 <b>Select Category</b>\n"
                    f"<i>Current:</i> <b>{session.get('category') or ALL_VIDEOS_LABEL}</b>\n"
                    "Choose a category:"
                ),
                reply_markup=_category_picker(owner_id, session.get("category")),
                reply_to_message_id=session["message_id"],
            )
            session["cat_menu_msg_id"] = picker.id
        except Exception as e:
            await q.answer(f"Failed to open picker: {e}", show_alert=True)
            return
        await q.answer()
        return

    if action == "catclose":
        old_picker = session.get("cat_menu_msg_id")
        if old_picker:
            try:
                await client.delete_messages(session["chat_id"], old_picker)
            except Exception:
                pass
            session["cat_menu_msg_id"] = None
        return await q.answer("Cancelled")

    if action == "setcat":
        idx = int(parts[3]) if len(parts) > 3 else 0
        cats = get_categories()
        options = cats + [ALL_VIDEOS_LABEL]
        if idx < 0 or idx >= len(options):
            return await q.answer("Invalid category")
        choice = options[idx]
        new_category = None if choice == ALL_VIDEOS_LABEL else choice

        # Premium re-check (defensive)
        if not await db.has_premium_access(owner_id):
            return await _send_premium_upsell(client, q, session, "Change Category")

        # Limit / verification check (this counts as a fresh fetch)
        if not await _check_limits_for_callback(client, q, session):
            return

        video_id = await _fetch_new_video(owner_id, category=new_category)
        if not video_id:
            return await q.answer(
                f"❌ No videos found in category “{choice}”.",
                show_alert=True,
            )

        username = q.from_user.username or q.from_user.first_name or "Unknown"
        await db.increase_video_count(owner_id, username)

        session["category"] = new_category
        session["history"].append(video_id)
        session["index"] = len(session["history"]) - 1

        await _refresh_player(client, session, video_id)

        # Tear down the picker
        old_picker = session.get("cat_menu_msg_id")
        if old_picker:
            try:
                await client.delete_messages(session["chat_id"], old_picker)
            except Exception:
                pass
            session["cat_menu_msg_id"] = None
        return await q.answer(f"Category: {choice}")

    # ---------------- BACK ----------------
    if action == "back":
        if session["index"] <= 0:
            return await q.answer("This is the first video.")
        session["index"] -= 1
        target = session["history"][session["index"]]
        await _refresh_player(client, session, target)
        return await q.answer()

    # ---------------- NEXT ----------------
    if action == "next":
        if session["index"] < len(session["history"]) - 1:
            session["index"] += 1
            target = session["history"][session["index"]]
            await _refresh_player(client, session, target)
            return await q.answer()

        if not await _check_limits_for_callback(client, q, session):
            return

        video_id = await _fetch_new_video(owner_id, session.get("category"))
        if not video_id:
            return await q.answer(
                "❌ No more videos available in this category.",
                show_alert=True,
            )

        username = q.from_user.username or q.from_user.first_name or "Unknown"
        await db.increase_video_count(owner_id, username)

        session["history"].append(video_id)
        session["index"] = len(session["history"]) - 1
        await _refresh_player(client, session, video_id)
        return await q.answer()


# ----------------------------------------------------------------------
# Edit-in-place helper
# ----------------------------------------------------------------------
async def _refresh_player(client, session: dict, file_id: str):
    owner_id = next(
        (uid for uid, s in ACTIVE_PLAYERS.items() if s is session), None
    )
    if owner_id is None:
        return
    caption = await _render_caption(file_id)
    keyboard = await _render_keyboard(
        owner_id,
        file_id,
        index=session["index"],
        history_len=len(session["history"]),
        category=session.get("category"),
    )
    try:
        await client.edit_message_media(
            chat_id=session["chat_id"],
            message_id=session["message_id"],
            media=InputMediaVideo(media=file_id, caption=caption),
            reply_markup=keyboard,
        )
    except Exception:
        # Caption-only edit (e.g. when only reaction state changed and the
        # underlying file_id is unchanged → Telegram rejects unchanged media)
        try:
            await client.edit_message_caption(
                chat_id=session["chat_id"],
                message_id=session["message_id"],
                caption=caption,
                reply_markup=keyboard,
            )
        except Exception:
            pass

    _schedule_auto_delete(owner_id, session["chat_id"], session["message_id"])

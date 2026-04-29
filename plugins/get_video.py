from os import environ
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
    InputMediaVideo,
)
from database.users_db import db
from info import (
    PROTECT_CONTENT,
    DAILY_LIMIT,
    PREMIUM_DAILY_LIMIT,
    VERIFICATION_DAILY_LIMIT,
    FSUB,
    IS_VERIFY,
)
import asyncio
from plugins.verification import av_x_verification
from plugins.ban_manager import ban_manager
from utils import temp, auto_delete_message, is_user_joined


# ======================================================================
# IN-MEMORY ACTIVE VIDEO PLAYERS (one per user)
# ----------------------------------------------------------------------
# user_id -> {
#   "client":       Pyrogram Client,
#   "chat_id":      int,
#   "message_id":   int,                # the player message we keep editing
#   "trigger_msg":  Message,            # the user's /getvideo message
#   "history":      [file_id, ...],     # videos shown so far in this session
#   "index":        int,                # current position inside `history`
#   "delete_task":  asyncio.Task | None # 10-min auto-delete task
# }
# ======================================================================
ACTIVE_PLAYERS: dict = {}

PLAYER_AUTO_DELETE_SECONDS = 600  # 10 minutes (same as repo's auto_delete_message)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _player_caption() -> str:
    return (
        f"𝘗𝘰𝘸𝘦𝘳𝘦𝘥 𝘉𝘺: {temp.B_LINK}\n\n"
        "<blockquote>"
        "ᴛʜɪꜱ ꜰɪʟᴇ ᴡɪʟʟ ʙᴇ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ᴀꜰᴛᴇʀ 10 ᴍɪɴᴜᴛᴇꜱ.\n"
        "ᴘʟᴇᴀꜱᴇ ꜰᴏʀᴡᴀʀᴅ ᴛʜɪꜱ ꜰɪʟᴇ ꜱᴏᴍᴇᴡʜᴇʀᴇ ᴇʟꜱᴇ "
        "ᴏʀ ꜱᴀᴠᴇ ɪɴ ꜱᴀᴠᴇᴅ ᴍᴇꜱꜱᴀɢᴇꜱ."
        "</blockquote>"
    )


def _player_keyboard(user_id: int, index: int, history_len: int) -> InlineKeyboardMarkup:
    has_back = index > 0
    back_btn = InlineKeyboardButton(
        "⬅️ Back" if has_back else "⏹ Start",
        callback_data=(f"vp:back:{user_id}" if has_back else f"vp:noop:{user_id}"),
    )
    page_btn = InlineKeyboardButton(
        f"🎬 {index + 1}/{history_len}",
        callback_data=f"vp:noop:{user_id}",
    )
    next_btn = InlineKeyboardButton(
        "Next ➡️", callback_data=f"vp:next:{user_id}"
    )
    close_btn = InlineKeyboardButton(
        "✖️ Close Player", callback_data=f"vp:close:{user_id}"
    )
    return InlineKeyboardMarkup([[back_btn, page_btn, next_btn], [close_btn]])


async def _delete_player_after(user_id: int, chat_id: int, message_id: int):
    """Background task: after 10 min, delete the player message + trigger message."""
    try:
        await asyncio.sleep(PLAYER_AUTO_DELETE_SECONDS)
    except asyncio.CancelledError:
        return

    session = ACTIVE_PLAYERS.get(user_id)
    if not session or session.get("message_id") != message_id:
        # The player has already been replaced or closed
        return

    client = session.get("client")
    trigger_msg = session.get("trigger_msg")

    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass
    try:
        if trigger_msg:
            await trigger_msg.delete()
    except Exception:
        pass

    ACTIVE_PLAYERS.pop(user_id, None)


def _schedule_auto_delete(user_id: int, chat_id: int, message_id: int):
    """(Re)start the 10-min auto-delete timer for the active player."""
    session = ACTIVE_PLAYERS.get(user_id)
    if not session:
        return
    old = session.get("delete_task")
    if old and not old.done():
        old.cancel()
    session["delete_task"] = asyncio.create_task(
        _delete_player_after(user_id, chat_id, message_id)
    )


async def _fetch_new_video(user_id: int):
    """Pull a fresh, unseen video — fall back to any random one."""
    video_id = await db.get_unseen_video(user_id)
    if not video_id:
        try:
            video_id = await db.get_random_video()
        except Exception as e:
            print(f"[Random Video Error] {e}")
            return None
    return video_id


async def _check_limits_for_message(client, m: Message, user_id: int) -> bool:
    """
    Limit + verification gate for the initial /getvideo request.
    Returns True if a new video may be sent. Replies to `m` on failure.
    """
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
    """
    Limit + verification gate for the Next button (only when fetching a brand
    new video). On failure shows an alert / sends the verification message in
    chat and returns False.
    """
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

    # ---- Free user ----
    if used >= VERIFICATION_DAILY_LIMIT:
        await q.answer(
            f"You've reached your daily limit of {used} files. "
            "Try again tomorrow or buy a subscription.",
            show_alert=True,
        )
        return False

    if used >= DAILY_LIMIT:
        if IS_VERIFY:
            await q.answer("Verification required to continue.", show_alert=False)
            trigger = session.get("trigger_msg") or q.message
            verified = await av_x_verification(client, trigger)
            if not verified:
                return False
        else:
            await q.answer(
                "Daily limit reached. Try again tomorrow.", show_alert=True
            )
            return False
    return True


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

    # ---------------------------------------------------------------
    # If a player is already active for this user, point them at it
    # ---------------------------------------------------------------
    existing = ACTIVE_PLAYERS.get(user_id)
    if existing:
        notice = await m.reply(
            "🎬 <b>Your video player is still active.</b>\n\n"
            "Use the <b>⬅️ Back</b> / <b>Next ➡️</b> buttons on it to switch videos "
            "instead of starting a new one.\n"
            "Tap <b>✖️ Close Player</b> on the existing player if you want to start over."
        )
        # Auto-clean this little notice using the same helper as the rest of the repo
        asyncio.create_task(auto_delete_message(m, notice))
        return

    # ---------------------------------------------------------------
    # Limits + verification
    # ---------------------------------------------------------------
    allowed = await _check_limits_for_message(client, m, user_id)
    if not allowed:
        return

    # ---------------------------------------------------------------
    # Fetch first video for this player session
    # ---------------------------------------------------------------
    video_id = await _fetch_new_video(user_id)
    if not video_id:
        return await m.reply("❌ No videos found in the database.")

    # ---------------------------------------------------------------
    # Send the player message (video + Next/Back buttons)
    # ---------------------------------------------------------------
    try:
        sent = await client.send_video(
            chat_id=m.chat.id,
            video=video_id,
            protect_content=PROTECT_CONTENT,
            caption=_player_caption(),
            reply_to_message_id=m.id,
            reply_markup=_player_keyboard(user_id, 0, 1),
        )

        # Increase daily count ONLY after successful send
        await db.increase_video_count(user_id, username)

        ACTIVE_PLAYERS[user_id] = {
            "client": client,
            "chat_id": m.chat.id,
            "message_id": sent.id,
            "trigger_msg": m,
            "history": [video_id],
            "index": 0,
            "delete_task": None,
        }
        _schedule_auto_delete(user_id, m.chat.id, sent.id)

    except Exception as e:
        await m.reply(f"❌ Failed to send video: {str(e)}")


# ======================================================================
# Inline-button callbacks: Next / Back / Close / no-op
# ======================================================================
@Client.on_callback_query(filters.regex(r"^vp:(next|back|close|noop):(\d+)$"))
async def video_player_callback(client, q: CallbackQuery):
    action = q.matches[0].group(1)
    owner_id = int(q.matches[0].group(2))

    # Only the user who opened the player may control it
    if q.from_user.id != owner_id:
        return await q.answer(
            "This player isn't for you. Send /getvideo to start your own.",
            show_alert=True,
        )

    if action == "noop":
        return await q.answer()

    session = ACTIVE_PLAYERS.get(owner_id)
    # If the in-memory session was lost (bot restart, expired, etc.) just disarm.
    if not session or session.get("message_id") != q.message.id:
        try:
            await q.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return await q.answer(
            "This player has expired. Send /getvideo to start a new one.",
            show_alert=True,
        )

    # ---------------- CLOSE ----------------
    if action == "close":
        task = session.get("delete_task")
        if task and not task.done():
            task.cancel()
        try:
            await q.message.delete()
        except Exception:
            pass
        try:
            if session.get("trigger_msg"):
                await session["trigger_msg"].delete()
        except Exception:
            pass
        ACTIVE_PLAYERS.pop(owner_id, None)
        return await q.answer("Player closed")

    # ---------------- BACK ----------------
    if action == "back":
        if session["index"] <= 0:
            return await q.answer("This is the first video.", show_alert=False)
        new_index = session["index"] - 1
        target_video = session["history"][new_index]

    # ---------------- NEXT ----------------
    else:  # action == "next"
        if session["index"] < len(session["history"]) - 1:
            # Forward into already-seen history — free, no daily-limit hit
            new_index = session["index"] + 1
            target_video = session["history"][new_index]
        else:
            # Need a brand new video — counts against the daily limit
            allowed = await _check_limits_for_callback(client, q, session)
            if not allowed:
                return

            video_id = await _fetch_new_video(owner_id)
            if not video_id:
                return await q.answer(
                    "❌ No more videos available.", show_alert=True
                )

            username = (
                q.from_user.username or q.from_user.first_name or "Unknown"
            )
            await db.increase_video_count(owner_id, username)

            session["history"].append(video_id)
            new_index = len(session["history"]) - 1
            target_video = video_id

    # ---------------- Swap the video in place ----------------
    try:
        await q.message.edit_media(
            media=InputMediaVideo(
                media=target_video,
                caption=_player_caption(),
            ),
            reply_markup=_player_keyboard(
                owner_id, new_index, len(session["history"])
            ),
        )
        session["index"] = new_index
        # Reset the 10-min auto-delete clock so an actively used player isn't nuked
        _schedule_auto_delete(owner_id, session["chat_id"], session["message_id"])
        try:
            await q.answer()
        except Exception:
            pass
    except Exception as e:
        await q.answer(f"Failed to switch video: {e}", show_alert=True)

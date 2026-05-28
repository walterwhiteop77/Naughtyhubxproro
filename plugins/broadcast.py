from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid
import time
import asyncio
import logging
from database.users_db import db
from info import ADMINS
from utils import temp, get_readable_time, users_broadcast

lock = asyncio.Lock()
logger = logging.getLogger(__name__)


def parse_inline_buttons(text: str):
    """
    Parse admin input into InlineKeyboardMarkup.

    Format rules:
      - Each line becomes one row of buttons.
      - Multiple buttons in the same row are separated by a comma.
      - Each button is:  Button Label | https://url.com

    Example:
      Visit Website | https://example.com
      Channel | https://t.me/chan , Support | https://t.me/support

    Returns None if the text is "no" / empty, or raises ValueError on bad format.
    """
    if not text or text.strip().lower() == "no":
        return None

    keyboard = []
    for line_no, line in enumerate(text.strip().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        row = []
        for part in line.split(","):
            part = part.strip()
            if "|" not in part:
                raise ValueError(
                    f"Line {line_no}: missing '|' separator in «{part}»"
                )
            label, _, url = part.partition("|")
            label = label.strip()
            url = url.strip()
            if not label:
                raise ValueError(f"Line {line_no}: button label is empty")
            if not url:
                raise ValueError(f"Line {line_no}: button URL is empty")
            if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
                raise ValueError(
                    f"Line {line_no}: URL must start with http://, https://, or tg://"
                )
            row.append(InlineKeyboardButton(label, url=url))
        if row:
            keyboard.append(row)

    return InlineKeyboardMarkup(keyboard) if keyboard else None


@Client.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def broadcast_users(bot, message):
    if lock.locked():
        return await message.reply("⚠️ A broadcast is already running. Wait for it to finish.")

    # ── Step 1: Pin? ─────────────────────────────────────────────────────────
    ask_pin = await message.reply(
        "<b>📌 Do you want to pin this message for all users?</b>",
        reply_markup=ReplyKeyboardMarkup(
            [["Yes", "No"]], one_time_keyboard=True, resize_keyboard=True
        ),
    )
    try:
        pin_msg = await bot.listen(
            chat_id=message.chat.id, user_id=message.from_user.id, timeout=30
        )
    except asyncio.TimeoutError:
        await ask_pin.delete()
        return await message.reply_text("⏰ Timed out. Broadcast cancelled.")

    if pin_msg.text == "Yes":
        is_pin = True
    elif pin_msg.text == "No":
        is_pin = False
    else:
        await ask_pin.delete()
        return await message.reply_text("❌ Invalid response. Broadcast cancelled.")

    await ask_pin.delete()

    # ── Step 2: Inline buttons? ───────────────────────────────────────────────
    ask_btn = await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "<b>🔘 Do you want to attach inline buttons to this broadcast?</b>\n\n"
            "Reply <code>No</code> to skip.\n\n"
            "<b>Or send buttons in this format:</b>\n"
            "• Each <b>line</b> = one row of buttons\n"
            "• Separate multiple buttons in a row with a <b>comma</b>\n"
            "• Each button: <code>Label | https://url</code>\n\n"
            "<b>Example:</b>\n"
            "<code>Visit Website | https://example.com\n"
            "Channel | https://t.me/chan , Support | https://t.me/grp</code>"
        ),
        reply_markup=ReplyKeyboardRemove(),
    )
    try:
        btn_msg = await bot.listen(
            chat_id=message.chat.id, user_id=message.from_user.id, timeout=60
        )
    except asyncio.TimeoutError:
        await ask_btn.delete()
        return await message.reply_text("⏰ Timed out. Broadcast cancelled.")

    reply_markup = None
    if btn_msg.text and btn_msg.text.strip().lower() != "no":
        try:
            reply_markup = parse_inline_buttons(btn_msg.text)
        except ValueError as e:
            await ask_btn.delete()
            return await message.reply_text(
                f"❌ <b>Invalid button format:</b> {e}\n\n"
                "Broadcast cancelled. Use the correct format and try again."
            )

    await ask_btn.delete()

    # ── Step 3: Start broadcast ───────────────────────────────────────────────
    b_msg = message.reply_to_message
    total_users = await db.total_users_count()
    cancel_btn = [[InlineKeyboardButton("🚫 CANCEL", callback_data="broadcast_cancel#users")]]

    b_sts = await message.reply_text(
        text=(
            f"📢 <b>Broadcast started!</b>\n\n"
            f"Total Users: <code>{total_users}</code>\n"
            f"Completed: <code>0</code>\n"
            f"Success: <code>0</code>"
        ),
        reply_markup=InlineKeyboardMarkup(cancel_btn),
    )

    start_time = time.time()
    users = await db.get_all_users()
    done = 0
    success = 0
    failed = 0

    async with lock:
        async for user in users:
            # Check cancellation flag
            if temp.USERS_CANCEL:
                temp.USERS_CANCEL = False
                time_taken = get_readable_time(time.time() - start_time)
                await b_sts.edit(
                    f"❌ <b>Broadcast cancelled!</b>\n"
                    f"Completed in {time_taken}\n\n"
                    f"Total Users: <code>{total_users}</code>\n"
                    f"Completed: <code>{done}</code>\n"
                    f"Success: <code>{success}</code>",
                    reply_markup=None,
                )
                return

            success_flag, sts = await users_broadcast(
                int(user["id"]), b_msg, is_pin, reply_markup=reply_markup
            )

            if sts == "Success":
                success += 1
            else:
                failed += 1
            done += 1

            # Small proactive delay every 10 sends to avoid Telegram rate limits
            if done % 10 == 0:
                await asyncio.sleep(0.05)

            # Update progress every 20 sends
            if done % 20 == 0:
                try:
                    await b_sts.edit(
                        f"📢 <b>Broadcast in progress...</b>\n\n"
                        f"Total Users: <code>{total_users}</code>\n"
                        f"Completed: <code>{done}</code>\n"
                        f"Success: <code>{success}</code>",
                        reply_markup=InlineKeyboardMarkup(cancel_btn),
                    )
                except Exception:
                    pass

        # Final summary
        time_taken = get_readable_time(time.time() - start_time)
        await b_sts.edit(
            f"✅ <b>Broadcast completed!</b>\n"
            f"Completed in {time_taken}\n\n"
            f"Total Users: <code>{total_users}</code>\n"
            f"Completed: <code>{done}</code>\n"
            f"Success: <code>{success}</code>\n"
            f"Failed: <code>{failed}</code>",
            reply_markup=None,
        )


@Client.on_callback_query(filters.regex(r"^broadcast_cancel"))
async def broadcast_cancel(bot, query):
    _, ident = query.data.split("#")
    if ident == "users":
        await query.answer("Cancellation requested!", show_alert=False)
        await query.message.edit_text("⏳ Cancelling broadcast, please wait...")
        temp.USERS_CANCEL = True

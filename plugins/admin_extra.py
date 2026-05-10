"""
Extra Admin Commands
--------------------
Dynamic admin management (owner-only):
  /add_admin  <user_id> [user_id ...]  — Add one or more admins
  /deladmin   <user_id> [...]|all      — Remove admins
  /admins                              — List all DB admins

Auto-delete timer (admin):
  /dlt_time   <seconds>                — Set file auto-delete time (0 = disabled)
  /check_dlt_time                      — Check current auto-delete time
"""

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from database.users_db import db
from info import OWNER_ID
from helper_func import admin, get_exp_time


CLOSE_BTN = InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_data")]])


# =========================================================
# /add_admin — Add one or more admins (owner only)
# =========================================================
@Client.on_message(filters.private & filters.user(OWNER_ID) & filters.command("add_admin"))
async def add_admins(client: Client, message: Message):
    pro = await message.reply("<b><i>Please wait…</i></b>", quote=True)
    raw_ids = message.text.split()[1:]

    if not raw_ids:
        return await pro.edit(
            "<b>Provide user ID(s) to add as admin.</b>\n\n"
            "<b>Usage:</b> <code>/add_admin user_id1 user_id2 …</code>",
            reply_markup=CLOSE_BTN,
        )

    existing_admins = await db.fs_get_all_admins()
    lines = ""
    added = 0

    for raw_id in raw_ids:
        try:
            uid = int(raw_id)
        except ValueError:
            lines += f"<blockquote>❌ Invalid ID: <code>{raw_id}</code></blockquote>\n"
            continue

        if uid == OWNER_ID:
            lines += f"<blockquote>⚠️ <code>{uid}</code> is the owner — already has full access.</blockquote>\n"
            continue

        if uid in existing_admins:
            lines += f"<blockquote>⚠️ <code>{uid}</code> is already an admin.</blockquote>\n"
            continue

        await db.fs_add_admin(uid)
        lines += f"<blockquote>✅ <code>{uid}</code> added.</blockquote>\n"
        added += 1

    await pro.edit(
        f"<b>Admin update result ({added} added):</b>\n\n{lines.strip()}",
        reply_markup=CLOSE_BTN,
    )


# =========================================================
# /deladmin — Remove admins (owner only)
# =========================================================
@Client.on_message(filters.private & filters.user(OWNER_ID) & filters.command("deladmin"))
async def del_admins(client: Client, message: Message):
    pro = await message.reply("<b><i>Please wait…</i></b>", quote=True)
    raw_ids = message.text.split()[1:]

    if not raw_ids:
        return await pro.edit(
            "<b>Provide user ID(s) to remove, or use <code>all</code> to clear all.</b>\n\n"
            "<b>Usage:</b> <code>/deladmin user_id1 user_id2 … | all</code>",
            reply_markup=CLOSE_BTN,
        )

    existing_admins = await db.fs_get_all_admins()

    # Remove all
    if len(raw_ids) == 1 and raw_ids[0].lower() == "all":
        if not existing_admins:
            return await pro.edit("<blockquote>No admins to remove.</blockquote>", reply_markup=CLOSE_BTN)
        for uid in existing_admins:
            await db.fs_del_admin(uid)
        ids_str = "\n".join(f"<code>{i}</code>" for i in existing_admins)
        return await pro.edit(f"<b>⛔ All admins removed:</b>\n{ids_str}", reply_markup=CLOSE_BTN)

    lines = ""
    for raw_id in raw_ids:
        try:
            uid = int(raw_id)
        except ValueError:
            lines += f"<blockquote>❌ Invalid ID: <code>{raw_id}</code></blockquote>\n"
            continue

        if uid in existing_admins:
            await db.fs_del_admin(uid)
            lines += f"<blockquote>✅ <code>{uid}</code> removed.</blockquote>\n"
        else:
            lines += f"<blockquote>⚠️ <code>{uid}</code> not found in admin list.</blockquote>\n"

    await pro.edit(f"<b>⛔ Admin removal result:</b>\n\n{lines.strip()}", reply_markup=CLOSE_BTN)


# =========================================================
# /admins — List all DB admins (admin only)
# =========================================================
@Client.on_message(filters.private & admin & filters.command("admins"))
async def get_admins(client: Client, message: Message):
    pro = await message.reply("<b><i>Please wait…</i></b>", quote=True)
    admin_ids = await db.fs_get_all_admins()

    if not admin_ids:
        admin_list = "<blockquote>❌ No DB admins found.</blockquote>"
    else:
        admin_list = "\n".join(f"<blockquote>ID: <code>{uid}</code></blockquote>" for uid in admin_ids)

    owner_line = f"<blockquote>👑 Owner: <code>{OWNER_ID}</code> (always admin)</blockquote>"
    await pro.edit(
        f"<b>⚡ Admin List:</b>\n\n{owner_line}\n\n<b>DB Admins:</b>\n{admin_list}",
        reply_markup=CLOSE_BTN,
    )


# =========================================================
# /dlt_time — Set auto-delete timer (admin only)
# =========================================================
@Client.on_message(filters.private & admin & filters.command("dlt_time"))
async def set_dlt_time(client: Client, message: Message):
    if len(message.command) < 2:
        current = await db.fs_get_del_timer()
        return await message.reply(
            "<b>Usage:</b> <code>/dlt_time &lt;seconds&gt;</code>\n\n"
            "• Use <code>0</code> to disable auto-delete.\n"
            f"• Current setting: <code>{current}s</code>"
            + (f" ({get_exp_time(current)})" if current > 0 else " (disabled)")
        )

    try:
        seconds = int(message.command[1])
        if seconds < 0:
            raise ValueError
    except ValueError:
        return await message.reply("❌ Please provide a valid non-negative integer (seconds).")

    await db.fs_set_del_timer(seconds)
    if seconds == 0:
        await message.reply("✅ Auto-delete for file store files has been <b>disabled</b>.")
    else:
        await message.reply(
            f"✅ Auto-delete timer set to <code>{seconds}</code> seconds "
            f"(<b>{get_exp_time(seconds)}</b>)."
        )


# =========================================================
# /check_dlt_time — Check current auto-delete setting (admin)
# =========================================================
@Client.on_message(filters.private & admin & filters.command("check_dlt_time"))
async def check_dlt_time(client: Client, message: Message):
    current = await db.fs_get_del_timer()
    if current == 0:
        await message.reply("⏱ Auto-delete is currently <b>disabled</b>.")
    else:
        await message.reply(
            f"⏱ Current auto-delete timer: <code>{current}</code> seconds "
            f"(<b>{get_exp_time(current)}</b>)."
        )

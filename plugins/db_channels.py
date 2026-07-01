from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from database.users_db import db
from helper_func import admin
from info import DB_CHANNEL


# ================================================================
# Helpers
# ================================================================
async def _db_channels_text() -> str:
    channels = await db.get_db_channels()
    if not channels:
        return (
            "<b>📦 DB Channels</b>\n\n"
            "No extra DB channels added.\n"
            f"<i>Default from env: <code>{DB_CHANNEL}</code></i>"
        )
    lines = ["<b>📦 DB Channels</b>\n"]
    for ch in channels:
        cid = ch["_id"]
        primary = "⭐ Primary" if ch.get("is_primary") else ""
        active = "✅" if ch.get("is_active", True) else "🔴 Inactive"
        lines.append(f"{active} <code>{cid}</code> {primary}")
    lines.append(f"\n<i>Default (env): <code>{DB_CHANNEL}</code></i>")
    return "\n".join(lines)


def _db_channels_keyboard(channels: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        cid = ch["_id"]
        toggle_label = "🔴 Deactivate" if ch.get("is_active", True) else "🟢 Activate"
        primary_label = "⭐ Set Primary" if not ch.get("is_primary") else "✔ Primary"
        rows.append([
            InlineKeyboardButton(f"🗑 Remove {cid}", callback_data=f"dbch_remove_{cid}"),
        ])
        rows.append([
            InlineKeyboardButton(toggle_label, callback_data=f"dbch_toggle_{cid}"),
            InlineKeyboardButton(primary_label, callback_data=f"dbch_primary_{cid}"),
        ])
    rows.append([InlineKeyboardButton("➕ Add Channel", callback_data="dbch_add")])
    return InlineKeyboardMarkup(rows)


# ================================================================
# /listdb — show all DB channels
# ================================================================
@Client.on_message(filters.command("listdb") & admin)
async def listdb_cmd(client: Client, message: Message):
    channels = await db.get_db_channels()
    text = await _db_channels_text()
    keyboard = _db_channels_keyboard(channels)
    await message.reply(text, reply_markup=keyboard)


# ================================================================
# /adddb <channel_id> [primary]
# ================================================================
@Client.on_message(filters.command("adddb") & admin)
async def adddb_cmd(client: Client, message: Message):
    args = message.command[1:]
    if not args:
        return await message.reply(
            "Usage: <code>/adddb -100xxxxxxxxx [primary]</code>\n"
            "Add <code>primary</code> at the end to set as primary channel."
        )
    try:
        channel_id = int(args[0])
    except ValueError:
        return await message.reply("❌ Invalid channel ID. Must be an integer like <code>-1001234567890</code>.")

    is_primary = len(args) > 1 and args[1].lower() == "primary"
    added = await db.add_db_channel(channel_id, is_primary=is_primary)
    if added:
        tag = " and set as <b>primary</b>" if is_primary else ""
        await message.reply(f"✅ Channel <code>{channel_id}</code> added{tag}.")
    else:
        await message.reply(f"⚠️ Channel <code>{channel_id}</code> is already in the list.")


# ================================================================
# /removedb <channel_id>
# ================================================================
@Client.on_message(filters.command("removedb") & admin)
async def removedb_cmd(client: Client, message: Message):
    args = message.command[1:]
    if not args:
        return await message.reply("Usage: <code>/removedb -100xxxxxxxxx</code>")
    try:
        channel_id = int(args[0])
    except ValueError:
        return await message.reply("❌ Invalid channel ID.")

    removed = await db.remove_db_channel(channel_id)
    if removed:
        await message.reply(f"✅ Channel <code>{channel_id}</code> removed.")
    else:
        await message.reply(f"❌ Channel <code>{channel_id}</code> not found in list.")


# ================================================================
# Inline callbacks
# ================================================================
@Client.on_callback_query(filters.regex(r"^dbch_remove_(-?\d+)$") & admin)
async def dbch_remove(client: Client, query: CallbackQuery):
    channel_id = int(query.matches[0].group(1))
    removed = await db.remove_db_channel(channel_id)
    if removed:
        await query.answer(f"Removed {channel_id}.", show_alert=False)
    else:
        await query.answer("Not found.", show_alert=True)
    channels = await db.get_db_channels()
    await query.message.edit_text(
        await _db_channels_text(),
        reply_markup=_db_channels_keyboard(channels),
    )


@Client.on_callback_query(filters.regex(r"^dbch_toggle_(-?\d+)$") & admin)
async def dbch_toggle(client: Client, query: CallbackQuery):
    channel_id = int(query.matches[0].group(1))
    new_status = await db.toggle_db_channel_status(channel_id)
    if new_status is None:
        await query.answer("Channel not found.", show_alert=True)
        return
    label = "activated" if new_status else "deactivated"
    await query.answer(f"Channel {label}.", show_alert=False)
    channels = await db.get_db_channels()
    await query.message.edit_text(
        await _db_channels_text(),
        reply_markup=_db_channels_keyboard(channels),
    )


@Client.on_callback_query(filters.regex(r"^dbch_primary_(-?\d+)$") & admin)
async def dbch_set_primary(client: Client, query: CallbackQuery):
    channel_id = int(query.matches[0].group(1))
    await db.set_primary_db_channel(channel_id)
    await query.answer(f"{channel_id} set as primary.", show_alert=False)
    channels = await db.get_db_channels()
    await query.message.edit_text(
        await _db_channels_text(),
        reply_markup=_db_channels_keyboard(channels),
    )


@Client.on_callback_query(filters.regex(r"^dbch_add$") & admin)
async def dbch_add_inline(client: Client, query: CallbackQuery):
    await query.answer()
    prompt = await query.message.edit_text(
        "<b>Send the channel ID to add</b> (e.g. <code>-1001234567890</code>).\n\n"
        "<i>Append <code>primary</code> after to set as primary, e.g.:</i>\n"
        "<code>-1001234567890 primary</code>\n\n"
        "<i>Timeout: 60 s.</i>",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="dbch_list")]]
        ),
    )
    try:
        reply = await client.listen(
            chat_id=query.from_user.id, filters=filters.text, timeout=60
        )
    except Exception:
        await prompt.edit_text(
            "⏰ Timed out.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀ Back", callback_data="dbch_list")]]
            ),
        )
        return

    parts = reply.text.strip().split()
    await reply.delete()
    try:
        channel_id = int(parts[0])
    except ValueError:
        await prompt.edit_text(
            "❌ Invalid ID.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀ Back", callback_data="dbch_list")]]
            ),
        )
        return

    is_primary = len(parts) > 1 and parts[1].lower() == "primary"
    added = await db.add_db_channel(channel_id, is_primary=is_primary)
    msg = (
        f"✅ Channel <code>{channel_id}</code> added."
        if added
        else f"⚠️ Channel <code>{channel_id}</code> already exists."
    )
    channels = await db.get_db_channels()
    await prompt.edit_text(
        f"{msg}\n\n{await _db_channels_text()}",
        reply_markup=_db_channels_keyboard(channels),
    )


@Client.on_callback_query(filters.regex(r"^dbch_list$") & admin)
async def dbch_list_cb(client: Client, query: CallbackQuery):
    await query.answer()
    channels = await db.get_db_channels()
    await query.message.edit_text(
        await _db_channels_text(),
        reply_markup=_db_channels_keyboard(channels),
    )

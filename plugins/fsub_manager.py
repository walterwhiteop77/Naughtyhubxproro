"""
Dynamic Force-Subscribe Channel Manager
----------------------------------------
Commands (owner or db-admin only):
  /addchnl  <channel_id>           — Add a force-sub channel
  /delchnl  <channel_id>           — Remove a force-sub channel
  /listchnl                        — List all force-sub channels
  /fsub_mode <channel_id> on|off   — Toggle request-mode for a channel
  /delreq   <channel_id>           — Clear join-request user list for a channel

Join-request handler: auto-records users who raise a request to any DB channel.
"""

from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest,
)

from database.users_db import db
from info import OWNER_ID
from helper_func import admin


# =========================================================
# /addchnl — Add a force-sub channel
# =========================================================
@Client.on_message(filters.private & filters.user(OWNER_ID) & filters.command("addchnl"))
async def add_channel(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply(
            "Usage: <code>/addchnl &lt;channel_id&gt; [on|off]</code>\n\n"
            "• <code>on</code>  — request mode (users apply to join)\n"
            "• <code>off</code> — normal join mode (default)"
        )

    try:
        channel_id = int(message.command[1])
    except ValueError:
        return await message.reply("❌ Invalid channel ID. It must be a number.")

    mode = message.command[2].lower() if len(message.command) > 2 else "off"
    if mode not in ("on", "off"):
        mode = "off"

    if await db.fs_channel_exist(channel_id):
        return await message.reply(f"⚠️ Channel <code>{channel_id}</code> is already in the list.")

    try:
        chat = await client.get_chat(channel_id)
        await db.fs_add_channel(channel_id, mode)
        await message.reply(
            f"✅ Channel added!\n\n"
            f"📢 Name: <b>{chat.title}</b>\n"
            f"🆔 ID: <code>{channel_id}</code>\n"
            f"⚙️ Mode: <code>{mode}</code>"
        )
    except Exception as e:
        await message.reply(f"❌ Error: <code>{e}</code>")


# =========================================================
# /delchnl — Remove a force-sub channel
# =========================================================
@Client.on_message(filters.private & filters.user(OWNER_ID) & filters.command("delchnl"))
async def del_channel(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: <code>/delchnl &lt;channel_id&gt;</code>")

    try:
        channel_id = int(message.command[1])
    except ValueError:
        return await message.reply("❌ Invalid channel ID.")

    if not await db.fs_channel_exist(channel_id):
        return await message.reply(f"⚠️ Channel <code>{channel_id}</code> is not in the list.")

    await db.fs_rem_channel(channel_id)
    await message.reply(f"✅ Channel <code>{channel_id}</code> removed from force-sub list.")


# =========================================================
# /listchnl — List all force-sub channels
# =========================================================
@Client.on_message(filters.private & admin & filters.command("listchnl"))
async def list_channels(client: Client, message: Message):
    channel_ids = await db.fs_show_channels()
    if not channel_ids:
        return await message.reply("📭 No force-sub channels configured.")

    lines = []
    for cid in channel_ids:
        mode = await db.fs_get_channel_mode(cid)
        try:
            chat = await client.get_chat(cid)
            name = chat.title
        except Exception:
            name = "Unknown"
        lines.append(f"• <b>{name}</b> | <code>{cid}</code> | mode: <code>{mode}</code>")

    await message.reply(
        "<b>📋 Force-Sub Channels:</b>\n\n" + "\n".join(lines)
    )


# =========================================================
# /fsub_mode — Toggle join-request mode for a channel
# =========================================================
@Client.on_message(filters.private & filters.user(OWNER_ID) & filters.command("fsub_mode"))
async def fsub_mode(client: Client, message: Message):
    if len(message.command) < 3:
        return await message.reply(
            "Usage: <code>/fsub_mode &lt;channel_id&gt; on|off</code>\n\n"
            "• <code>on</code>  — request mode\n"
            "• <code>off</code> — direct join mode"
        )

    try:
        channel_id = int(message.command[1])
    except ValueError:
        return await message.reply("❌ Invalid channel ID.")

    mode = message.command[2].lower()
    if mode not in ("on", "off"):
        return await message.reply("❌ Mode must be <code>on</code> or <code>off</code>.")

    if not await db.fs_channel_exist(channel_id):
        return await message.reply(
            f"⚠️ Channel <code>{channel_id}</code> is not in the force-sub list.\n"
            "Use /addchnl first."
        )

    await db.fs_set_channel_mode(channel_id, mode)
    await message.reply(
        f"✅ Mode for channel <code>{channel_id}</code> set to <code>{mode}</code>."
    )


# =========================================================
# /delreq — Clear join-request tracking for a channel
# =========================================================
@Client.on_message(filters.private & filters.user(OWNER_ID) & filters.command("delreq"))
async def del_req(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: <code>/delreq &lt;channel_id&gt;</code>")

    try:
        channel_id = int(message.command[1])
    except ValueError:
        return await message.reply("❌ Invalid channel ID.")

    await db.fs_clear_req_users(channel_id)
    await message.reply(f"✅ Cleared all join-request records for channel <code>{channel_id}</code>.")


# =========================================================
# JOIN REQUEST HANDLER — Auto-record users who request to join
# =========================================================
@Client.on_chat_join_request()
async def handle_join_request(client: Client, update: ChatJoinRequest):
    try:
        channel_id = update.chat.id
        user_id = update.from_user.id

        # Only track if this channel is in our DB with mode=on
        mode = await db.fs_get_channel_mode(channel_id)
        if mode == "on":
            await db.fs_req_user(channel_id, user_id)
    except Exception as e:
        print(f"[join_request handler error] {e}")

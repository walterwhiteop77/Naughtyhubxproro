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

@Client.on_message(filters.command("broadcast") & filters.private & filters.reply)
async def broadcast_users(bot, message):
    from info import ADMINS as _ADMINS, OWNER_ID as _OWNER_ID
    uid = message.from_user.id
    if uid != _OWNER_ID and uid not in _ADMINS:
        try:
            from database.users_db import db as _db
            if not await _db.fs_admin_exist(uid):
                return await message.reply(
                    "⛔ <b>Access Denied</b>\n\n"
                    "This command is for admins only.\n"
                    "Send /myid to get your Telegram ID, then set it as the <code>ADMINS</code> env var."
                )
        except Exception:
            return await message.reply("⛔ Access Denied.")
    if lock.locked():
        return await message.reply('Currently broadcast processing, Wait for complete.')

    ask_pin = await message.reply(
        '<b>Do you want to pin this message in users?</b>',
        reply_markup=ReplyKeyboardMarkup([['Yes', 'No']], one_time_keyboard=True, resize_keyboard=True)
    )

    try:
        msg = await bot.listen(chat_id=message.chat.id, user_id=message.from_user.id, timeout=30)
    except asyncio.TimeoutError:
        await ask_pin.delete()
        return await message.reply_text('⏰ Timeout. Broadcast cancelled.')

    if msg.text == 'Yes':
        is_pin = True
    elif msg.text == 'No':
        is_pin = False
    else:
        await ask_pin.delete()
        return await message.reply_text('❌ Wrong Response!')

    await ask_pin.delete()
    await bot.send_message(chat_id=message.chat.id, text="Broadcast started...", reply_markup=ReplyKeyboardRemove())

    users = await db.get_all_users()
    b_msg = message.reply_to_message
    b_sts = await message.reply_text(text='<b>ʙʀᴏᴀᴅᴄᴀsᴛɪɴɢ ʏᴏᴜʀ ᴍᴇssᴀɢᴇs ᴛᴏ ᴜsᴇʀs ⌛️</b>')

    start_time = time.time()
    total_users = await db.total_users_count()
    done = 0
    success = 0
    failed = 0

    async with lock:
        async for user in users:
            if temp.USERS_CANCEL:
                temp.USERS_CANCEL = False
                time_taken = get_readable_time(time.time() - start_time)
                await b_sts.edit(
                    f"❌ Users broadcast cancelled!\nCompleted in {time_taken}\n\n"
                    f"Total Users: <code>{total_users}</code>\n"
                    f"Completed: <code>{done}</code>\n"
                    f"Success: <code>{success}</code>"
                )
                return

            success_flag, sts = await users_broadcast(int(user['id']), b_msg, is_pin)
            if sts == 'Success':
                success += 1
            elif sts == 'Error':
                failed += 1
            done += 1

            if done % 20 == 0:
                btn = [[InlineKeyboardButton('CANCEL', callback_data='broadcast_cancel#users')]]
                await b_sts.edit(
                    f"📢 Users broadcast in progress...\n\n"
                    f"Total Users: <code>{total_users}</code>\n"
                    f"Completed: <code>{done}</code>\n"
                    f"Success: <code>{success}</code>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )

        time_taken = get_readable_time(time.time() - start_time)
        await b_sts.edit(
            f"✅ Users broadcast completed!\nCompleted in {time_taken}\n\n"
            f"Total Users: <code>{total_users}</code>\n"
            f"Completed: <code>{done}</code>\n"
            f"Success: <code>{success}</code>\n"
            f"Failed: <code>{failed}</code>"
        )

@Client.on_callback_query(filters.regex(r'^broadcast_cancel'))
async def broadcast_cancel(bot, query):
    _, ident = query.data.split("#")
    if ident == 'users':
        await query.message.edit("ᴛʀʏɪɴɢ ᴛᴏ ᴄᴀɴᴄᴇʟ ᴜsᴇʀs ʙʀᴏᴀᴅᴄᴀsᴛɪɴɢ...")
        temp.USERS_CANCEL = True

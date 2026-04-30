import asyncio
import logging
import random
import string
import pytz
from datetime import datetime
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram import enums
from info import (
    VERIFIED_LOG, TIMEZONE, VERIFY_IMG,
    TUTORIAL_LINK, IS_VERIFY
)
from database.users_db import db
from utils import temp, get_shortlink_av, auto_delete_message
from Script import script

logger = logging.getLogger(__name__)

# --- MAIN VERIFICATION CHECKER ---
async def av_x_verification(client, message):
    user_id = message.from_user.id
    
    # 1. Check if Verification is ON/OFF
    if IS_VERIFY:
        user_verified = await db.is_user_verified(user_id)
    else:
        user_verified = True 
    
    # 2. Agar Verified hai to TRUE return karo
    if user_verified:
        return True
        
    file_id = None
    
    # 🔴 FIX: Check agar message.command None nahi hai tabhi length check karein
    if message.command and len(message.command) > 1:
        file_id = message.command[1]
    
    verify_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))
    await db.create_verify_id(user_id, verify_id, file_id)
    
    # Link Generation
    long_url = f"https://telegram.me/{temp.U_NAME}?start=avbotz_{user_id}_{verify_id}"
    verify_url = await get_shortlink_av(long_url)
    
    buttons = [[
        InlineKeyboardButton(text="⚠️ ᴠᴇʀɪғʏ ⚠️", url=verify_url), 
        InlineKeyboardButton(text="❗ ʜᴏᴡ ᴛᴏ ᴠᴇʀɪғʏ ❗", url=TUTORIAL_LINK)
    ]]
    
    user_name = message.from_user.first_name
    
    # Text Format
    try:
        bin_text = script.VERIFICATION_TEXT.format(user_name, "1/1")
    except:
        bin_text = script.VERIFICATION_TEXT.format(user_name)
        
    dlt = await message.reply_text(
        text=bin_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML
    )
    asyncio.create_task(auto_delete_message(message, dlt))
    return False

# --- VERIFICATION SUCCESS HANDLER (Run on /start) ---
async def verify_user_on_start(client, message):
    try:
        # Check if command exists before splitting
        if not message.command or len(message.command) < 2:
            return False

        data = message.command[1].split("_")       
        if len(data) < 3:
            return False           
        user_id = int(data[1])
        verify_id = data[2]
        
        if message.from_user.id != user_id:
            await message.reply("<b>This link is not for you!</b>")
            return True
            
        verify_id_info = await db.get_verify_id_info(user_id, verify_id)
        if not verify_id_info or verify_id_info["verified"]:
            await message.reply("<b>Lɪɴᴋ Exᴘɪʀᴇᴅ ᴏʀ Aʟʀᴇᴀᴅʏ Usᴇᴅ... Tʀʏ Aɢᴀɪɴ.</b>")
            return True
            
        ist_timezone = pytz.timezone(TIMEZONE)     
        current_time = datetime.now(tz=ist_timezone)
        
        # DB Update: Last Verified Time set karo
        await db.update_notcopy_user(user_id, {"last_verified": current_time})
        await db.update_verify_id_info(user_id, verify_id, {"verified": True})
        
        stored_file_id = verify_id_info.get("file_id")
        if stored_file_id:
            file_link = f"https://t.me/{temp.U_NAME}?start={stored_file_id}"
        else:
            file_link = f"https://t.me/{temp.U_NAME}?start=help"
            
        btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("📂 ɢᴇᴛ ʀᴇǫᴜᴇsᴛᴇᴅ ғɪʟᴇ 📂", url=file_link)
        ]])
        
        txt = script.VERIFY_COMPLETE_TEXT
        
        # Log Channel Message
        if VERIFIED_LOG:
            try:
                await client.send_message(
                    VERIFIED_LOG, 
                    script.VERIFIED_TXT.format(
                        message.from_user.mention, 
                        user_id, 
                        datetime.now(ist_timezone).strftime('%d_%B_%Y'), 
                        "1" 
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to send log: {e}")
                
        await message.reply_photo(
            photo=VERIFY_IMG, 
            caption=txt.format(message.from_user.mention), 
            reply_markup=btn, 
            parse_mode=enums.ParseMode.HTML
        )
        return True
        
    except Exception as e:
        logger.error(f"Verify Error: {e}")
        return False
        

from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
from info import OWNER_ID
from helper_func import admin


@Client.on_message(filters.command("owner_cmd") & admin)
async def admin_cmd(client, message):
    is_owner = message.from_user.id == OWNER_ID

    # Row 1 — Premium management
    row1 = [KeyboardButton("/add_premium"), KeyboardButton("/remove_premium")]
    row2 = [KeyboardButton("/premium_user"), KeyboardButton("/check_user")]

    # Row 3 — User management
    row3 = [KeyboardButton("/ban"), KeyboardButton("/unban")]
    row4 = [KeyboardButton("/blocked"), KeyboardButton("/broadcast")]

    # Row 5 — Stats & database
    row5 = [KeyboardButton("/stats"), KeyboardButton("/all_users_stats")]
    row6 = [KeyboardButton("/deleteall"), KeyboardButton("/index")]

    # Row 7 — Redemption codes
    row7 = [KeyboardButton("/code"), KeyboardButton("/allcodes")]
    row8 = [KeyboardButton("/delete_redeem"), KeyboardButton("/clearcodes")]

    # Row 9 — File store
    row9 = [KeyboardButton("/genlink"), KeyboardButton("/batch")]
    row10 = [KeyboardButton("/custom_batch"), KeyboardButton("/dlt_time")]
    row11 = [KeyboardButton("/check_dlt_time")]

    # Row 12 — Force-subscribe channels (owner only)
    row12 = [KeyboardButton("/addchnl"), KeyboardButton("/delchnl")]
    row13 = [KeyboardButton("/listchnl"), KeyboardButton("/fsub_mode")]
    row14 = [KeyboardButton("/delreq")]

    # Row 15 — Admin management (owner only)
    row15 = [KeyboardButton("/add_admin"), KeyboardButton("/deladmin")]
    row16 = [KeyboardButton("/admins")]

    base_rows = [row1, row2, row3, row4, row5, row6, row7, row8, row9, row10, row11]
    owner_rows = [row12, row13, row14, row15, row16]

    all_rows = base_rows + (owner_rows if is_owner else [])

    reply_markup = ReplyKeyboardMarkup(
        all_rows,
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await message.reply(
        "<b>⚡ Admin Commands 👇</b>\n\n"
        "<i>Tap any command to run it.</i>",
        reply_markup=reply_markup,
    )

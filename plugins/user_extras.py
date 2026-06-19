import pytz
from datetime import datetime, timezone
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.users_db import db
from info import OWNER_ID, OWNER_USERNAME, PREMIUM_DAILY_LIMIT, DAILY_LIMIT, VERIFICATION_DAILY_LIMIT, TIMEZONE


# ================================================================
# /profile — user's plan details
# ================================================================
@Client.on_message(filters.command("profile") & filters.private)
async def profile_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    name = message.from_user.mention

    is_premium = await db.has_premium_access(user_id)
    is_verified = await db.is_user_verified(user_id)
    used_today = await db.get_video_count(user_id)
    user_data = await db.get_user(user_id)

    if is_premium:
        plan_label = "💎 Premium"
        daily_limit = PREMIUM_DAILY_LIMIT
    elif is_verified:
        plan_label = "✅ Verified"
        daily_limit = VERIFICATION_DAILY_LIMIT
    else:
        plan_label = "🆓 Free"
        daily_limit = DAILY_LIMIT

    remaining = max(daily_limit - used_today, 0)

    text = (
        f"<b>👤 Profile</b>\n\n"
        f"<b>Name:</b> {name}\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n\n"
        f"<b>Plan:</b> {plan_label}\n"
        f"<b>Daily Limit:</b> <code>{daily_limit}</code> files\n"
        f"<b>Used Today:</b> <code>{used_today}</code>\n"
        f"<b>Remaining:</b> <code>{remaining}</code>\n"
    )

    if is_premium and user_data:
        expiry = user_data.get("expiry_time")
        if expiry:
            if isinstance(expiry, datetime):
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                tz = pytz.timezone(TIMEZONE)
                expiry_local = expiry.astimezone(tz)
                expiry_str = expiry_local.strftime("%d %b %Y, %I:%M %p")
                text += f"\n<b>Premium Expires:</b> <code>{expiry_str}</code>"

    text += (
        f"\n\n<i>Use /buy to upgrade your plan.</i>"
    )

    await message.reply(text)


# ================================================================
# /request — premium users send content requests to owner
# ================================================================
@Client.on_message(filters.command("request") & filters.private)
async def request_cmd(client: Client, message: Message):
    user_id = message.from_user.id

    if not await db.has_premium_access(user_id):
        await message.reply(
            "❌ <b>This feature is for premium users only.</b>\n\n"
            "Upgrade your plan with /buy to send content requests."
        )
        return

    if len(message.command) < 2:
        await message.reply(
            "📋 <b>Content Request</b>\n\n"
            "Usage: <code>/request your request here</code>\n\n"
            "Example: <code>/request Full movie XYZ 2024 HD</code>"
        )
        return

    request_text = message.text.split(None, 1)[1].strip()
    if len(request_text) < 3:
        await message.reply("❌ Request is too short. Please describe what you want.")
        return

    user_mention = message.from_user.mention
    user_username = f"@{message.from_user.username}" if message.from_user.username else "No username"

    forward_text = (
        f"📋 <b>#ContentRequest</b>\n\n"
        f"<b>From:</b> {user_mention}\n"
        f"<b>Username:</b> {user_username}\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n\n"
        f"<b>Request:</b>\n{request_text}"
    )

    try:
        await client.send_message(
            OWNER_ID,
            forward_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Reply to User", url=f"tg://user?id={user_id}")]
            ]),
        )
        await message.reply(
            "✅ <b>Request sent!</b>\n\n"
            "Your content request has been forwarded to the admin.\n"
            f"You can also contact directly: @{OWNER_USERNAME}"
        )
    except Exception as e:
        await message.reply(
            f"❌ Failed to send request. Please contact @{OWNER_USERNAME} directly."
        )
        print(f"[request_cmd] Error sending to owner: {e}")

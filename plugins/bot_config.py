"""
Bot Admin Configuration Panel — /config

Lets the owner/admins configure every bot setting directly through inline buttons:
  🖼 Images      — Start, Auth, Verify, No-Video, QR-Code
  🔘 Toggles     — FSUB, Verification, Post Shortlink, Protect Content, etc.
  📊 Limits      — Daily limits, Bookmark limits
  ⏱ Timers      — Verify expiry, FS verify expiry, Category verify expiry
  💳 Payment     — UPI ID
  📝 Captions    — Custom caption, Tutorial link, Owner username
  🔗 Shortner    — Link to shortner panel
  📦 DB Channels — Link to DB channels panel

Settings are saved to MongoDB (bot_config collection) and applied live via bot_cfg.
"""

import asyncio
import info
import bot_cfg
from database.users_db import db
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

# ────────────────────────────────────────────────────────────────────────
# /admincheck — debug command (no auth needed)
# Shows your Telegram ID vs OWNER_ID so you can spot mismatches
# Remove this once /config is confirmed working
# ────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("admincheck") & filters.private)
async def admincheck_cmd(client: Client, message: Message):
    uid = message.from_user.id
    owner = info.OWNER_ID
    match = uid == owner
    is_db_admin = False
    try:
        is_db_admin = await db.fs_admin_exist(uid)
    except Exception:
        pass
    status = "✅ You ARE the owner" if match else "❌ ID mismatch — not recognised as owner"
    fix = (
        "✅ /config and /shortner should work for you."
        if (match or is_db_admin) else
        f"❌ Fix: set OWNER_ID={uid} in your environment variables, then restart the bot."
    )
    await message.reply(
        f"<b>🔍 Admin Check</b>\n\n"
        f"Your Telegram ID: <code>{uid}</code>\n"
        f"Bot OWNER_ID set to: <code>{owner}</code>\n"
        f"Match: {status}\n"
        f"DB admin: <code>{is_db_admin}</code>\n\n"
        f"{fix}"
    )




# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _g(key):
    """Get live value for a config key."""
    return bot_cfg.gcfg(key, getattr(info, key, None))


def _bool_icon(val) -> str:
    return "✅" if val else "❌"


def _shorten(s, n=30) -> str:
    if not s:
        return "—"
    s = str(s)
    return s[:n] + "…" if len(s) > n else s


def _fmt_seconds(secs) -> str:
    secs = int(secs or 0)
    if secs <= 0:
        return "∞ (disabled)"
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


async def _save(key, value):
    """Persist a config value to DB and update runtime."""
    await db.set_bot_config(key, value)
    bot_cfg.set_cfg(key, value)


async def _prompt(client, query, prompt_text, *, timeout=120):
    """
    Edit message to show prompt, then listen for text OR photo.
    Returns the reply message, or None on timeout/cancel.
    """
    cancel_btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data="bcfg_cancel")]]
    )
    await query.message.edit_text(prompt_text, reply_markup=cancel_btn)
    try:
        reply = await client.listen(
            chat_id=query.from_user.id,
            user_id=query.from_user.id,
            timeout=timeout,
        )
        if reply and reply.text and reply.text.startswith("/"):
            return None
        return reply
    except asyncio.TimeoutError:
        await query.message.edit_text(
            "⏰ Timed out. No changes made.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀ Back to Config", callback_data="bcfg_main")]]
            ),
        )
        return None
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────────
# Panel builders
# ────────────────────────────────────────────────────────────────────────

def _main_panel_text():
    return (
        "<b>⚙️ Bot Configuration Panel</b>\n\n"
        "Configure every bot setting from here.\n"
        "Changes are saved to DB and applied <b>instantly</b> without restart.\n\n"
        "<i>Select a section below:</i>"
    )


def _main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖼 Images", callback_data="bcfg_images"),
            InlineKeyboardButton("🔘 Toggles", callback_data="bcfg_toggles"),
        ],
        [
            InlineKeyboardButton("📊 Limits", callback_data="bcfg_limits"),
            InlineKeyboardButton("⏱ Timers", callback_data="bcfg_timers"),
        ],
        [
            InlineKeyboardButton("💳 Payment", callback_data="bcfg_payment"),
            InlineKeyboardButton("📝 Captions", callback_data="bcfg_captions"),
        ],
        [
            InlineKeyboardButton("🔗 Shortner Panel", callback_data="bcfg_shortner"),
            InlineKeyboardButton("📦 DB Channels", callback_data="bcfg_dbchannels"),
        ],
    ])


def _back_btn(section="bcfg_main"):
    return InlineKeyboardButton("◀ Back", callback_data=section)


# ────── IMAGES ──────────────────────────────────────────────────────────
def _images_text():
    return (
        "<b>🖼 Images Configuration</b>\n\n"
        f"<b>Start Image:</b>\n<code>{_shorten(_g('START_PIC'), 50)}</code>\n\n"
        f"<b>Auth/FSUB Image:</b>\n<code>{_shorten(_g('AUTH_PICS'), 50)}</code>\n\n"
        f"<b>Verify Image:</b>\n<code>{_shorten(_g('VERIFY_IMG'), 50)}</code>\n\n"
        f"<b>No-Video Image:</b>\n<code>{_shorten(_g('NO_IMG'), 50)}</code>\n\n"
        f"<b>QR Code Image:</b>\n<code>{_shorten(_g('QR_CODE_IMAGE'), 50)}</code>\n\n"
        "<i>Click a button to update. Send a URL or send the image directly.</i>"
    )


def _images_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📷 Start Image", callback_data="bcfg_img_START_PIC"),
            InlineKeyboardButton("📷 Auth Image", callback_data="bcfg_img_AUTH_PICS"),
        ],
        [
            InlineKeyboardButton("📷 Verify Image", callback_data="bcfg_img_VERIFY_IMG"),
            InlineKeyboardButton("📷 No-Video Img", callback_data="bcfg_img_NO_IMG"),
        ],
        [
            InlineKeyboardButton("💳 QR Code", callback_data="bcfg_img_QR_CODE_IMAGE"),
        ],
        [_back_btn()],
    ])


# ────── TOGGLES ─────────────────────────────────────────────────────────
def _toggles_text():
    return (
        "<b>🔘 Feature Toggles</b>\n\n"
        f"{_bool_icon(_g('FSUB'))} <b>Force Subscribe</b>\n"
        f"{_bool_icon(_g('IS_VERIFY'))} <b>Verification (AV)</b>\n"
        f"{_bool_icon(_g('POST_SHORTLINK'))} <b>Post Shortlink</b>\n"
        f"{_bool_icon(_g('PROTECT_CONTENT'))} <b>Protect Content</b>\n"
        f"{_bool_icon(not _g('DISABLE_CHANNEL_BUTTON'))} <b>Channel Button Visible</b>\n"
        f"{_bool_icon(_g('SEND_POST'))} <b>Send Post to Channel</b>\n\n"
        "<i>Tap a button to toggle instantly.</i>"
    )


def _toggles_keyboard():
    def _tlabel(key, label):
        return f"{'✅' if _g(key) else '❌'} {label}"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_tlabel("FSUB", "Force Sub"), callback_data="bcfg_tog_FSUB"),
            InlineKeyboardButton(_tlabel("IS_VERIFY", "Verification"), callback_data="bcfg_tog_IS_VERIFY"),
        ],
        [
            InlineKeyboardButton(_tlabel("POST_SHORTLINK", "Post Shortlink"), callback_data="bcfg_tog_POST_SHORTLINK"),
            InlineKeyboardButton(_tlabel("PROTECT_CONTENT", "Protect Content"), callback_data="bcfg_tog_PROTECT_CONTENT"),
        ],
        [
            InlineKeyboardButton(
                f"{'❌' if _g('DISABLE_CHANNEL_BUTTON') else '✅'} Channel Button",
                callback_data="bcfg_tog_DISABLE_CHANNEL_BUTTON",
            ),
            InlineKeyboardButton(_tlabel("SEND_POST", "Send Post"), callback_data="bcfg_tog_SEND_POST"),
        ],
        [_back_btn()],
    ])


# ────── LIMITS ──────────────────────────────────────────────────────────
def _limits_text():
    return (
        "<b>📊 Daily Limits & Bookmarks</b>\n\n"
        f"<b>Free Daily Limit:</b> <code>{_g('DAILY_LIMIT')}</code>\n"
        f"<b>Verified Daily Limit:</b> <code>{_g('VERIFICATION_DAILY_LIMIT')}</code>\n"
        f"<b>Premium Daily Limit:</b> <code>{_g('PREMIUM_DAILY_LIMIT')}</code>\n\n"
        f"<b>Bookmark Limit (Free):</b> <code>{_g('BOOKMARK_LIMIT_FREE')}</code>\n"
        f"<b>Bookmark Limit (Premium):</b> <code>{_g('BOOKMARK_LIMIT_PREMIUM')}</code>\n\n"
        "<i>Tap a button to set a new value.</i>"
    )


def _limits_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Free Limit", callback_data="bcfg_set_DAILY_LIMIT"),
            InlineKeyboardButton("✏️ Verified Limit", callback_data="bcfg_set_VERIFICATION_DAILY_LIMIT"),
        ],
        [
            InlineKeyboardButton("✏️ Premium Limit", callback_data="bcfg_set_PREMIUM_DAILY_LIMIT"),
        ],
        [
            InlineKeyboardButton("✏️ BM Limit (Free)", callback_data="bcfg_set_BOOKMARK_LIMIT_FREE"),
            InlineKeyboardButton("✏️ BM Limit (Prem)", callback_data="bcfg_set_BOOKMARK_LIMIT_PREMIUM"),
        ],
        [_back_btn()],
    ])


# ────── TIMERS ──────────────────────────────────────────────────────────
def _timers_text():
    return (
        "<b>⏱ Verification Timers</b>\n\n"
        f"<b>AV Verify Expire:</b> <code>{_fmt_seconds(_g('VERIFY_EXPIRE'))}</code>\n"
        f"<b>FS Verify Expire:</b> <code>{_fmt_seconds(_g('FS_VERIFY_EXPIRE'))}</code>\n"
        f"<b>Cat Verify Expire:</b> <code>{_fmt_seconds(_g('CAT_VERIFY_EXPIRE'))}</code>\n\n"
        "<i>Enter new value in seconds. E.g. 3600 = 1h, 86400 = 24h.</i>"
    )


def _timers_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ AV Verify", callback_data="bcfg_set_VERIFY_EXPIRE"),
            InlineKeyboardButton("✏️ FS Verify", callback_data="bcfg_set_FS_VERIFY_EXPIRE"),
        ],
        [
            InlineKeyboardButton("✏️ Cat Verify", callback_data="bcfg_set_CAT_VERIFY_EXPIRE"),
        ],
        [_back_btn()],
    ])


# ────── PAYMENT ─────────────────────────────────────────────────────────
def _payment_text():
    return (
        "<b>💳 Payment Settings</b>\n\n"
        f"<b>UPI ID:</b> <code>{_g('UPI_ID')}</code>\n\n"
        "<i>Tap to update.</i>"
    )


def _payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Update UPI ID", callback_data="bcfg_set_UPI_ID")],
        [_back_btn()],
    ])


# ────── CAPTIONS ────────────────────────────────────────────────────────
def _captions_text():
    return (
        "<b>📝 Captions & Links</b>\n\n"
        f"<b>Custom Caption:</b>\n<code>{_shorten(_g('CUSTOM_CAPTION'), 60)}</code>\n\n"
        f"<b>Tutorial Link:</b>\n<code>{_shorten(_g('TUTORIAL_LINK'), 60)}</code>\n\n"
        f"<b>Owner Username:</b> <code>{_g('OWNER_USERNAME')}</code>\n\n"
        "<i>Tap to update.</i>"
    )


def _captions_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Custom Caption", callback_data="bcfg_set_CUSTOM_CAPTION"),
            InlineKeyboardButton("✏️ Tutorial Link", callback_data="bcfg_set_TUTORIAL_LINK"),
        ],
        [
            InlineKeyboardButton("✏️ Owner Username", callback_data="bcfg_set_OWNER_USERNAME"),
        ],
        [_back_btn()],
    ])


# ────────────────────────────────────────────────────────────────────────
# /config command
# ────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("config") & filters.private)
async def config_cmd(client: Client, message: Message):
    from helper_func import is_admin
    if not await is_admin(message.from_user.id):
        return await message.reply(
            "⛔ <b>Access Denied</b>\n\n"
            "This command is for admins only.\n"
            "Send /myid to get your Telegram ID, then set it as the <code>ADMINS</code> env var."
        )
    await message.reply(_main_panel_text(), reply_markup=_main_keyboard())


# ────────────────────────────────────────────────────────────────────────
# Main navigation callbacks
# ────────────────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^bcfg_main$"))
async def bcfg_main(client, query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(_main_panel_text(), reply_markup=_main_keyboard())


@Client.on_callback_query(filters.regex(r"^bcfg_images$"))
async def bcfg_images(client, query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(_images_text(), reply_markup=_images_keyboard())


@Client.on_callback_query(filters.regex(r"^bcfg_toggles$"))
async def bcfg_toggles(client, query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(_toggles_text(), reply_markup=_toggles_keyboard())


@Client.on_callback_query(filters.regex(r"^bcfg_limits$"))
async def bcfg_limits(client, query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(_limits_text(), reply_markup=_limits_keyboard())


@Client.on_callback_query(filters.regex(r"^bcfg_timers$"))
async def bcfg_timers(client, query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(_timers_text(), reply_markup=_timers_keyboard())


@Client.on_callback_query(filters.regex(r"^bcfg_payment$"))
async def bcfg_payment(client, query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(_payment_text(), reply_markup=_payment_keyboard())


@Client.on_callback_query(filters.regex(r"^bcfg_captions$"))
async def bcfg_captions(client, query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(_captions_text(), reply_markup=_captions_keyboard())


@Client.on_callback_query(filters.regex(r"^bcfg_shortner$"))
async def bcfg_shortner_link(client, query: CallbackQuery):
    await query.answer()
    from plugins.shortner_panel import _shortner_panel_text, _shortner_keyboard
    from database.users_db import db as _db
    settings = await _db.get_shortner_settings()
    await query.message.edit_text(
        await _shortner_panel_text(settings),
        reply_markup=_shortner_keyboard(settings, show_back_to_config=True),
    )


@Client.on_callback_query(filters.regex(r"^bcfg_dbchannels$"))
async def bcfg_dbchannels_link(client, query: CallbackQuery):
    await query.answer()
    from plugins.db_channels import _db_channels_text, _db_channels_keyboard
    from database.users_db import db as _db
    channels = await _db.get_db_channels()
    await query.message.edit_text(
        await _db_channels_text(),
        reply_markup=_db_channels_keyboard(channels),
    )


@Client.on_callback_query(filters.regex(r"^bcfg_cancel$"))
async def bcfg_cancel(client, query: CallbackQuery):
    await query.answer("Cancelled.")
    try:
        client.cancel_listener(chat_id=query.from_user.id)
    except Exception:
        pass
    await query.message.edit_text(_main_panel_text(), reply_markup=_main_keyboard())


# ────────────────────────────────────────────────────────────────────────
# Image update handlers
# ────────────────────────────────────────────────────────────────────────

_IMAGE_LABELS = {
    "START_PIC": "Start Image",
    "AUTH_PICS": "Auth / Force-Sub Image",
    "VERIFY_IMG": "Verification Success Image",
    "NO_IMG": "No-Video Fallback Image",
    "QR_CODE_IMAGE": "Payment QR Code Image",
}


@Client.on_callback_query(filters.regex(r"^bcfg_img_(.+)$"))
async def bcfg_img_update(client: Client, query: CallbackQuery):
    key = query.matches[0].group(1)
    label = _IMAGE_LABELS.get(key, key)
    current = _g(key)
    prompt_text = (
        f"<b>Update: {label}</b>\n\n"
        f"Current: <code>{_shorten(current, 60)}</code>\n\n"
        "📤 <b>Send the new image</b> in one of two ways:\n"
        "• Send a <b>URL</b> (text starting with https://)\n"
        "• <b>Forward or send a photo</b> directly\n\n"
        "<i>Timeout: 120 seconds. Send /cancel to abort.</i>"
    )
    await query.answer()
    reply = await _prompt(client, query, prompt_text)
    if reply is None:
        return

    if reply.text and reply.text.strip().lower() == "/cancel":
        await reply.delete()
        await query.message.edit_text(_images_text(), reply_markup=_images_keyboard())
        return

    if reply.photo:
        value = reply.photo.file_id
        kind = "photo file_id"
    elif reply.text and (reply.text.strip().startswith("http://") or reply.text.strip().startswith("https://")):
        value = reply.text.strip()
        kind = "URL"
    else:
        await reply.delete()
        await query.message.edit_text(
            "❌ Invalid input. Must be a URL or a photo.\n\nReturning to Images section.",
            reply_markup=_images_keyboard(),
        )
        return

    await reply.delete()
    await _save(key, value)
    await query.message.edit_text(
        f"✅ <b>{label} updated!</b>\n\nSaved as {kind}:\n<code>{_shorten(value, 60)}</code>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀ Back to Images", callback_data="bcfg_images")],
        ]),
    )


# ────────────────────────────────────────────────────────────────────────
# Toggle handlers
# ────────────────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^bcfg_tog_(.+)$"))
async def bcfg_toggle(client: Client, query: CallbackQuery):
    key = query.matches[0].group(1)
    current = _g(key)
    new_val = not bool(current)
    await _save(key, new_val)
    state = "enabled ✅" if new_val else "disabled ❌"
    await query.answer(f"{key} {state}", show_alert=False)
    await query.message.edit_text(_toggles_text(), reply_markup=_toggles_keyboard())


# ────────────────────────────────────────────────────────────────────────
# Text / Integer input handlers
# ────────────────────────────────────────────────────────────────────────

_SET_LABELS = {
    "DAILY_LIMIT": ("Free Daily Limit", int, "bcfg_limits"),
    "VERIFICATION_DAILY_LIMIT": ("Verified Daily Limit", int, "bcfg_limits"),
    "PREMIUM_DAILY_LIMIT": ("Premium Daily Limit", int, "bcfg_limits"),
    "BOOKMARK_LIMIT_FREE": ("Free Bookmark Limit", int, "bcfg_limits"),
    "BOOKMARK_LIMIT_PREMIUM": ("Premium Bookmark Limit", int, "bcfg_limits"),
    "VERIFY_EXPIRE": ("AV Verify Expire (seconds)", int, "bcfg_timers"),
    "FS_VERIFY_EXPIRE": ("FS Verify Expire (seconds)", int, "bcfg_timers"),
    "CAT_VERIFY_EXPIRE": ("Category Verify Expire (seconds)", int, "bcfg_timers"),
    "UPI_ID": ("UPI ID", str, "bcfg_payment"),
    "CUSTOM_CAPTION": ("Custom Caption", str, "bcfg_captions"),
    "TUTORIAL_LINK": ("Tutorial Link", str, "bcfg_captions"),
    "OWNER_USERNAME": ("Owner Username", str, "bcfg_captions"),
}


@Client.on_callback_query(filters.regex(r"^bcfg_set_(.+)$"))
async def bcfg_set_value(client: Client, query: CallbackQuery):
    key = query.matches[0].group(1)
    if key not in _SET_LABELS:
        await query.answer("Unknown setting.", show_alert=True)
        return

    label, cast_type, back_cb = _SET_LABELS[key]
    current = _g(key)
    type_hint = "a number" if cast_type == int else "text"
    prompt_text = (
        f"<b>Update: {label}</b>\n\n"
        f"Current: <code>{current}</code>\n\n"
        f"Send {type_hint} as the new value.\n"
        "<i>Timeout: 60 seconds. Send /cancel to abort.</i>"
    )
    await query.answer()
    reply = await _prompt(client, query, prompt_text, timeout=60)
    if reply is None:
        return

    raw = (reply.text or "").strip()
    await reply.delete()

    if raw.lower() == "/cancel":
        await query.message.edit_text(
            _get_section_text(back_cb),
            reply_markup=_get_section_kb(back_cb),
        )
        return

    if cast_type == int:
        try:
            value = int(raw)
        except ValueError:
            await query.message.edit_text(
                f"❌ Invalid number: <code>{raw}</code>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(f"◀ Back", callback_data=back_cb)]]
                ),
            )
            return
    else:
        value = raw

    await _save(key, value)
    await query.message.edit_text(
        f"✅ <b>{label} updated!</b>\n\nNew value: <code>{value}</code>",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("◀ Back", callback_data=back_cb)]]
        ),
    )


# ────────────────────────────────────────────────────────────────────────
# Helper to refresh section view after back navigation
# ────────────────────────────────────────────────────────────────────────

def _get_section_text(cb: str) -> str:
    mapping = {
        "bcfg_limits": _limits_text,
        "bcfg_timers": _timers_text,
        "bcfg_payment": _payment_text,
        "bcfg_captions": _captions_text,
        "bcfg_images": _images_text,
        "bcfg_toggles": _toggles_text,
        "bcfg_main": _main_panel_text,
    }
    fn = mapping.get(cb, _main_panel_text)
    return fn()


def _get_section_kb(cb: str) -> InlineKeyboardMarkup:
    mapping = {
        "bcfg_limits": _limits_keyboard,
        "bcfg_timers": _timers_keyboard,
        "bcfg_payment": _payment_keyboard,
        "bcfg_captions": _captions_keyboard,
        "bcfg_images": _images_keyboard,
        "bcfg_toggles": _toggles_keyboard,
        "bcfg_main": _main_keyboard,
    }
    fn = mapping.get(cb, _main_keyboard)
    return fn()

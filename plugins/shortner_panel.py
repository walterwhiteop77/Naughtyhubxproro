"""
Shortner Settings Panel — /shortner

Configures all three shortlink contexts:
  - Verify Shortner   (SHORTLINK_URL / SHORTLINK_API)       — AV verification links
  - Post Shortner     (POST_SHORTLINK_URL / API)            — post channel links
  - Category Shortner (CAT_SHORTLINK_URL / CAT_SHORTLINK_API) — category verify links

All values saved to MongoDB (fs_settings collection) and applied live to
temp.* without restarting the bot.
"""

import asyncio
import aiohttp
import random
import string
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from database.users_db import db
from info import (
    SHORTLINK_URL, SHORTLINK_API,
    POST_SHORTLINK_URL, POST_SHORTLINK_API,
    CAT_SHORTLINK_URL, CAT_SHORTLINK_API,
    TUTORIAL_LINK,
)
from helper_func import admin
from utils import temp


# ── Utilities ─────────────────────────────────────────────────────────────────

def _rnd_alias(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def _strip_url(raw: str) -> str:
    """Remove https:// / http:// prefix and trailing slashes."""
    s = raw.strip()
    if s.startswith("https://"):
        s = s[len("https://"):]
    elif s.startswith("http://"):
        s = s[len("http://"):]
    return s.rstrip("/")


def _short_api(api: str, n: int = 22) -> str:
    if not api:
        return "— not set —"
    return api[:n] + "…" if len(api) > n else api


async def _test_shortner(url: str, api: str) -> tuple[bool, str]:
    alias = _rnd_alias()
    endpoint = f"https://{url}/api?api={api}&url=https://google.com&alias={alias}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                endpoint, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("status") == "success":
                    return True, data.get("shortenedUrl", "—")
                return False, data.get("message", "Unknown error")
    except Exception as e:
        return False, str(e)


# ── Active-value helpers (live value or env-var fallback) ─────────────────────

def _av_url(s: dict) -> str:
    return s.get("short_url") or SHORTLINK_URL

def _av_api(s: dict) -> str:
    return s.get("short_api") or SHORTLINK_API

def _av_tut(s: dict) -> str:
    return s.get("tutorial_link") or TUTORIAL_LINK

def _post_url(s: dict) -> str:
    return s.get("post_short_url") or POST_SHORTLINK_URL

def _post_api(s: dict) -> str:
    return s.get("post_short_api") or POST_SHORTLINK_API

def _cat_url(s: dict) -> str:
    return s.get("cat_short_url") or CAT_SHORTLINK_URL

def _cat_api(s: dict) -> str:
    v = s.get("cat_short_api") or CAT_SHORTLINK_API
    return v if v else "— not set —"


# ── Panel text ────────────────────────────────────────────────────────────────

async def _shortner_panel_text(s: dict) -> str:
    enabled = s.get("is_enabled", True)
    status = "✅ Enabled" if enabled else "❌ Disabled"
    return (
        "<b>🔗 Shortner Settings</b>\n\n"
        f"<b>Status:</b> {status}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>🔑 Verify Shortner</b> (AV verify links)\n"
        f"  URL: <code>{_av_url(s)}</code>\n"
        f"  API: <code>{_short_api(_av_api(s))}</code>\n\n"
        "<b>📢 Post Shortner</b> (post-channel links)\n"
        f"  URL: <code>{_post_url(s)}</code>\n"
        f"  API: <code>{_short_api(_post_api(s))}</code>\n\n"
        "<b>📂 Category Shortner</b> (cat-verify links)\n"
        f"  URL: <code>{_cat_url(s)}</code>\n"
        f"  API: <code>{_short_api(_cat_api(s))}</code>\n\n"
        "<b>🎓 Tutorial Link:</b>\n"
        f"  <code>{_av_tut(s)}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Use the buttons below to configure.</i>"
    )


# ── Keyboard ──────────────────────────────────────────────────────────────────

def _shortner_keyboard(
    s: dict, show_back_to_config: bool = False
) -> InlineKeyboardMarkup:
    enabled = s.get("is_enabled", True)
    toggle_lbl = "🔴 Disable Shortner" if enabled else "🟢 Enable Shortner"
    rows = [
        [InlineKeyboardButton(toggle_lbl, callback_data="sht_toggle")],
        [
            InlineKeyboardButton("✏️ Verify URL & API",  callback_data="sht_update_av"),
            InlineKeyboardButton("✏️ Post URL & API",    callback_data="sht_update_post"),
        ],
        [
            InlineKeyboardButton("✏️ Cat URL & API",     callback_data="sht_update_cat"),
            InlineKeyboardButton("🎓 Tutorial Link",     callback_data="sht_tutorial"),
        ],
        [
            InlineKeyboardButton("🧪 Test Verify",       callback_data="sht_test_av"),
            InlineKeyboardButton("🧪 Test Post",         callback_data="sht_test_post"),
        ],
    ]
    if show_back_to_config:
        rows.append(
            [InlineKeyboardButton("◀ Back to Config", callback_data="bcfg_main")]
        )
    return InlineKeyboardMarkup(rows)


def _has_config_back(message) -> bool:
    """True if the message already has a 'Back to Config' button."""
    try:
        for row in message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data == "bcfg_main":
                    return True
    except Exception:
        pass
    return False


def _back_kb(show_back: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("◀ Back", callback_data="sht_back")]]
    if show_back:
        rows.append(
            [InlineKeyboardButton("◀ Back to Config", callback_data="bcfg_main")]
        )
    return InlineKeyboardMarkup(rows)


# ── Listen helper ─────────────────────────────────────────────────────────────

async def _listen(client, chat_id: int, timeout: int = 60):
    """
    Wait for the next non-command text message from the user.
    Messages starting with '/' are excluded so /config or /shortner
    commands are never swallowed by an active listen.
    Returns the Message, or None on timeout/cancel.
    """
    try:
        msg = await client.listen(
            chat_id=chat_id,
            user_id=chat_id,
            timeout=timeout,
        )
        if msg and msg.text and msg.text.startswith("/"):
            return None
        return msg
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None


# ── Generic URL+API update ────────────────────────────────────────────────────

async def _update_url_api(
    client,
    query: CallbackQuery,
    *,
    label: str,
    url_key: str,
    api_key: str,
    cur_url: str,
    cur_api: str,
    temp_url_attr: str,
    temp_api_attr: str,
    show_back: bool,
) -> None:
    prompt = await query.message.edit_text(
        f"<b>✏️ Update {label}</b>\n\n"
        "Send URL and API key in <b>one message</b>:\n"
        "<code>domain.com YOUR_API_KEY</code>\n\n"
        f"Current URL: <code>{cur_url}</code>\n"
        f"Current API: <code>{_short_api(cur_api)}</code>\n\n"
        "<i>Timeout: 60 s. Click Cancel to abort.</i>",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="sht_cancel")]]
        ),
    )

    reply = await _listen(client, query.from_user.id, timeout=60)
    if reply is None:
        await prompt.edit_text(
            "⏰ Timed out. No changes made.",
            reply_markup=_back_kb(show_back),
        )
        return

    text = reply.text.strip()
    await reply.delete()

    parts = text.split()
    if len(parts) < 2:
        await prompt.edit_text(
            "❌ Invalid format. Use: <code>domain.com API_KEY</code>",
            reply_markup=_back_kb(show_back),
        )
        return

    new_url = _strip_url(parts[0])
    new_api = " ".join(parts[1:])

    await db.update_shortner_setting(url_key, new_url)
    await db.update_shortner_setting(api_key, new_api)
    setattr(temp, temp_url_attr, new_url)
    setattr(temp, temp_api_attr, new_api)

    await prompt.edit_text(
        f"✅ <b>{label} updated!</b>\n\n"
        f"URL: <code>{new_url}</code>\n"
        f"API: <code>{_short_api(new_api)}</code>",
        reply_markup=_back_kb(show_back),
    )


# ================================================================
# /shortner command
# ================================================================

@Client.on_message(filters.command("shortner") & filters.private & admin)
async def shortner_cmd(client: Client, message: Message):
    settings = await db.get_shortner_settings()
    temp.SHORTNER_ENABLED = settings.get("is_enabled", True)
    await message.reply(
        await _shortner_panel_text(settings),
        reply_markup=_shortner_keyboard(settings),
    )


# ================================================================
# Toggle on/off
# ================================================================

@Client.on_callback_query(filters.regex(r"^sht_toggle$") & admin)
async def sht_toggle(client: Client, query: CallbackQuery):
    settings = await db.get_shortner_settings()
    new_state = not settings.get("is_enabled", True)
    await db.set_shortner_status(new_state)
    temp.SHORTNER_ENABLED = new_state
    label = "enabled ✅" if new_state else "disabled ❌"
    await query.answer(f"Shortner {label}!", show_alert=False)
    settings["is_enabled"] = new_state
    show_back = _has_config_back(query.message)
    await query.message.edit_text(
        await _shortner_panel_text(settings),
        reply_markup=_shortner_keyboard(settings, show_back_to_config=show_back),
    )


# ================================================================
# Update Verify Shortner
# ================================================================

@Client.on_callback_query(filters.regex(r"^sht_update_av$") & admin)
async def sht_update_av(client: Client, query: CallbackQuery):
    await query.answer()
    settings = await db.get_shortner_settings()
    show_back = _has_config_back(query.message)
    await _update_url_api(
        client, query,
        label="Verify Shortner",
        url_key="short_url",       api_key="short_api",
        cur_url=_av_url(settings), cur_api=_av_api(settings),
        temp_url_attr="SHORTNER_URL", temp_api_attr="SHORTNER_API",
        show_back=show_back,
    )


# ================================================================
# Update Post Shortner
# ================================================================

@Client.on_callback_query(filters.regex(r"^sht_update_post$") & admin)
async def sht_update_post(client: Client, query: CallbackQuery):
    await query.answer()
    settings = await db.get_shortner_settings()
    show_back = _has_config_back(query.message)
    await _update_url_api(
        client, query,
        label="Post Shortner",
        url_key="post_short_url",    api_key="post_short_api",
        cur_url=_post_url(settings), cur_api=_post_api(settings),
        temp_url_attr="POST_SHORT_URL", temp_api_attr="POST_SHORT_API",
        show_back=show_back,
    )


# ================================================================
# Update Category Shortner
# ================================================================

@Client.on_callback_query(filters.regex(r"^sht_update_cat$") & admin)
async def sht_update_cat(client: Client, query: CallbackQuery):
    await query.answer()
    settings = await db.get_shortner_settings()
    show_back = _has_config_back(query.message)
    await _update_url_api(
        client, query,
        label="Category Shortner",
        url_key="cat_short_url",    api_key="cat_short_api",
        cur_url=_cat_url(settings), cur_api=_cat_api(settings),
        temp_url_attr="CAT_SHORT_URL", temp_api_attr="CAT_SHORT_API",
        show_back=show_back,
    )


# ================================================================
# Update Tutorial Link
# ================================================================

@Client.on_callback_query(filters.regex(r"^sht_tutorial$") & admin)
async def sht_tutorial(client: Client, query: CallbackQuery):
    await query.answer()
    settings = await db.get_shortner_settings()
    cur = _av_tut(settings)
    show_back = _has_config_back(query.message)

    prompt = await query.message.edit_text(
        f"<b>🎓 Set Tutorial Link</b>\n\n"
        f"Send the new tutorial URL (must start with https://).\n\n"
        f"Current: <code>{cur}</code>\n\n"
        "<i>Timeout: 60 s. Click Cancel to abort.</i>",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="sht_cancel")]]
        ),
    )

    reply = await _listen(client, query.from_user.id, timeout=60)
    if reply is None:
        await prompt.edit_text("⏰ Timed out. No changes made.", reply_markup=_back_kb(show_back))
        return

    link = reply.text.strip()
    await reply.delete()

    if not link.startswith("http"):
        await prompt.edit_text(
            "❌ Invalid link. Must start with https://",
            reply_markup=_back_kb(show_back),
        )
        return

    await db.update_shortner_setting("tutorial_link", link)
    temp.SHORTNER_TUTORIAL = link
    await prompt.edit_text(
        f"✅ <b>Tutorial link updated!</b>\n\n<code>{link}</code>",
        reply_markup=_back_kb(show_back),
    )


# ================================================================
# Test Shortners
# ================================================================

@Client.on_callback_query(filters.regex(r"^sht_test_av$") & admin)
async def sht_test_av(client: Client, query: CallbackQuery):
    await query.answer("Testing Verify Shortner…", show_alert=False)
    settings = await db.get_shortner_settings()
    show_back = _has_config_back(query.message)
    ok, result = await _test_shortner(_av_url(settings), _av_api(settings))
    text = (
        f"✅ <b>Verify Shortner working!</b>\n\nTest link: <code>{result}</code>"
        if ok else
        f"❌ <b>Verify Shortner failed!</b>\n\nError: <code>{result}</code>"
    )
    await query.message.edit_text(text, reply_markup=_back_kb(show_back))


@Client.on_callback_query(filters.regex(r"^sht_test_post$") & admin)
async def sht_test_post(client: Client, query: CallbackQuery):
    await query.answer("Testing Post Shortner…", show_alert=False)
    settings = await db.get_shortner_settings()
    show_back = _has_config_back(query.message)
    ok, result = await _test_shortner(_post_url(settings), _post_api(settings))
    text = (
        f"✅ <b>Post Shortner working!</b>\n\nTest link: <code>{result}</code>"
        if ok else
        f"❌ <b>Post Shortner failed!</b>\n\nError: <code>{result}</code>"
    )
    await query.message.edit_text(text, reply_markup=_back_kb(show_back))


# ================================================================
# Back / Cancel
# ================================================================

@Client.on_callback_query(filters.regex(r"^sht_back$") & admin)
async def sht_back(client: Client, query: CallbackQuery):
    await query.answer()
    settings = await db.get_shortner_settings()
    show_back = _has_config_back(query.message)
    await query.message.edit_text(
        await _shortner_panel_text(settings),
        reply_markup=_shortner_keyboard(settings, show_back_to_config=show_back),
    )


@Client.on_callback_query(filters.regex(r"^sht_cancel$") & admin)
async def sht_cancel(client: Client, query: CallbackQuery):
    await query.answer("Cancelled.")
    try:
        client.cancel_listener(chat_id=query.from_user.id)
    except Exception:
        pass
    settings = await db.get_shortner_settings()
    show_back = _has_config_back(query.message)
    await query.message.edit_text(
        await _shortner_panel_text(settings),
        reply_markup=_shortner_keyboard(settings, show_back_to_config=show_back),
    )

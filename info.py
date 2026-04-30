import re
from os import environ

# -------------------------
# Helper
# -------------------------
def str_to_bool(val, default=False):
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes", "on")

# =========================================================
# 🤖 BOT BASIC INFORMATION
# =========================================================
API_ID = int(environ.get("API_ID", "23685822"))
API_HASH = environ.get("API_HASH", "ff0572e13ff2f63a50f6dc707e0c4c9f")
BOT_TOKEN = environ.get("BOT_TOKEN", "")
PORT = int(environ.get("PORT", "8080"))
TIMEZONE = environ.get("TIMEZONE", "Asia/Kolkata")
OWNER_USERNAME = environ.get("OWNER_USERNAME", "eren645")

# =========================================================
# 💾 DATABASE CONFIGURATION
# =========================================================
DB_URL = environ.get("DATABASE_URI", "")
DB_NAME = environ.get("DATABASE_NAME", "Cluster0")

# =========================================================
# 📢 CHANNELS & ADMINS
# =========================================================
ADMINS = int(environ.get("ADMINS", "6725874739"))

LOG_CHANNEL = int(environ.get("LOG_CHANNEL", "-1003719289913"))
PREMIUM_LOGS = int(environ.get("PREMIUM_LOGS", "-1003798512506"))
VERIFIED_LOG = int(environ.get("VERIFIED_LOG", "-1003923118233"))

POST_CHANNEL = int(environ.get("POST_CHANNEL", "-1003871870272"))
VIDEO_CHANNEL = int(environ.get("VIDEO_CHANNEL", "-1003828231424"))
BRAZZER_CHANNEL = int(environ.get("BRAZZER_CHANNEL", "-1003782456217"))


# Auth channels list
auth_channel_str = environ.get("AUTH_CHANNEL", "-1001610198839")
AUTH_CHANNEL = [int(x) for x in auth_channel_str.split() if x.strip().lstrip("-").isdigit()]

# =========================================================
# ⚙️ FEATURES & TOGGLES  (FIXED)
# =========================================================
FSUB = str_to_bool(environ.get("FSUB"), True)
IS_VERIFY = str_to_bool(environ.get("IS_VERIFY"), True)
POST_SHORTLINK = str_to_bool(environ.get("POST_SHORTLINK"), True)
SEND_POST = str_to_bool(environ.get("SEND_POST"), False)
PROTECT_CONTENT = str_to_bool(environ.get("PROTECT_CONTENT"), True)

# =========================================================
# 🔢 LIMITS
# =========================================================
DAILY_LIMIT = int(environ.get("DAILY_LIMIT", "15"))
VERIFICATION_DAILY_LIMIT = int(environ.get("VERIFICATION_DAILY_LIMIT", "700"))
PREMIUM_DAILY_LIMIT = int(environ.get("PREMIUM_DAILY_LIMIT", "50050"))
BOOKMARK_LIMIT_FREE = int(environ.get("BOOKMARK_LIMIT_FREE", "5"))
BOOKMARK_LIMIT_PREMIUM =int(environ.get("BOOKMARK_LIMIT_PREMIUM", "15"))
# =========================================================
# 🔗 SHORTLINK & VERIFICATION
# =========================================================
SHORTLINK_URL = environ.get("SHORTLINK_URL", "vplink.in")
SHORTLINK_API = environ.get("SHORTLINK_API", "f9da968c27a8594f2bbc3b2cd1e8778fa756b3a5")
POST_SHORTLINK_URL = environ.get("POST_SHORTLINK_URL", "vplink.in")
POST_SHORTLINK_API = environ.get("POST_SHORTLINK_API", "f9da968c27a8594f2bbc3b2cd1e8778fa756b3a5")
VERIFY_EXPIRE = int(environ.get("VERIFY_EXPIRE", "3600"))
TUTORIAL_LINK = environ.get("TUTORIAL_LINK", "https://t.me/tutorial_filx/7")

# =========================================================
# 💳 PAYMENT SETTINGS
# =========================================================
UPI_ID = environ.get("UPI_ID", "flixhd@ptaxis")
QR_CODE_IMAGE = environ.get("QR_CODE_IMAGE", "https://i.ibb.co/Rk2fXKN3/x.jpg")

# =========================================================
# 🖼️ IMAGES
# =========================================================
START_PIC = environ.get("START_PIC", "https://i.ibb.co/nMfrCRSw/x.jpg")
AUTH_PICS = environ.get("AUTH_PICS", "https://i.ibb.co/rfNnbhV9/x.jpg")
VERIFY_IMG = environ.get("VERIFY_IMG", "https://i.ibb.co/1JbhhN74/x.jpg")
NO_IMG = environ.get("NO_IMG", "https://i.ibb.co/5xc7m3cd/x.jpg")

# =========================================================
# 🌐 WEB APP
# =========================================================
WEB_APP_URL = environ.get("WEB_APP_URL", "https://civilian-harriot-filmyflixhd-12852492.koyeb.app/")

import os
import time
from pyrogram import Client
from info import API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL, PORT, ADMINS, DB_CHANNEL
from aiohttp import web
from route import web_server, ping_server, check_expired_premium, start_scheduler
import pytz
from datetime import date, datetime
from utils import temp
from database.users_db import db
import bot_cfg


class Bot(Client):
    def __init__(self):
        super().__init__(
            name="avbotz",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=200,
            plugins={"root": "plugins"},
            sleep_threshold=15,
            max_concurrent_transmissions=5,
        )

    async def start(self):
        await super().start()
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        temp.B_LINK = me.mention
        temp.START_TIME = time.time()
        self.username = "@" + me.username

        # --- Load all admin panel bot_config overrides from DB ---
        try:
            all_cfg = await db.get_all_bot_config()
            bot_cfg.load(all_cfg)
        except Exception as e:
            print(f"⚠️  Could not load bot config overrides: {e}")

        # --- Load shortner settings from DB into temp ---
        try:
            sht = await db.get_shortner_settings()
            temp.SHORTNER_ENABLED = sht.get("is_enabled", True)
            temp.SHORTNER_URL = sht.get("short_url")      # None = use env var fallback
            temp.SHORTNER_API = sht.get("short_api")      # None = use env var fallback
            temp.SHORTNER_TUTORIAL = sht.get("tutorial_link")
            temp.POST_SHORT_URL = sht.get("post_short_url")
            temp.POST_SHORT_API = sht.get("post_short_api")
            temp.CAT_SHORT_URL = sht.get("cat_short_url")
            temp.CAT_SHORT_API = sht.get("cat_short_api")
        except Exception as e:
            print(f"⚠️  Could not load shortner settings: {e}")

        # --- Set up DB channel for File Store ---
        if DB_CHANNEL:
            try:
                self.db_channel = await self.get_chat(DB_CHANNEL)
                print(f"✅ DB Channel Connected: {self.db_channel.title} [{self.db_channel.id}]")
            except Exception as e:
                print(f"⚠️  Could not connect to DB_CHANNEL ({DB_CHANNEL}): {e}")
                self.db_channel = None
        else:
            self.db_channel = None
            print("⚠️  DB_CHANNEL not set. File Store features disabled.")

        # --- Print loaded plugins ---
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🛠  LOADING PLUGINS...")
        plugin_count = 0
        for root, dirs, files in os.walk("plugins"):
            for file in files:
                if file.endswith(".py") and not file.startswith("__"):
                    print(f"✅ Successfully Loaded: {file}")
                    plugin_count += 1
        print(f"🎉 Total {plugin_count} Plugins Loaded!")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

        tz = pytz.timezone("Asia/Kolkata")
        today = date.today()
        now = datetime.now(tz)
        time_str = now.strftime("%H:%M:%S %p")

        # --- Background tasks ---
        self.loop.create_task(check_expired_premium(self))
        self.loop.create_task(start_scheduler(self))
        self.loop.create_task(ping_server())

        app_instance = await web_server()
        app_runner = web.AppRunner(app_instance)
        await app_runner.setup()
        site = web.TCPSite(app_runner, "0.0.0.0", int(PORT))
        await site.start()

        print(f"{me.first_name} 𝚂𝚃𝙰𝚁𝚃𝙴𝙳 ⚡️⚡️⚡️")

        # Notify admins
        if isinstance(ADMINS, list):
            for admin in ADMINS:
                try:
                    await self.send_message(admin, f"**__{me.first_name} Iꜱ Sᴛᴀʀᴛᴇᴅ.....✨️😅😅😅__**")
                except Exception:
                    pass
        else:
            try:
                await self.send_message(ADMINS, f"**__{me.first_name} Iꜱ Sᴛᴀʀᴛᴇᴅ.....✨️😅😅😅__**")
            except Exception:
                pass

        # Log channel message
        try:
            await self.send_message(
                LOG_CHANNEL,
                text=(
                    f"<b>ʀᴇsᴛᴀʀᴛᴇᴅ 🤖\n\n"
                    f"📆 ᴅᴀᴛᴇ - <code>{today}</code>\n"
                    f"🕙 ᴛɪᴍᴇ - <code>{time_str}</code>\n"
                    f"🌍 ᴛɪᴍᴇ ᴢᴏɴᴇ - <code>Asia/Kolkata</code></b>"
                ),
            )
        except Exception:
            pass

    async def stop(self, *args):
        await super().stop()
        print("Bot Stopped")


if __name__ == "__main__":
    Bot().run()

import pytz
import random
import logging
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from info import DB_URL, DB_NAME, TIMEZONE, VERIFY_EXPIRE

logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(DB_URL)
mydb = client[DB_NAME]


def get_ist_now():
    return datetime.now(pytz.timezone(TIMEZONE))


def get_ist_today():
    return get_ist_now().date()


class Database:
    def __init__(self):
        # ---- Original NaughtyHub collections ----
        self.users = mydb.users
        self.codes = mydb.codes
        self.misc = mydb.misc
        self.videos = mydb.videoz
        self.historys = mydb.historyz
        self.brazzers = mydb.brazzers
        self.verify_id = mydb.verify_id
        self.refer_collection = mydb.referrals
        self.braz_history = mydb.braz_history
        self.blocked_users = mydb.blocked_users

        # ---- File Store collections ----
        self.fs_admins = mydb.fs_admins           # Dynamic admin list
        self.fs_channels = mydb.fs_channels       # Dynamic force-sub channels
        self.fs_req_users = mydb.fs_req_users     # Join-request tracking
        self.fs_del_timer = mydb.fs_del_timer     # Auto-delete timer setting
        self.fs_verify = mydb.fs_verify           # File-store token verification

    # ================================================================
    # USERS
    # ================================================================
    async def add_user(self, id, name):
        if not await self.users.find_one({"id": id}):
            await self.users.insert_one({
                "id": id,
                "name": name,
                "video_count": 0,
                "last_date": None,
                "expiry_time": None,
            })

    async def is_user_exist(self, id):
        return bool(await self.users.find_one({"id": int(id)}))

    async def total_users_count(self):
        return await self.users.count_documents({})

    async def delete_user(self, user_id):
        await self.users.delete_many({"id": int(user_id)})

    async def get_user(self, user_id):
        return await self.users.find_one({"id": user_id})

    async def update_user(self, user_data):
        await self.users.update_one({"id": user_data["id"]}, {"$set": user_data}, upsert=True)

    async def get_all_users(self):
        return self.users.find({})

    # ================================================================
    # COUNTS
    # ================================================================
    async def total_files_count(self):
        return await self.videos.count_documents({})

    async def total_brazzers_videos(self):
        return await self.brazzers.count_documents({})

    async def total_blocked_count(self):
        return await self.blocked_users.count_documents({})

    async def total_redeem_count(self):
        return await self.codes.count_documents({})

    # ================================================================
    # REFERRAL SYSTEM
    # ================================================================
    async def is_user_in_list(self, user_id):
        return bool(await self.refer_collection.find_one({"user_id": int(user_id)}))

    async def get_refer_points(self, user_id: int):
        user = await self.refer_collection.find_one({"user_id": int(user_id)})
        return user.get("points", 0) if user else 0

    async def add_refer_points(self, user_id: int, points: int):
        await self.refer_collection.update_one(
            {"user_id": int(user_id)},
            {"$set": {"points": points}},
            upsert=True,
        )

    async def change_points(self, user_id: int, amount: int):
        current = await self.get_refer_points(user_id)
        new = max(current + amount, 0)
        await self.refer_collection.update_one(
            {"user_id": int(user_id)},
            {"$set": {"points": new}},
            upsert=True,
        )
        return new

    # ================================================================
    # PREMIUM
    # ================================================================
    async def add_premium_access(self, user_id, days):
        user = await self.get_user(user_id)
        now = datetime.now(timezone.utc)
        current_expiry = user.get("expiry_time") if user else None
        if current_expiry and isinstance(current_expiry, datetime):
            if current_expiry.tzinfo is None:
                current_expiry = current_expiry.replace(tzinfo=timezone.utc)
            new_expiry = (current_expiry + timedelta(days=days)
                          if current_expiry > now
                          else now + timedelta(days=days))
        else:
            new_expiry = now + timedelta(days=days)
        await self.users.update_one({"id": user_id}, {"$set": {"expiry_time": new_expiry}})
        return new_expiry

    async def has_premium_access(self, user_id):
        user_data = await self.get_user(user_id)
        if not user_data:
            return False
        expiry_time = user_data.get("expiry_time")
        if not expiry_time:
            return False
        now = datetime.now(timezone.utc)
        if isinstance(expiry_time, datetime):
            if expiry_time.tzinfo is None:
                expiry_time = expiry_time.replace(tzinfo=timezone.utc)
            return now <= expiry_time
        await self.users.update_one({"id": user_id}, {"$set": {"expiry_time": None}})
        return False

    async def remove_premium_access(self, user_id):
        return await self.update_one({"id": user_id}, {"$set": {"expiry_time": None}})

    async def premium_users_count(self):
        return await self.users.count_documents({
            "expiry_time": {"$gt": datetime.now(timezone.utc)}
        })

    async def get_expired(self, current_time):
        expired = []
        async for user in self.users.find({"expiry_time": {"$lt": current_time}}):
            expired.append(user)
        return expired

    async def get_expiring_soon(self, label, delta):
        reminder_key = f"reminder_{label}_sent"
        now = datetime.now(timezone.utc)
        target = now + delta
        window = timedelta(seconds=30)
        result = []
        cursor = self.users.find({
            "expiry_time": {"$gte": target - window, "$lte": target + window},
            reminder_key: {"$ne": True},
        })
        async for user in cursor:
            result.append(user)
            await self.users.update_one({"id": user["id"]}, {"$set": {reminder_key: True}})
        return result

    async def update_one(self, filter_query, update_data):
        try:
            result = await self.users.update_one(filter_query, update_data)
            return result.matched_count == 1
        except Exception as e:
            print(f"update_one error: {e}")
            return False

    # ================================================================
    # BLOCK SYSTEM
    # ================================================================
    async def is_user_blocked(self, user_id):
        return bool(await self.blocked_users.find_one({"user_id": user_id}))

    async def block_user(self, user_id, reason="Spam"):
        await self.blocked_users.update_one(
            {"user_id": user_id},
            {"$set": {"blocked_at": datetime.now(timezone.utc), "reason": reason}},
            upsert=True,
        )

    async def unblock_user(self, user_id: int):
        await self.blocked_users.delete_one({"user_id": user_id})

    async def get_all_blocked_users(self):
        return self.blocked_users.find({})

    async def add_temp_ban(self, user_id, duration_seconds):
        expiry = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        await self.users.update_one({"id": user_id}, {"$set": {"temp_ban_expiry": expiry}})

    async def is_temp_banned(self, user_id):
        user = await self.users.find_one({"id": user_id})
        if not user or "temp_ban_expiry" not in user:
            return False, 0
        expiry = user["temp_ban_expiry"]
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now < expiry:
            return True, int((expiry - now).total_seconds())
        await self.users.update_one({"id": user_id}, {"$unset": {"temp_ban_expiry": ""}})
        return False, 0

    # ================================================================
    # VIDEOS SYSTEM
    # ================================================================
    async def add_video(self, file_unique_id, file_id):
        if not await self.videos.find_one({"file_unique_id": file_unique_id}):
            await self.videos.insert_one({
                "file_unique_id": file_unique_id,
                "file_id": file_id,
                "added_at": datetime.now(timezone.utc),
            })
            return True
        return False

    async def total_videos(self):
        return await self.videos.count_documents({})

    async def delete_main_data(self):
        await self.videos.delete_many({})
        await self.historys.delete_many({})
        return True

    async def delete_brazzers_data(self):
        await self.brazzers.delete_many({})
        await self.braz_history.delete_many({})
        return True

    async def increase_video_count(self, user_id, username):
        today = get_ist_today()
        today_dt = datetime.combine(today, datetime.min.time())
        user = await self.users.find_one({"id": user_id})
        if user:
            last_date = user.get("last_date")
            if isinstance(last_date, datetime):
                if last_date.tzinfo is not None:
                    check_date = last_date.astimezone(pytz.timezone(TIMEZONE)).date()
                else:
                    check_date = last_date.date()
            else:
                check_date = None
            if check_date != today:
                await self.users.update_one(
                    {"id": user_id},
                    {"$set": {"video_count": 1, "last_date": today_dt, "username": username}},
                )
            else:
                await self.users.update_one(
                    {"id": user_id},
                    {"$inc": {"video_count": 1}, "$set": {"username": username}},
                )
        else:
            await self.users.insert_one({
                "id": user_id,
                "name": username,
                "video_count": 1,
                "last_date": today_dt,
                "expiry_time": None,
            })

    async def get_video_count(self, user_id: int):
        today = get_ist_today()
        user = await self.users.find_one({"id": user_id})
        if user:
            last_date = user.get("last_date")
            if isinstance(last_date, datetime):
                if last_date.tzinfo is not None:
                    check_date = last_date.astimezone(pytz.timezone(TIMEZONE)).date()
                else:
                    check_date = last_date.date()
                if check_date == today:
                    return user.get("video_count", 0)
        return 0

    async def get_unseen_video(self, user_id):
        seen = await self.historys.find_one({"user_id": user_id})
        seen_ids = seen.get("seen", []) if seen else []
        cursor = self.videos.find({"file_id": {"$nin": seen_ids}}, {"file_id": 1}).limit(500)
        unseen = await cursor.to_list(length=500)
        if not unseen:
            return None
        video = random.choice(unseen)
        await self.mark_seen(user_id, video["file_id"])
        return video["file_id"]

    async def get_random_video(self):
        try:
            cursor = self.videos.aggregate([{"$sample": {"size": 1}}])
            result = await cursor.to_list(length=1)
            if result:
                return result[0]["file_id"]
        except Exception as e:
            print(f"get_random_video error: {e}")
        return None

    async def mark_seen(self, user_id, file_id):
        await self.historys.update_one(
            {"user_id": user_id},
            {"$addToSet": {"seen": file_id}},
            upsert=True,
        )

    async def reset_seen_videos(self, user_id: int):
        await self.historys.update_one(
            {"user_id": user_id}, {"$set": {"seen": []}}, upsert=True
        )

    async def add_brazzers_video(self, file_unique_id, file_id):
        if not await self.brazzers.find_one({"file_unique_id": file_unique_id}):
            await self.brazzers.insert_one({
                "file_unique_id": file_unique_id,
                "file_id": file_id,
            })
            return True
        return False

    async def get_unseen_brazzers(self, user_id):
        seen = await self.braz_history.find_one({"user_id": user_id})
        seen_ids = seen.get("seen", []) if seen else []
        cursor = self.brazzers.find({"file_id": {"$nin": seen_ids}})
        unseen = await cursor.to_list(length=1000)
        if not unseen:
            return None
        video = random.choice(unseen)
        await self.mark_brazzers_seen(user_id, video["file_id"])
        return video["file_id"]

    async def mark_brazzers_seen(self, user_id, file_id):
        await self.braz_history.update_one(
            {"user_id": user_id},
            {"$addToSet": {"seen": file_id}},
            upsert=True,
        )

    async def reset_seen_brazzers(self, user_id: int):
        await self.braz_history.update_one(
            {"user_id": user_id}, {"$set": {"seen": []}}, upsert=True
        )

    # ================================================================
    # VERIFICATION SYSTEM (Original)
    # ================================================================
    async def get_notcopy_user(self, user_id):
        user_id = int(user_id)
        user = await self.misc.find_one({"user_id": user_id})
        default_date = datetime(2020, 5, 17, 0, 0, 0, tzinfo=timezone.utc)
        if not user:
            res = {"user_id": user_id, "last_verified": default_date}
            await self.misc.insert_one(res)
            return res
        return user

    async def update_notcopy_user(self, user_id, value: dict):
        return await self.misc.update_one({"user_id": int(user_id)}, {"$set": value})

    async def is_user_verified(self, user_id):
        user = await self.get_notcopy_user(user_id)
        pastDate = user.get("last_verified") or datetime(2020, 5, 17, 0, 0, 0, tzinfo=timezone.utc)
        if pastDate.tzinfo is None:
            pastDate = pastDate.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - pastDate) < timedelta(seconds=VERIFY_EXPIRE)

    async def create_verify_id(self, user_id: int, hash, file_id=None):
        res = {"user_id": user_id, "hash": hash, "verified": False, "file_id": file_id}
        return await self.verify_id.insert_one(res)

    async def get_verify_id_info(self, user_id: int, hash):
        return await self.verify_id.find_one({"user_id": user_id, "hash": hash})

    async def update_verify_id_info(self, user_id, hash, value: dict):
        return await self.verify_id.update_one(
            {"user_id": user_id, "hash": hash}, {"$set": value}
        )

    async def get_verification_stats(self):
        midnight_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.misc.count_documents({"last_verified": {"$gte": midnight_utc}})

    async def get_db_size(self):
        stats = await mydb.command("dbstats")
        return stats.get("dataSize", 0)

    # ================================================================
    # FILE STORE — DYNAMIC ADMIN MANAGEMENT
    # ================================================================
    async def fs_admin_exist(self, admin_id: int):
        return bool(await self.fs_admins.find_one({"_id": admin_id}))

    async def fs_add_admin(self, admin_id: int):
        if not await self.fs_admin_exist(admin_id):
            await self.fs_admins.insert_one({"_id": admin_id})

    async def fs_del_admin(self, admin_id: int):
        if await self.fs_admin_exist(admin_id):
            await self.fs_admins.delete_one({"_id": admin_id})

    async def fs_get_all_admins(self):
        docs = await self.fs_admins.find().to_list(length=None)
        return [doc["_id"] for doc in docs]

    # ================================================================
    # FILE STORE — DYNAMIC FORCE-SUB CHANNEL MANAGEMENT
    # ================================================================
    async def fs_channel_exist(self, channel_id: int):
        return bool(await self.fs_channels.find_one({"_id": channel_id}))

    async def fs_add_channel(self, channel_id: int, mode: str = "off"):
        if not await self.fs_channel_exist(channel_id):
            await self.fs_channels.insert_one({"_id": channel_id, "mode": mode})

    async def fs_rem_channel(self, channel_id: int):
        if await self.fs_channel_exist(channel_id):
            await self.fs_channels.delete_one({"_id": channel_id})

    async def fs_show_channels(self):
        docs = await self.fs_channels.find().to_list(length=None)
        return [doc["_id"] for doc in docs]

    async def fs_get_channel_mode(self, channel_id: int):
        data = await self.fs_channels.find_one({"_id": channel_id})
        return data.get("mode", "off") if data else "off"

    async def fs_set_channel_mode(self, channel_id: int, mode: str):
        await self.fs_channels.update_one(
            {"_id": channel_id}, {"$set": {"mode": mode}}, upsert=True
        )

    # ================================================================
    # FILE STORE — JOIN REQUEST TRACKING
    # ================================================================
    async def fs_req_user(self, channel_id: int, user_id: int):
        try:
            await self.fs_req_users.update_one(
                {"_id": int(channel_id)},
                {"$addToSet": {"user_ids": int(user_id)}},
                upsert=True,
            )
        except Exception as e:
            print(f"[fs_req_user error] {e}")

    async def fs_del_req_user(self, channel_id: int, user_id: int):
        await self.fs_req_users.update_one(
            {"_id": channel_id}, {"$pull": {"user_ids": user_id}}
        )

    async def fs_req_user_exist(self, channel_id: int, user_id: int):
        try:
            found = await self.fs_req_users.find_one({
                "_id": int(channel_id),
                "user_ids": int(user_id),
            })
            return bool(found)
        except Exception as e:
            print(f"[fs_req_user_exist error] {e}")
            return False

    async def fs_clear_req_users(self, channel_id: int):
        await self.fs_req_users.update_one({"_id": channel_id}, {"$set": {"user_ids": []}})

    # ================================================================
    # FILE STORE — AUTO-DELETE TIMER
    # ================================================================
    async def fs_set_del_timer(self, value: int):
        existing = await self.fs_del_timer.find_one({})
        if existing:
            await self.fs_del_timer.update_one({}, {"$set": {"value": value}})
        else:
            await self.fs_del_timer.insert_one({"value": value})

    async def fs_get_del_timer(self):
        data = await self.fs_del_timer.find_one({})
        return data.get("value", 600) if data else 600

    # ================================================================
    # FILE STORE — TOKEN VERIFICATION
    # ================================================================
    _default_verify = {"is_verified": False, "verified_time": 0, "verify_token": "", "link": ""}

    async def fs_get_verify_status(self, user_id: int):
        user = await self.fs_verify.find_one({"_id": user_id})
        if user:
            return user.get("verify_status", self._default_verify)
        return dict(self._default_verify)

    async def fs_update_verify_status(
        self, user_id: int, verify_token="", is_verified=False, verified_time=0, link=""
    ):
        current = await self.fs_get_verify_status(user_id)
        current["verify_token"] = verify_token
        current["is_verified"] = is_verified
        current["verified_time"] = verified_time
        current["link"] = link
        await self.fs_verify.update_one(
            {"_id": user_id},
            {"$set": {"verify_status": current}},
            upsert=True,
        )


db = Database()

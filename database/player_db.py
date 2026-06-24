"""
Player-side database helpers.

This module is **additive**: it does NOT modify your existing
`database/users_db.py`. It reuses the same MongoDB connection and adds
new collections for video metadata that the rich player needs:

  - videoz            (existing) — adds `category` and `video_number` fields lazily
  - video_reactions   (new)      — per-user like/dislike per video
  - bookmarks         (new)      — per-user bookmarks
  - counters          (new)      — autoincrement source for `video_number`
  - category_channels (new)      — admin-managed category ↔ channel mapping (DB-backed)
"""

import os
import random
from datetime import datetime, timezone

from pymongo import ReturnDocument

from database.users_db import mydb


# ---- collections ----
videos_col = mydb.videoz
historys_col = mydb.historyz
reactions_col = mydb.video_reactions
bookmarks_col = mydb.bookmarks
counters_col = mydb.counters
cat_channels_col = mydb.category_channels   # NEW: DB-backed category channel map


# ---- categories (env-var fallback, kept for backward compat) ----
def _categories_from_env() -> list:
    raw = os.environ.get("CATEGORIES", "")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _categories_from_channels_env() -> list:
    """
    Pulls category names out of the legacy CATEGORY_CHANNELS env var.
    Format:  "Desi:-1001234 Videsi:-1005678"
    Kept as a fallback; DB-backed channels take precedence at runtime.
    """
    raw = os.environ.get("CATEGORY_CHANNELS", "").replace(",", " ")
    names = []
    for entry in raw.split():
        if ":" not in entry:
            continue
        name, _ = entry.rsplit(":", 1)
        name = name.strip()
        if name:
            names.append(name)
    return names


def get_categories() -> list:
    """
    Sync helper — returns category names from env vars only.
    Used as a fallback where async is not available.
    For the full list (including DB channels) use PlayerDB.get_categories_merged().
    """
    seen = set()
    result = []
    for c in _categories_from_env() + _categories_from_channels_env():
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result


ALL_VIDEOS_LABEL = "All Videos"


# ---- bookmark caps (env-configurable) ----
def bookmark_limit_free() -> int:
    try:
        return int(os.environ.get("BOOKMARK_LIMIT_FREE", "5"))
    except ValueError:
        return 5


def bookmark_limit_premium() -> int:
    try:
        return int(os.environ.get("BOOKMARK_LIMIT_PREMIUM", "15"))
    except ValueError:
        return 15


class PlayerDB:
    # ---------- indexes (idempotent) ----------
    async def ensure_indexes(self):
        try:
            await reactions_col.create_index(
                [("file_id", 1), ("user_id", 1)], unique=True
            )
            await bookmarks_col.create_index(
                [("user_id", 1), ("file_id", 1)], unique=True
            )
            await videos_col.create_index([("category", 1)])
            await videos_col.create_index([("video_number", 1)])
            await cat_channels_col.create_index([("channel_id", 1)], unique=True)
            await cat_channels_col.create_index([("name", 1)])
        except Exception:
            pass

    # ---------- video number ----------
    async def ensure_video_number(self, file_id) -> int:
        """Returns the stable numeric ID for a video, assigning one if missing."""
        v = await videos_col.find_one({"file_id": file_id}, {"video_number": 1})
        if v and v.get("video_number"):
            return int(v["video_number"])
        doc = await counters_col.find_one_and_update(
            {"_id": "video_number"},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        n = int(doc.get("value", 1))
        await videos_col.update_one(
            {"file_id": file_id}, {"$set": {"video_number": n}}
        )
        return n

    async def get_file_id_by_number(self, n: int):
        """Reverse lookup — file_id from a numeric Video ID. None if missing."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            return None
        v = await videos_col.find_one({"video_number": n}, {"file_id": 1})
        return v.get("file_id") if v else None

    # ---------- category ----------
    async def get_category(self, file_id):
        v = await videos_col.find_one({"file_id": file_id}, {"category": 1})
        return v.get("category") if v else None

    async def set_category(self, file_id, category):
        result = await videos_col.update_one(
            {"file_id": file_id}, {"$set": {"category": category}}
        )
        return result.modified_count

    async def set_category_by_unique_id(self, file_unique_id, category):
        result = await videos_col.update_one(
            {"file_unique_id": file_unique_id}, {"$set": {"category": category}}
        )
        return result.modified_count

    # ---------- category channel management (DB-backed) ----------

    async def add_cat_channel(self, name: str, channel_id: int) -> bool:
        """
        Add or update a category channel.
        Returns True if newly inserted, False if it already existed (updated).
        """
        existing = await cat_channels_col.find_one({"channel_id": channel_id})
        if existing:
            await cat_channels_col.update_one(
                {"channel_id": channel_id}, {"$set": {"name": name}}
            )
            return False
        await cat_channels_col.insert_one({
            "name": name,
            "channel_id": channel_id,
            "added_at": datetime.now(timezone.utc),
        })
        return True

    async def get_cat_channels(self) -> list:
        """Returns list of {name, channel_id} dicts from the DB."""
        cursor = cat_channels_col.find(
            {}, {"_id": 0, "name": 1, "channel_id": 1}
        ).sort("name", 1)
        return await cursor.to_list(length=200)

    async def get_cat_channel_by_name(self, name: str) -> dict | None:
        return await cat_channels_col.find_one({"name": name}, {"_id": 0})

    async def get_cat_channel_by_id(self, channel_id: int) -> dict | None:
        return await cat_channels_col.find_one({"channel_id": channel_id}, {"_id": 0})

    async def remove_cat_channel(self, name: str) -> bool:
        """Remove a category channel by name. Returns True if deleted."""
        result = await cat_channels_col.delete_one({"name": name})
        return result.deleted_count > 0

    async def rename_cat_channel(self, old_name: str, new_name: str) -> int:
        """
        Rename a category channel:
          1. Updates the channel record in category_channels collection.
          2. Re-tags every video that was tagged with old_name → new_name.
        Returns the number of videos re-tagged.
        """
        await cat_channels_col.update_many(
            {"name": old_name}, {"$set": {"name": new_name}}
        )
        result = await videos_col.update_many(
            {"category": old_name}, {"$set": {"category": new_name}}
        )
        return result.modified_count

    async def get_categories_from_db(self) -> list:
        """Returns unique category names from the DB-backed category_channels collection."""
        cursor = cat_channels_col.find({}, {"_id": 0, "name": 1}).sort("name", 1)
        docs = await cursor.to_list(length=200)
        return [d["name"] for d in docs if d.get("name")]

    async def get_categories_merged(self) -> list:
        """
        Returns all category names — DB channels first, then env-var fallbacks.
        Deduplicates so no name appears twice.
        Use this in async contexts (e.g. the player category picker).
        """
        seen = set()
        result = []
        db_names = await self.get_categories_from_db()
        env_names = get_categories()
        for name in db_names + env_names:
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result

    # ---------- reactions ----------
    async def get_reaction_stats(self, file_id) -> dict:
        likes = await reactions_col.count_documents(
            {"file_id": file_id, "reaction": "like"}
        )
        dislikes = await reactions_col.count_documents(
            {"file_id": file_id, "reaction": "dislike"}
        )
        total = likes + dislikes
        percent = int(round(100 * likes / total)) if total else 0
        return {
            "likes": likes,
            "dislikes": dislikes,
            "total": total,
            "percent": percent,
        }

    async def get_user_reaction(self, user_id, file_id):
        r = await reactions_col.find_one(
            {"user_id": user_id, "file_id": file_id}
        )
        return r.get("reaction") if r else None

    async def set_user_reaction(self, user_id, file_id, reaction):
        """
        reaction: 'like' or 'dislike'. Toggles off if the user clicks the same
        reaction twice. Returns the new reaction (or None if cleared).
        """
        current = await self.get_user_reaction(user_id, file_id)
        if current == reaction:
            await reactions_col.delete_one(
                {"user_id": user_id, "file_id": file_id}
            )
            return None
        await reactions_col.update_one(
            {"user_id": user_id, "file_id": file_id},
            {"$set": {
                "reaction": reaction,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return reaction

    # ---------- bookmarks ----------
    async def is_bookmarked(self, user_id, file_id) -> bool:
        return bool(
            await bookmarks_col.find_one(
                {"user_id": user_id, "file_id": file_id}
            )
        )

    async def count_bookmarks(self, user_id) -> int:
        return await bookmarks_col.count_documents({"user_id": user_id})

    async def try_toggle_bookmark(
        self, user_id, file_id, max_count: int
    ) -> str:
        """
        Atomic-ish bookmark toggle with a per-user cap.

        Returns one of:
          - "added"           — newly bookmarked
          - "removed"         — was bookmarked, now removed
          - "limit_reached"   — at cap, refused to add
        """
        existing = await bookmarks_col.find_one(
            {"user_id": user_id, "file_id": file_id}
        )
        if existing:
            await bookmarks_col.delete_one({"_id": existing["_id"]})
            return "removed"

        current = await bookmarks_col.count_documents({"user_id": user_id})
        if current >= max_count:
            return "limit_reached"

        try:
            await bookmarks_col.insert_one({
                "user_id": user_id,
                "file_id": file_id,
                "added_at": datetime.now(timezone.utc),
            })
        except Exception:
            pass
        return "added"

    async def toggle_bookmark(self, user_id, file_id) -> bool:
        """
        Legacy uncapped toggle. Kept for back-compat; new code should use
        try_toggle_bookmark with an explicit cap.
        """
        existing = await bookmarks_col.find_one(
            {"user_id": user_id, "file_id": file_id}
        )
        if existing:
            await bookmarks_col.delete_one({"_id": existing["_id"]})
            return False
        await bookmarks_col.insert_one({
            "user_id": user_id,
            "file_id": file_id,
            "added_at": datetime.now(timezone.utc),
        })
        return True

    async def list_bookmarks(self, user_id, limit: int = 50):
        cursor = bookmarks_col.find({"user_id": user_id}).sort("added_at", -1)
        docs = await cursor.to_list(length=limit)
        return [b["file_id"] for b in docs]

    # ---------- video selection (with category filter) ----------
    async def get_unseen_video(self, user_id, category=None):
        seen_doc = await historys_col.find_one({"user_id": user_id})
        seen_ids = seen_doc.get("seen", []) if seen_doc else []

        base_query = {}
        if category:
            base_query["category"] = category

        total = await videos_col.count_documents(base_query)
        if total == 0:
            return None

        if len(seen_ids) >= max(1, int(total * 0.8)):
            await historys_col.delete_one({"user_id": user_id})
            seen_ids = []

        unseen_query = dict(base_query)
        if seen_ids:
            unseen_query["file_id"] = {"$nin": seen_ids}

        unseen_count = await videos_col.count_documents(unseen_query)

        if unseen_count == 0:
            unseen_query = base_query
            unseen_count = total

        skip = random.randint(0, unseen_count - 1)
        cursor = videos_col.find(unseen_query, {"file_id": 1}).skip(skip).limit(1)
        results = await cursor.to_list(length=1)

        if not results:
            cursor = videos_col.find(unseen_query, {"file_id": 1}).limit(1)
            results = await cursor.to_list(length=1)

        if not results:
            return None

        file_id = results[0]["file_id"]
        await historys_col.update_one(
            {"user_id": user_id},
            {"$addToSet": {"seen": file_id}},
            upsert=True,
        )
        return file_id

    async def get_random_video(self, category=None):
        try:
            pipeline = []
            if category:
                pipeline.append({"$match": {"category": category}})
            pipeline.append({"$sample": {"size": 1}})
            cursor = videos_col.aggregate(pipeline)
            res = await cursor.to_list(length=1)
            return res[0]["file_id"] if res else None
        except Exception:
            return None

    async def find_by_unique_id(self, file_unique_id):
        return await videos_col.find_one({"file_unique_id": file_unique_id})


player_db = PlayerDB()

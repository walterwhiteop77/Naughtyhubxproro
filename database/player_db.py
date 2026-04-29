"""
Player-side database helpers.

This module is **additive**: it does NOT modify your existing
`database/users_db.py`. It reuses the same MongoDB connection and adds
new collections for video metadata that the rich player needs:

  - videoz          (existing) — adds `category` and `video_number` fields lazily
  - video_reactions (new)      — per-user like/dislike per video
  - bookmarks       (new)      — per-user bookmarks
  - counters        (new)      — autoincrement source for `video_number`
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


# ---- categories (configured via env var) ----
def get_categories() -> list:
    """Returns the configured category names (excluding the 'All Videos' pseudo-cat)."""
    raw = os.environ.get("CATEGORIES", "Desi,Videsi,Leaked,Snaps")
    return [c.strip() for c in raw.split(",") if c.strip()]


ALL_VIDEOS_LABEL = "All Videos"


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

    async def toggle_bookmark(self, user_id, file_id) -> bool:
        """Returns True if it is now bookmarked, False if it was removed."""
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
        return [b["file_id"] async for b in cursor.to_list(length=limit)]

    # ---------- video selection (with category filter) ----------
    async def get_unseen_video(self, user_id, category=None):
        seen_doc = await historys_col.find_one({"user_id": user_id})
        seen_ids = seen_doc.get("seen", []) if seen_doc else []

        query = {"file_id": {"$nin": seen_ids}}
        if category:
            query["category"] = category

        cursor = videos_col.find(query, {"file_id": 1}).limit(500)
        results = await cursor.to_list(length=500)
        if not results:
            return None
        v = random.choice(results)
        await historys_col.update_one(
            {"user_id": user_id},
            {"$addToSet": {"seen": v["file_id"]}},
            upsert=True,
        )
        return v["file_id"]

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

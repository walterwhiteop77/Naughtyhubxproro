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
def _categories_from_env() -> list:
    raw = os.environ.get("CATEGORIES", "Desi,Videsi,Leaked,Snaps")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _categories_from_channels() -> list:
    """
    Pulls the category names out of the CATEGORY_CHANNELS mapping so users
    only have to configure the channel mapping; the picker stays in sync
    automatically.

    Format:  "Desi:-1001234 Videsi:-1005678 Leaked:-1009999"
    (Entries can be space- or comma-separated.)
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
    Returns the configured category names (excluding the 'All Videos'
    pseudo-cat). Merges CATEGORIES + CATEGORY_CHANNELS so that any
    category mapped to a channel automatically shows up in the player's
    'Change Category' picker — no need to keep two env vars in sync.
    """
    seen = set()
    result = []
    for c in _categories_from_env() + _categories_from_channels():
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
            # likely a duplicate-key race — treat as already added
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

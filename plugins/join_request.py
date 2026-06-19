from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest, ChatMemberUpdated
from pyrogram.enums import ChatMemberStatus
from database.users_db import db
from info import AUTH_CHANNEL


_ACTIVE_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}


async def _monitored_channels():
    env_channels = set(AUTH_CHANNEL)
    db_channels = set(await db.fs_show_channels())
    return env_channels | db_channels


# ================================================================
# Join Request — track users who request to join FSUB channels
# ================================================================
@Client.on_chat_join_request(filters.channel)
async def handle_join_request(client: Client, join_request: ChatJoinRequest):
    channel_id = join_request.chat.id
    user_id = join_request.from_user.id

    monitored = await _monitored_channels()
    if channel_id not in monitored:
        return

    try:
        await db.fs_req_user(channel_id, user_id)
    except Exception as e:
        print(f"[join_request] fs_req_user error: {e}")


# ================================================================
# Member updated — remove tracking when user joins/leaves/banned
# ================================================================
@Client.on_chat_member_updated(filters.channel)
async def handle_member_update(client: Client, update: ChatMemberUpdated):
    channel_id = update.chat.id
    if not update.from_user:
        return
    user_id = update.from_user.id

    monitored = await _monitored_channels()
    if channel_id not in monitored:
        return

    old_member = update.old_chat_member
    new_member = update.new_chat_member

    old_status = old_member.status if old_member else None
    new_status = new_member.status if new_member else None

    try:
        if new_status in _ACTIVE_STATUSES:
            # User joined / was approved — remove join-request record
            await db.fs_del_req_user(channel_id, user_id)

        elif old_status in _ACTIVE_STATUSES and new_status not in _ACTIVE_STATUSES:
            # User left, was kicked or banned — nothing to clean for req tracking
            # but ensure they are not still in pending list
            await db.fs_del_req_user(channel_id, user_id)

    except Exception as e:
        print(f"[join_request] member_update error user={user_id} ch={channel_id}: {e}")

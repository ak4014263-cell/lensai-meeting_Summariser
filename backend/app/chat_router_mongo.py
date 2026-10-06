"""
MongoDB-based Chat API endpoints - much simpler, no connection pool issues!
"""
from datetime import datetime
from typing import List, Optional
from pathlib import Path
import aiofiles
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from bson import ObjectId

from .auth.router import get_current_user
from .models import User
from .mongo_db import get_mongo_db
from .chat_websocket import ws_manager
from .config import settings

router = APIRouter(prefix="/api/chat", tags=["chat"])


# Helper to convert ObjectId to string
def serialize_doc(doc):
    if doc and "_id" in doc:
        doc["id"] = str(doc["_id"])
        del doc["_id"]
    return doc


# ============================================================================
# Pydantic Schemas
# ============================================================================

class ChannelCreate(BaseModel):
    name: str
    description: Optional[str] = None
    type: str = "public"  # public, private, dm


class MessageCreate(BaseModel):
    content: str
    parent_message_id: Optional[str] = None


class ReactionCreate(BaseModel):
    emoji: str


# ============================================================================
# Channel Endpoints
# ============================================================================

@router.get("/channels")
async def list_channels(
    current_user: User = Depends(get_current_user)
):
    """List all channels the user is a member of, plus all public channels"""
    db = get_mongo_db()
    
    channels = await db.channels.find({
        "$or": [
            {"type": "public"},
            {"members.user_id": current_user.id}
        ],
        "is_archived": False
    }).sort("created_at", 1).to_list(100)
    
    # Add unread counts
    result = []
    for channel in channels:
        channel = serialize_doc(channel)
        
        # Get member's last_read_at
        member = next((m for m in channel.get("members", []) if m["user_id"] == current_user.id), None)
        last_read = member.get("last_read_at") if member else None
        
        # Count unread
        unread_filter = {"channel_id": channel["id"], "deleted_at": None}
        if last_read:
            unread_filter["created_at"] = {"$gt": last_read}
        
        unread_count = await db.messages.count_documents(unread_filter)
        channel["unread_count"] = unread_count
        
        # Get last message
        last_msg = await db.messages.find_one(
            {"channel_id": channel["id"], "deleted_at": None},
            sort=[("created_at", -1)]
        )
        if last_msg:
            channel["last_message"] = {
                "id": str(last_msg["_id"]),
                "content": last_msg["content"][:100],
                "user_id": last_msg["user_id"],
                "created_at": last_msg["created_at"].isoformat()
            }
        
        result.append(channel)
    
    return result


@router.post("/channels")
async def create_channel(
    channel_data: ChannelCreate,
    current_user: User = Depends(get_current_user)
):
    """Create a new channel or return existing public channel if already exists"""
    db = get_mongo_db()
    
    clean_name = channel_data.name.strip()
    
    # If public, check if channel with this name already exists
    if channel_data.type == "public":
        existing = await db.channels.find_one({
            "name": {"$regex": f"^{clean_name}$", "$options": "i"},
            "type": "public",
            "is_archived": False
        })
        if existing:
            # Ensure current user is a member
            if not any(m.get("user_id") == current_user.id for m in existing.get("members", [])):
                await db.channels.update_one(
                    {"_id": existing["_id"]},
                    {"$push": {"members": {
                        "user_id": current_user.id,
                        "role": "member",
                        "joined_at": datetime.utcnow(),
                        "last_read_at": None
                    }}}
                )
            return serialize_doc(existing)
    
    channel_doc = {
        "name": clean_name,
        "description": channel_data.description,
        "type": channel_data.type,
        "created_by": current_user.id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "is_archived": False,
        "members": [
            {
                "user_id": current_user.id,
                "role": "admin",
                "joined_at": datetime.utcnow(),
                "last_read_at": None
            }
        ]
    }
    
    result = await db.channels.insert_one(channel_doc)
    channel_doc["id"] = str(result.inserted_id)
    del channel_doc["_id"]
    
    if channel_data.type == "public":
        await ws_manager.broadcast_all("channel_created", {
            "channel_id": channel_doc["id"],
            "name": channel_doc["name"]
        })
    else:
        await ws_manager.broadcast_to_user(current_user.id, "channel_created", {
            "channel_id": channel_doc["id"],
            "name": channel_doc["name"]
        })
    
    return channel_doc


@router.post("/channels/{channel_id}/join")
async def join_channel(
    channel_id: str,
    current_user: User = Depends(get_current_user)
):
    """Join a public channel"""
    db = get_mongo_db()
    
    channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    if channel["type"] == "private":
        raise HTTPException(status_code=403, detail="Cannot join private channel")
    
    # Check if already a member
    if any(m["user_id"] == current_user.id for m in channel.get("members", [])):
        return {"message": "Already a member"}
    
    # Add member
    await db.channels.update_one(
        {"_id": ObjectId(channel_id)},
        {"$push": {"members": {
            "user_id": current_user.id,
            "role": "member",
            "joined_at": datetime.utcnow(),
            "last_read_at": None
        }}}
    )
    
    await ws_manager.broadcast_to_channel(channel_id, "user_joined", {
        "channel_id": channel_id,
        "user_id": current_user.id
    })
    
    return {"message": "Joined successfully"}


@router.post("/channels/{channel_id}/mark_read")
async def mark_channel_read(
    channel_id: str,
    current_user: User = Depends(get_current_user)
):
    """Mark all messages as read"""
    db = get_mongo_db()
    
    await db.channels.update_one(
        {"_id": ObjectId(channel_id), "members.user_id": current_user.id},
        {"$set": {"members.$.last_read_at": datetime.utcnow()}}
    )
    
    return {"message": "Marked as read"}


# ============================================================================
# Message Endpoints
# ============================================================================

@router.get("/channels/{channel_id}/messages")
async def list_messages(
    channel_id: str,
    limit: int = 50,
    before: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """List messages in a channel"""
    db = get_mongo_db()
    
    # Check channel exists
    channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Check membership or auto-join if public
    is_member = any(m.get("user_id") == current_user.id for m in channel.get("members", []))
    if not is_member:
        if channel.get("type") == "public":
            # Auto-add user to public channel members
            await db.channels.update_one(
                {"_id": ObjectId(channel_id)},
                {"$push": {"members": {
                    "user_id": current_user.id,
                    "role": "member",
                    "joined_at": datetime.utcnow(),
                    "last_read_at": datetime.utcnow()
                }}}
            )
        else:
            raise HTTPException(status_code=403, detail="Not a member")
    
    # Build query
    query = {
        "channel_id": channel_id,
        "deleted_at": None,
        "parent_message_id": None
    }
    if before:
        query["_id"] = {"$lt": ObjectId(before)}
    
    messages = await db.messages.find(query).sort("created_at", -1).limit(limit).to_list(limit)
    messages.reverse()  # Return chronological order
    
    # Get reactions and format
    result = []
    for msg in messages:
        msg = serialize_doc(msg)
        
        # Get reactions
        reactions = await db.reactions.find({"message_id": msg["id"]}).to_list(100)
        msg["reactions"] = [
            {"id": str(r["_id"]), "emoji": r["emoji"], "user_id": r["user_id"]}
            for r in reactions
        ]
        
        # Count replies
        reply_count = await db.messages.count_documents({
            "parent_message_id": msg["id"],
            "deleted_at": None
        })
        msg["reply_count"] = reply_count
        
        # Serialize dates
        if "created_at" in msg:
            msg["created_at"] = msg["created_at"].isoformat()
        if "updated_at" in msg:
            msg["updated_at"] = msg["updated_at"].isoformat()
        
        result.append(msg)
    
    return result


@router.post("/channels/{channel_id}/messages")
async def create_message(
    channel_id: str,
    message_data: MessageCreate,
    current_user: User = Depends(get_current_user)
):
    """Send a message"""
    db = get_mongo_db()
    
    # Check channel exists
    channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    is_member = any(m.get("user_id") == current_user.id for m in channel.get("members", []))
    if not is_member:
        if channel.get("type") == "public":
            # Auto-add user to public channel members
            await db.channels.update_one(
                {"_id": ObjectId(channel_id)},
                {"$push": {"members": {
                    "user_id": current_user.id,
                    "role": "member",
                    "joined_at": datetime.utcnow(),
                    "last_read_at": None
                }}}
            )
            channel = await db.channels.find_one({"_id": ObjectId(channel_id)})
        else:
            raise HTTPException(status_code=403, detail="Not a member")
    
    message_doc = {
        "channel_id": channel_id,
        "user_id": current_user.id,
        "user_email": current_user.email,
        "content": message_data.content,
        "parent_message_id": message_data.parent_message_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "edited_at": None,
        "deleted_at": None,
        "is_pinned": False
    }
    
    result = await db.messages.insert_one(message_doc)
    message_doc["id"] = str(result.inserted_id)
    del message_doc["_id"]
    
    # Serialize dates
    message_doc["created_at"] = message_doc["created_at"].isoformat()
    message_doc["updated_at"] = message_doc["updated_at"].isoformat()
    
    payload = {
        **message_doc,
        "user": {"id": current_user.id, "email": current_user.email}
    }
    
    # 1. Broadcast to channel room (for clients currently looking at this channel)
    await ws_manager.broadcast_to_channel(channel_id, "new_message", payload)
    
    # 2. Also broadcast directly to all members of the channel
    # This guarantees cross-user delivery even if they haven't switched rooms or are in other channels
    members = channel.get("members", [])
    for member in members:
        m_uid = member.get("user_id")
        if m_uid and m_uid != current_user.id:
            await ws_manager.broadcast_to_user(m_uid, "new_message", payload)
    
    return message_doc


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete a message"""
    db = get_mongo_db()
    
    message = await db.messages.find_one({"_id": ObjectId(message_id)})
    if not message:
        raise HTTPException(status_code=404, detail="Not found")
    
    if message["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.messages.update_one(
        {"_id": ObjectId(message_id)},
        {"$set": {"deleted_at": datetime.utcnow(), "content": "[deleted]"}}
    )
    
    await ws_manager.broadcast_to_channel(message["channel_id"], "message_deleted", {
        "message_id": message_id
    })
    
    return {"message": "Deleted"}


# ============================================================================
# Reaction Endpoints
# ============================================================================

@router.post("/messages/{message_id}/reactions")
async def add_reaction(
    message_id: str,
    reaction_data: ReactionCreate,
    current_user: User = Depends(get_current_user)
):
    """Add emoji reaction"""
    db = get_mongo_db()
    
    message = await db.messages.find_one({"_id": ObjectId(message_id)})
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Check if already reacted
    existing = await db.reactions.find_one({
        "message_id": message_id,
        "user_id": current_user.id,
        "emoji": reaction_data.emoji
    })
    
    if existing:
        return {"message": "Already reacted"}
    
    await db.reactions.insert_one({
        "message_id": message_id,
        "user_id": current_user.id,
        "emoji": reaction_data.emoji,
        "created_at": datetime.utcnow()
    })
    
    await ws_manager.broadcast_to_channel(message["channel_id"], "reaction_added", {
        "message_id": message_id,
        "user_id": current_user.id,
        "emoji": reaction_data.emoji
    })
    
    return {"message": "Reaction added"}


@router.delete("/messages/{message_id}/reactions/{emoji}")
async def remove_reaction(
    message_id: str,
    emoji: str,
    current_user: User = Depends(get_current_user)
):
    """Remove reaction"""
    db = get_mongo_db()
    
    message = await db.messages.find_one({"_id": ObjectId(message_id)})
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    await db.reactions.delete_one({
        "message_id": message_id,
        "user_id": current_user.id,
        "emoji": emoji
    })
    
    await ws_manager.broadcast_to_channel(message["channel_id"], "reaction_removed", {
        "message_id": message_id,
        "user_id": current_user.id,
        "emoji": emoji
    })
    
    return {"message": "Reaction removed"}


# ============================================================================
# Search
# ============================================================================

@router.get("/search")
async def search_messages(
    q: str,
    channel_id: Optional[str] = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    """Search messages"""
    db = get_mongo_db()
    
    # Get user's channels
    channels = await db.channels.find({
        "members.user_id": current_user.id
    }).to_list(100)
    channel_ids = [str(c["_id"]) for c in channels]
    
    # Build search query
    query = {
        "channel_id": {"$in": channel_ids} if not channel_id else channel_id,
        "deleted_at": None,
        "$text": {"$search": q}
    }
    
    messages = await db.messages.find(query).sort("created_at", -1).limit(limit).to_list(limit)
    
    result = []
    for msg in messages:
        result.append({
            "id": str(msg["_id"]),
            "channel_id": msg["channel_id"],
            "user_id": msg["user_id"],
            "content": msg["content"],
            "created_at": msg["created_at"].isoformat()
        })
    
    return result


# ============================================================================
# Direct Message (DM) Endpoints
# ============================================================================

@router.get("/users")
async def list_users(
    current_user: User = Depends(get_current_user)
):
    """List all users for starting DMs"""
    from .database import SessionLocal
    from . import models as sql_models
    
    db_sql = SessionLocal()
    try:
        users = db_sql.query(sql_models.User).filter(
            sql_models.User.id != current_user.id
        ).all()
        
        return [
            {
                "id": user.id,
                "email": user.email,
                "name": user.email.split('@')[0]
            }
            for user in users
        ]
    finally:
        db_sql.close()


@router.post("/dm/{user_id}")
async def get_or_create_dm(
    user_id: int,
    current_user: User = Depends(get_current_user)
):
    """Get or create a DM channel with another user"""
    db = get_mongo_db()
    
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot DM yourself")
    
    # Check if DM already exists (either direction)
    existing_dm = await db.direct_messages.find_one({
        "$or": [
            {"participant_1": current_user.id, "participant_2": user_id},
            {"participant_1": user_id, "participant_2": current_user.id}
        ]
    })
    
    if existing_dm:
        channel = await db.channels.find_one({"_id": ObjectId(existing_dm["channel_id"])})
        if channel:
            cid_str = str(channel["_id"])
            # Ensure both users are members
            m_ids = [m.get("user_id") for m in channel.get("members", [])]
            if current_user.id not in m_ids or user_id not in m_ids:
                members_to_add = []
                if current_user.id not in m_ids:
                    members_to_add.append({"user_id": current_user.id, "role": "member", "joined_at": datetime.utcnow(), "last_read_at": None})
                if user_id not in m_ids:
                    members_to_add.append({"user_id": user_id, "role": "member", "joined_at": datetime.utcnow(), "last_read_at": None})
                if members_to_add:
                    await db.channels.update_one(
                        {"_id": channel["_id"]},
                        {"$push": {"members": {"$each": members_to_add}}}
                    )
            await ws_manager.broadcast_to_user(current_user.id, "dm_created", {"channel_id": cid_str, "other_user_id": user_id})
            await ws_manager.broadcast_to_user(user_id, "dm_created", {"channel_id": cid_str, "other_user_id": current_user.id})
            return {
                "channel_id": cid_str,
                "created": False
            }
    
    # Get other user's info
    from .database import SessionLocal
    from . import models as sql_models
    
    db_sql = SessionLocal()
    try:
        other_user = db_sql.query(sql_models.User).filter(
            sql_models.User.id == user_id
        ).first()
        
        if not other_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Create DM channel
        channel_doc = {
            "name": f"{current_user.email} ↔ {other_user.email}",
            "description": f"Direct message between {current_user.email} and {other_user.email}",
            "type": "dm",
            "created_by": current_user.id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "is_archived": False,
            "members": [
                {
                    "user_id": current_user.id,
                    "role": "member",
                    "joined_at": datetime.utcnow(),
                    "last_read_at": None
                },
                {
                    "user_id": user_id,
                    "role": "member",
                    "joined_at": datetime.utcnow(),
                    "last_read_at": None
                }
            ]
        }
        
        result = await db.channels.insert_one(channel_doc)
        channel_id = str(result.inserted_id)
        
        # Create DirectMessage record
        await db.direct_messages.insert_one({
            "channel_id": channel_id,
            "participant_1": min(current_user.id, user_id),
            "participant_2": max(current_user.id, user_id),
            "created_at": datetime.utcnow()
        })
        
        # Notify both users
        await ws_manager.broadcast_to_user(current_user.id, "dm_created", {
            "channel_id": channel_id,
            "other_user_id": user_id,
            "other_user_email": other_user.email
        })
        await ws_manager.broadcast_to_user(user_id, "dm_created", {
            "channel_id": channel_id,
            "other_user_id": current_user.id,
            "other_user_email": current_user.email
        })
        
        return {
            "channel_id": channel_id,
            "created": True
        }
    finally:
        db_sql.close()

"""
Enhanced Chat System API Routes (Phase 3)
Slack-like messaging with channels and threads
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from datetime import datetime
import json

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_chat import (
    Channel, ChannelMember, ChatMessage, MessageReaction,
    ChatFile, PinnedMessage,
    ChannelType, MessageType
)
from pydantic import BaseModel


router = APIRouter(prefix="/chat", tags=["chat"])


# Pydantic Models
class ChannelCreate(BaseModel):
    name: str
    description: Optional[str] = None
    channel_type: ChannelType = ChannelType.PUBLIC
    workspace_id: Optional[int] = None
    icon: Optional[str] = None
    topic: Optional[str] = None


class MessageCreate(BaseModel):
    content: str
    message_type: MessageType = MessageType.TEXT
    thread_parent_id: Optional[int] = None
    mentions: Optional[List[int]] = []


class MessageUpdate(BaseModel):
    content: str


class ReactionCreate(BaseModel):
    emoji: str


# ===== CHANNEL ENDPOINTS =====

@router.post("/channels", status_code=status.HTTP_201_CREATED)
def create_channel(
    channel: ChannelCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new channel"""
    new_channel = Channel(
        **channel.dict(),
        created_by=current_user.id
    )
    db.add(new_channel)
    db.commit()
    db.refresh(new_channel)
    
    # Add creator as admin member
    member = ChannelMember(
        channel_id=new_channel.id,
        user_id=current_user.id,
        is_admin=True
    )
    db.add(member)
    db.commit()
    
    return new_channel


@router.get("/channels")
def list_channels(
    workspace_id: Optional[int] = None,
    channel_type: Optional[ChannelType] = None,
    archived: bool = False,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all channels user has access to"""
    # Get channels where user is a member
    member_channel_ids = db.query(ChannelMember.channel_id).filter(
        ChannelMember.user_id == current_user.id
    ).subquery()
    
    query = db.query(Channel).filter(
        or_(
            Channel.id.in_(member_channel_ids),
            Channel.channel_type == ChannelType.PUBLIC
        ),
        Channel.is_archived == archived
    )
    
    if workspace_id:
        query = query.filter(Channel.workspace_id == workspace_id)
    if channel_type:
        query = query.filter(Channel.channel_type == channel_type)
    
    return query.order_by(Channel.created_at.desc()).all()


@router.get("/channels/{channel_id}")
def get_channel(
    channel_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get channel details"""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Check access
    if channel.channel_type != ChannelType.PUBLIC:
        member = db.query(ChannelMember).filter(
            ChannelMember.channel_id == channel_id,
            ChannelMember.user_id == current_user.id
        ).first()
        if not member:
            raise HTTPException(status_code=403, detail="Access denied")
    
    return channel


@router.post("/channels/{channel_id}/join")
def join_channel(
    channel_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Join a channel"""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    if channel.channel_type == ChannelType.PRIVATE:
        raise HTTPException(status_code=403, detail="Cannot join private channel")
    
    # Check if already a member
    existing = db.query(ChannelMember).filter(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user.id
    ).first()
    
    if existing:
        return {"message": "Already a member"}
    
    member = ChannelMember(
        channel_id=channel_id,
        user_id=current_user.id
    )
    db.add(member)
    db.commit()
    
    return {"message": "Joined channel"}


@router.post("/channels/{channel_id}/leave")
def leave_channel(
    channel_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Leave a channel"""
    member = db.query(ChannelMember).filter(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user.id
    ).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Not a member")
    
    db.delete(member)
    db.commit()
    
    return {"message": "Left channel"}


@router.get("/channels/{channel_id}/members")
def get_channel_members(
    channel_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all members of a channel"""
    members = db.query(ChannelMember).filter(
        ChannelMember.channel_id == channel_id
    ).all()
    return members


# ===== MESSAGE ENDPOINTS =====

@router.post("/channels/{channel_id}/messages", status_code=status.HTTP_201_CREATED)
def send_message(
    channel_id: int,
    message: MessageCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send a message to a channel"""
    # Check membership
    member = db.query(ChannelMember).filter(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user.id
    ).first()
    
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not member and channel.channel_type != ChannelType.PUBLIC:
        raise HTTPException(status_code=403, detail="Not a channel member")
    
    new_message = ChatMessage(
        channel_id=channel_id,
        user_id=current_user.id,
        content=message.content,
        message_type=message.message_type,
        thread_parent_id=message.thread_parent_id,
        mentions=json.dumps(message.mentions) if message.mentions else None
    )
    db.add(new_message)
    
    # Update thread reply count
    if message.thread_parent_id:
        parent = db.query(ChatMessage).filter(ChatMessage.id == message.thread_parent_id).first()
        if parent:
            parent.thread_reply_count += 1
    
    db.commit()
    db.refresh(new_message)
    return new_message


@router.get("/channels/{channel_id}/messages")
def get_messages(
    channel_id: int,
    thread_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get messages from a channel"""
    # Check access
    member = db.query(ChannelMember).filter(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user.id
    ).first()
    
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not member and channel.channel_type != ChannelType.PUBLIC:
        raise HTTPException(status_code=403, detail="Access denied")
    
    query = db.query(ChatMessage).filter(
        ChatMessage.channel_id == channel_id,
        ChatMessage.is_deleted == False
    )
    
    if thread_id:
        # Get thread replies
        query = query.filter(ChatMessage.thread_parent_id == thread_id)
    else:
        # Get top-level messages only
        query = query.filter(ChatMessage.thread_parent_id == None)
    
    messages = query.order_by(ChatMessage.created_at.desc()).offset(skip).limit(limit).all()
    
    # Update last_read_at
    if member:
        member.last_read_at = datetime.utcnow()
        db.commit()
    
    return messages


@router.patch("/messages/{message_id}")
def edit_message(
    message_id: int,
    message_update: MessageUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Edit a message"""
    message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    if message.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only edit own messages")
    
    message.content = message_update.content
    message.edited_at = datetime.utcnow()
    db.commit()
    
    return message


@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a message"""
    message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    if message.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only delete own messages")
    
    message.is_deleted = True
    message.content = "[deleted]"
    db.commit()
    
    return {"message": "Message deleted"}


# ===== REACTIONS =====

@router.post("/messages/{message_id}/reactions")
def add_reaction(
    message_id: int,
    reaction: ReactionCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a reaction to a message"""
    # Check if already reacted with same emoji
    existing = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id,
        MessageReaction.user_id == current_user.id,
        MessageReaction.emoji == reaction.emoji
    ).first()
    
    if existing:
        # Remove reaction (toggle)
        db.delete(existing)
        db.commit()
        return {"message": "Reaction removed"}
    
    new_reaction = MessageReaction(
        message_id=message_id,
        user_id=current_user.id,
        emoji=reaction.emoji
    )
    db.add(new_reaction)
    db.commit()
    
    return {"message": "Reaction added"}


@router.get("/messages/{message_id}/reactions")
def get_reactions(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all reactions for a message"""
    reactions = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id
    ).all()
    return reactions


# ===== THREADS =====

@router.get("/messages/{message_id}/thread")
def get_thread(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a message thread"""
    parent = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Message not found")
    
    replies = db.query(ChatMessage).filter(
        ChatMessage.thread_parent_id == message_id,
        ChatMessage.is_deleted == False
    ).order_by(ChatMessage.created_at.asc()).all()
    
    return {
        "parent": parent,
        "replies": replies
    }


# ===== PINNED MESSAGES =====

@router.post("/channels/{channel_id}/pin/{message_id}")
def pin_message(
    channel_id: int,
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Pin a message in a channel"""
    # Check if user is channel admin
    member = db.query(ChannelMember).filter(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user.id
    ).first()
    
    if not member or not member.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Check if already pinned
    existing = db.query(PinnedMessage).filter(
        PinnedMessage.channel_id == channel_id,
        PinnedMessage.message_id == message_id
    ).first()
    
    if existing:
        return {"message": "Already pinned"}
    
    pinned = PinnedMessage(
        channel_id=channel_id,
        message_id=message_id,
        pinned_by=current_user.id
    )
    db.add(pinned)
    db.commit()
    
    return {"message": "Message pinned"}


@router.get("/channels/{channel_id}/pinned")
def get_pinned_messages(
    channel_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all pinned messages in a channel"""
    pinned = db.query(PinnedMessage).filter(
        PinnedMessage.channel_id == channel_id
    ).order_by(PinnedMessage.pinned_at.desc()).all()
    return pinned


# ===== DIRECT MESSAGES =====

@router.post("/dm/{user_id}")
def create_or_get_dm(
    user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create or get existing DM channel with a user"""
    # Check if DM already exists
    participants = f"{min(current_user.id, user_id)},{max(current_user.id, user_id)}"
    
    existing = db.query(Channel).filter(
        Channel.channel_type == ChannelType.DIRECT,
        Channel.participants == participants
    ).first()
    
    if existing:
        return existing
    
    # Create new DM channel
    dm_channel = Channel(
        name=f"DM-{current_user.id}-{user_id}",
        channel_type=ChannelType.DIRECT,
        participants=participants,
        created_by=current_user.id
    )
    db.add(dm_channel)
    db.commit()
    db.refresh(dm_channel)
    
    # Add both users as members
    for uid in [current_user.id, user_id]:
        member = ChannelMember(
            channel_id=dm_channel.id,
            user_id=uid
        )
        db.add(member)
    
    db.commit()
    return dm_channel


# ===== SEARCH =====

@router.get("/search")
def search_messages(
    query: str,
    channel_id: Optional[int] = None,
    limit: int = 20,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search messages across channels"""
    # Get accessible channels
    member_channels = db.query(ChannelMember.channel_id).filter(
        ChannelMember.user_id == current_user.id
    ).subquery()
    
    search_query = db.query(ChatMessage).filter(
        ChatMessage.is_deleted == False,
        ChatMessage.content.ilike(f"%{query}%"),
        or_(
            ChatMessage.channel_id.in_(member_channels),
            ChatMessage.channel_id.in_(
                db.query(Channel.id).filter(Channel.channel_type == ChannelType.PUBLIC)
            )
        )
    )
    
    if channel_id:
        search_query = search_query.filter(ChatMessage.channel_id == channel_id)
    
    results = search_query.order_by(ChatMessage.created_at.desc()).limit(limit).all()
    return results


# ===== UNREAD COUNT =====

@router.get("/unread")
def get_unread_counts(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get unread message counts for all channels"""
    memberships = db.query(ChannelMember).filter(
        ChannelMember.user_id == current_user.id
    ).all()
    
    unread = []
    for membership in memberships:
        count = db.query(ChatMessage).filter(
            ChatMessage.channel_id == membership.channel_id,
            ChatMessage.created_at > membership.last_read_at,
            ChatMessage.user_id != current_user.id
        ).count()
        
        if count > 0:
            unread.append({
                "channel_id": membership.channel_id,
                "unread_count": count
            })
    
    return unread

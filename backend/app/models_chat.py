"""
Enhanced Chat System Models (Phase 3)
Slack-like messaging with channels, threads, and file sharing
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base
import enum


class ChannelType(str, enum.Enum):
    """Channel types"""
    PUBLIC = "public"
    PRIVATE = "private"
    DIRECT = "direct"  # DM
    GROUP = "group"  # Group DM


class MessageType(str, enum.Enum):
    """Message types"""
    TEXT = "text"
    FILE = "file"
    IMAGE = "image"
    SYSTEM = "system"  # System notifications
    MEETING_LINK = "meeting_link"


class Channel(Base):
    """Chat channels (like Slack channels)"""
    __tablename__ = "chat_channels"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    channel_type = Column(SQLEnum(ChannelType), default=ChannelType.PUBLIC)
    
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    
    # Direct/Group DM participants (comma-separated user IDs for quick lookup)
    participants = Column(Text, nullable=True)
    
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    is_archived = Column(Boolean, default=False)
    
    # Metadata
    icon = Column(String(100), nullable=True)
    topic = Column(String(500), nullable=True)
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    workspace = relationship("Workspace", back_populates="chat_channels")
    messages = relationship("ChatMessage", back_populates="channel", cascade="all, delete-orphan")
    members = relationship("ChannelMember", back_populates="channel", cascade="all, delete-orphan")


class ChannelMember(Base):
    """Channel membership"""
    __tablename__ = "channel_members"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    is_admin = Column(Boolean, default=False)
    
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_read_at = Column(DateTime, default=datetime.utcnow)
    
    # Notifications
    muted = Column(Boolean, default=False)
    
    # Relationships
    channel = relationship("Channel", back_populates="members")
    user = relationship("User")


class ChatMessage(Base):
    """Chat messages"""
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=False)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    
    message_type = Column(SQLEnum(MessageType), default=MessageType.TEXT)
    
    # Threading
    thread_parent_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=True)
    thread_reply_count = Column(Integer, default=0)
    
    # Attachments
    file_url = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    
    # Editing
    edited_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False)
    
    # Mentions (@user)
    mentions = Column(Text, nullable=True)  # JSON array of user IDs
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    channel = relationship("Channel", back_populates="messages")
    user = relationship("User")
    reactions = relationship("MessageReaction", back_populates="message", cascade="all, delete-orphan")
    thread_replies = relationship("ChatMessage", backref="thread_parent", remote_side=[id])


class MessageReaction(Base):
    """Emoji reactions to messages"""
    __tablename__ = "message_reactions"
    
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    emoji = Column(String(50), nullable=False)  # :thumbsup:, :fire:, etc.
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    message = relationship("ChatMessage", back_populates="reactions")
    user = relationship("User")


class ChatFile(Base):
    """Files shared in chat"""
    __tablename__ = "chat_files"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String(100), nullable=True)  # MIME type
    
    thumbnail_path = Column(String(500), nullable=True)  # For images/videos
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    channel = relationship("Channel")
    user = relationship("User")


class PinnedMessage(Base):
    """Pinned messages in channels"""
    __tablename__ = "pinned_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=False)
    
    pinned_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    pinned_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    channel = relationship("Channel")
    message = relationship("ChatMessage")
    user = relationship("User")

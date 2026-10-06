"""
Document & Wiki System Models (Phase 2)
Google Docs-like collaborative editing with version history
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base
import enum


class DocumentType(str, enum.Enum):
    """Document types"""
    DOC = "doc"  # Regular document
    WIKI = "wiki"  # Wiki page
    TEMPLATE = "template"  # Template
    MEETING_NOTE = "meeting_note"  # Auto-generated from meeting


class PermissionLevel(str, enum.Enum):
    """Document permission levels"""
    VIEW = "view"
    COMMENT = "comment"
    EDIT = "edit"
    OWNER = "owner"


class Document(Base):
    """Main document table"""
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=True)  # Rich text content (HTML/Markdown)
    doc_type = Column(SQLEnum(DocumentType), default=DocumentType.DOC)
    
    # Workspace and organization
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    folder_id = Column(Integer, ForeignKey("doc_folders.id"), nullable=True)
    parent_doc_id = Column(Integer, ForeignKey("documents.id"), nullable=True)  # For nested pages
    
    # Owner and collaboration
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_public = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    
    # Meeting integration
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    
    # Metadata
    icon = Column(String(100), nullable=True)  # Emoji or icon
    cover_image = Column(String(500), nullable=True)
    view_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    workspace = relationship("Workspace", back_populates="documents")
    folder = relationship("DocFolder", back_populates="documents")
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")
    comments = relationship("DocumentComment", back_populates="document", cascade="all, delete-orphan")
    permissions = relationship("DocumentPermission", back_populates="document", cascade="all, delete-orphan")
    child_pages = relationship("Document", backref="parent_doc", remote_side=[id])


class DocFolder(Base):
    """Document folders for organization"""
    __tablename__ = "doc_folders"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    parent_folder_id = Column(Integer, ForeignKey("doc_folders.id"), nullable=True)
    
    color = Column(String(20), default="#3B82F6")
    icon = Column(String(100), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    workspace = relationship("Workspace", back_populates="doc_folders")
    documents = relationship("Document", back_populates="folder")
    child_folders = relationship("DocFolder", backref="parent_folder", remote_side=[id])


class DocumentVersion(Base):
    """Version history for documents"""
    __tablename__ = "document_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    
    version_number = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    title = Column(String(500), nullable=False)
    
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    change_summary = Column(Text, nullable=True)  # What changed
    
    # Relationships
    document = relationship("Document", back_populates="versions")
    creator = relationship("User")


class DocumentComment(Base):
    """Comments on documents"""
    __tablename__ = "document_comments"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    
    # Position in document (for inline comments)
    position_start = Column(Integer, nullable=True)
    position_end = Column(Integer, nullable=True)
    
    # Threading
    parent_comment_id = Column(Integer, ForeignKey("document_comments.id"), nullable=True)
    
    is_resolved = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    document = relationship("Document", back_populates="comments")
    user = relationship("User")
    replies = relationship("DocumentComment", backref="parent_comment", remote_side=[id])


class DocumentPermission(Base):
    """Fine-grained permissions for documents"""
    __tablename__ = "document_permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    
    permission_level = Column(SQLEnum(PermissionLevel), nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    document = relationship("Document", back_populates="permissions")
    user = relationship("User")
    workspace = relationship("Workspace")


class DocumentTemplate(Base):
    """Reusable document templates"""
    __tablename__ = "document_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    
    category = Column(String(100), nullable=True)  # "Meeting Notes", "Project Brief", etc.
    icon = Column(String(100), nullable=True)
    
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    is_public = Column(Boolean, default=True)
    
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    use_count = Column(Integer, default=0)
    
    # Relationships
    creator = relationship("User")
    workspace = relationship("Workspace")

"""
Document & Wiki System API Routes (Phase 2)
Google Docs-like collaborative editing
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_docs import (
    Document, DocFolder, DocumentVersion, DocumentComment,
    DocumentPermission, DocumentTemplate,
    DocumentType, PermissionLevel
)
from pydantic import BaseModel


router = APIRouter(prefix="/docs", tags=["documents"])


# Pydantic Models
class DocumentCreate(BaseModel):
    title: str
    content: Optional[str] = ""
    doc_type: DocumentType = DocumentType.DOC
    workspace_id: Optional[int] = None
    folder_id: Optional[int] = None
    parent_doc_id: Optional[int] = None
    icon: Optional[str] = None
    cover_image: Optional[str] = None
    is_public: bool = False


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    icon: Optional[str] = None
    cover_image: Optional[str] = None
    is_public: Optional[bool] = None
    is_archived: Optional[bool] = None


class DocumentResponse(BaseModel):
    id: int
    title: str
    content: Optional[str]
    doc_type: str
    owner_id: int
    workspace_id: Optional[int]
    folder_id: Optional[int]
    parent_doc_id: Optional[int]
    is_public: bool
    is_archived: bool
    icon: Optional[str]
    cover_image: Optional[str]
    view_count: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class FolderCreate(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_id: int
    parent_folder_id: Optional[int] = None
    color: str = "#3B82F6"
    icon: Optional[str] = None


class CommentCreate(BaseModel):
    content: str
    position_start: Optional[int] = None
    position_end: Optional[int] = None
    parent_comment_id: Optional[int] = None


class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    content: str
    category: Optional[str] = None
    icon: Optional[str] = None
    workspace_id: Optional[int] = None


# ===== FOLDER ENDPOINTS =====

@router.post("/folders", status_code=status.HTTP_201_CREATED)
def create_folder(
    folder: FolderCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a document folder"""
    new_folder = DocFolder(**folder.dict())
    db.add(new_folder)
    db.commit()
    db.refresh(new_folder)
    return new_folder


@router.get("/folders")
def list_folders(
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all folders"""
    query = db.query(DocFolder)
    if workspace_id:
        query = query.filter(DocFolder.workspace_id == workspace_id)
    return query.all()


# ===== DOCUMENT ENDPOINTS =====

@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
@router.post("/", status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
def create_document(
    doc: DocumentCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new document"""
    new_doc = Document(
        **doc.dict(),
        owner_id=current_user.id
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    
    # Create initial version
    version = DocumentVersion(
        document_id=new_doc.id,
        version_number=1,
        content=doc.content or "",
        title=doc.title,
        created_by=current_user.id,
        change_summary="Initial creation"
    )
    db.add(version)
    db.commit()
    
    return new_doc


@router.get("", response_model=List[DocumentResponse])
@router.get("/", response_model=List[DocumentResponse])
def list_documents(
    workspace_id: Optional[int] = None,
    folder_id: Optional[int] = None,
    doc_type: Optional[DocumentType] = None,
    search: Optional[str] = None,
    archived: bool = False,
    skip: int = 0,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List documents with filters"""
    query = db.query(Document).filter(Document.is_archived == archived)
    
    # Filter by ownership or public
    query = query.filter(
        (Document.owner_id == current_user.id) | 
        (Document.is_public == True)
    )
    
    if workspace_id:
        query = query.filter(Document.workspace_id == workspace_id)
    if folder_id:
        query = query.filter(Document.folder_id == folder_id)
    if doc_type:
        query = query.filter(Document.doc_type == doc_type)
    if search:
        query = query.filter(
            (Document.title.ilike(f"%{search}%")) |
            (Document.content.ilike(f"%{search}%"))
        )
    
    return query.order_by(Document.updated_at.desc()).offset(skip).limit(limit).all()


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(
    doc_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific document"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check permissions
    if not doc.is_public and doc.owner_id != current_user.id:
        # Check if user has explicit permission
        permission = db.query(DocumentPermission).filter(
            DocumentPermission.document_id == doc_id,
            DocumentPermission.user_id == current_user.id
        ).first()
        if not permission:
            raise HTTPException(status_code=403, detail="Access denied")
    
    # Increment view count
    doc.view_count += 1
    db.commit()
    
    return doc


@router.patch("/{doc_id}", response_model=DocumentResponse)
def update_document(
    doc_id: int,
    doc_update: DocumentUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a document"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check edit permission
    if doc.owner_id != current_user.id:
        permission = db.query(DocumentPermission).filter(
            DocumentPermission.document_id == doc_id,
            DocumentPermission.user_id == current_user.id,
            DocumentPermission.permission_level.in_([PermissionLevel.EDIT, PermissionLevel.OWNER])
        ).first()
        if not permission:
            raise HTTPException(status_code=403, detail="No edit permission")
    
    # Create version if content changed
    if doc_update.content and doc_update.content != doc.content:
        last_version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id
        ).order_by(DocumentVersion.version_number.desc()).first()
        
        new_version = DocumentVersion(
            document_id=doc_id,
            version_number=(last_version.version_number + 1) if last_version else 1,
            content=doc_update.content,
            title=doc_update.title or doc.title,
            created_by=current_user.id,
            change_summary="Content updated"
        )
        db.add(new_version)
    
    # Update document
    update_data = doc_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(doc, field, value)
    
    doc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a document"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can delete")
    
    db.delete(doc)
    db.commit()
    return {"message": "Document deleted"}


# ===== VERSION HISTORY =====

@router.get("/{doc_id}/versions")
def get_versions(
    doc_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get document version history"""
    versions = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_id
    ).order_by(DocumentVersion.version_number.desc()).all()
    return versions


@router.post("/{doc_id}/restore/{version_number}")
def restore_version(
    doc_id: int,
    version_number: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restore document to a previous version"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc or doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    version = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_id,
        DocumentVersion.version_number == version_number
    ).first()
    
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    doc.content = version.content
    doc.title = version.title
    doc.updated_at = datetime.utcnow()
    db.commit()
    
    return {"message": f"Restored to version {version_number}"}


# ===== COMMENTS =====

@router.post("/{doc_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    doc_id: int,
    comment: CommentCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a comment to a document"""
    new_comment = DocumentComment(
        document_id=doc_id,
        user_id=current_user.id,
        **comment.dict()
    )
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)
    return new_comment


@router.get("/{doc_id}/comments")
def get_comments(
    doc_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all comments for a document"""
    comments = db.query(DocumentComment).filter(
        DocumentComment.document_id == doc_id
    ).order_by(DocumentComment.created_at.asc()).all()
    return comments


@router.patch("/comments/{comment_id}/resolve")
def resolve_comment(
    comment_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark a comment as resolved"""
    comment = db.query(DocumentComment).filter(DocumentComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    
    comment.is_resolved = True
    db.commit()
    return {"message": "Comment resolved"}


# ===== PERMISSIONS =====

@router.post("/{doc_id}/permissions")
def grant_permission(
    doc_id: int,
    user_id: int,
    permission_level: PermissionLevel,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Grant permission to a user"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc or doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can grant permissions")
    
    # Check if permission already exists
    existing = db.query(DocumentPermission).filter(
        DocumentPermission.document_id == doc_id,
        DocumentPermission.user_id == user_id
    ).first()
    
    if existing:
        existing.permission_level = permission_level
    else:
        permission = DocumentPermission(
            document_id=doc_id,
            user_id=user_id,
            permission_level=permission_level
        )
        db.add(permission)
    
    db.commit()
    return {"message": "Permission granted"}


# ===== TEMPLATES =====

@router.post("/templates", status_code=status.HTTP_201_CREATED)
def create_template(
    template: TemplateCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a document template"""
    new_template = DocumentTemplate(
        **template.dict(),
        created_by=current_user.id
    )
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return new_template


@router.get("/templates")
def list_templates(
    category: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all templates"""
    query = db.query(DocumentTemplate).filter(DocumentTemplate.is_public == True)
    if category:
        query = query.filter(DocumentTemplate.category == category)
    return query.order_by(DocumentTemplate.use_count.desc()).all()


@router.post("/templates/{template_id}/use")
def use_template(
    template_id: int,
    title: str,
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a document from a template"""
    template = db.query(DocumentTemplate).filter(DocumentTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Create document from template
    new_doc = Document(
        title=title,
        content=template.content,
        doc_type=DocumentType.DOC,
        workspace_id=workspace_id,
        owner_id=current_user.id,
        icon=template.icon
    )
    db.add(new_doc)
    
    # Increment use count
    template.use_count += 1
    
    db.commit()
    db.refresh(new_doc)
    return new_doc


# ===== MEETING INTEGRATION =====

@router.post("/from-meeting/{meeting_id}", response_model=DocumentResponse)
def create_from_meeting(
    meeting_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a document from a meeting"""
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    # Create document with meeting content
    content = f"""
# Meeting Notes: {meeting.title}

**Date:** {meeting.scheduled_time or meeting.created_at}

## Summary
{meeting.summary or 'No summary available'}

## Transcript
{meeting.transcript or 'No transcript available'}

## Action Items
- Review and add action items here
"""
    
    new_doc = Document(
        title=f"Notes: {meeting.title}",
        content=content,
        doc_type=DocumentType.MEETING_NOTE,
        owner_id=current_user.id,
        meeting_id=meeting_id,
        icon="📝"
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    
    return new_doc

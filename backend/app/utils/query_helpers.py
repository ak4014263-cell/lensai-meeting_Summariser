"""Optimized database query helpers with caching.

Provides reusable query functions with built-in caching and optimization.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from sqlalchemy import desc, and_, or_, func
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import models
from ..models import MeetingStatus
from .cache import CacheManager, cached

logger = logging.getLogger("lensai_bot.queries")


class MeetingQueries:
    """Optimized queries for meetings."""
    
    @staticmethod
    def get_meeting_by_id(
        db: Session,
        meeting_id: int,
        user_id: Optional[int] = None,
        with_transcript: bool = False,
        with_summary: bool = False,
    ) -> Optional[models.Meeting]:
        """
        Get a meeting by ID with optional eager loading.
        
        Args:
            db: Database session
            meeting_id: Meeting ID
            user_id: Optional user ID for ownership check
            with_transcript: Load transcript segments
            with_summary: Load summary data
            
        Returns:
            Meeting object or None
        """
        query = db.query(models.Meeting).filter(models.Meeting.id == meeting_id)
        
        # Add user filter if provided
        if user_id is not None:
            query = query.filter(models.Meeting.owner_id == user_id)
        
        # Eager load related data
        options = []
        if with_transcript:
            options.append(selectinload(models.Meeting.transcript))
        if with_summary:
            options.append(joinedload(models.Meeting.summary))
            options.append(selectinload(models.Meeting.decisions))
            options.append(selectinload(models.Meeting.action_items))
        
        if options:
            query = query.options(*options)
        
        return query.first()
    
    @staticmethod
    @cached(ttl=300, key_prefix="user_meetings")
    def get_user_meetings(
        db: Session,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[models.Meeting]:
        """
        Get meetings for a user with pagination.
        
        Cached for 5 minutes to reduce DB load on dashboard.
        
        Args:
            db: Database session
            user_id: User ID
            status: Optional status filter
            limit: Maximum results
            offset: Pagination offset
            
        Returns:
            List of Meeting objects
        """
        query = db.query(models.Meeting).filter(
            models.Meeting.owner_id == user_id
        )
        
        if status:
            query = query.filter(models.Meeting.status == status)
        
        query = query.order_by(desc(models.Meeting.created_at))
        query = query.limit(limit).offset(offset)
        
        return query.all()
    
    @staticmethod
    def get_active_meetings(db: Session, user_id: int) -> List[models.Meeting]:
        """
        Get all active (in-progress) meetings for a user.
        
        Args:
            db: Database session
            user_id: User ID
            
        Returns:
            List of active meetings
        """
        active_statuses = [
            MeetingStatus.BOT_QUEUED,
            MeetingStatus.BOT_JOINED,
            MeetingStatus.BOT_RECORDING,
            MeetingStatus.TRANSCRIBING,
            MeetingStatus.SUMMARISING,
        ]
        
        return db.query(models.Meeting).filter(
            and_(
                models.Meeting.owner_id == user_id,
                models.Meeting.status.in_(active_statuses)
            )
        ).order_by(desc(models.Meeting.updated_at)).all()
    
    @staticmethod
    def count_user_meetings(
        db: Session,
        user_id: int,
        status: Optional[str] = None,
    ) -> int:
        """
        Count meetings for a user.
        
        Args:
            db: Database session
            user_id: User ID
            status: Optional status filter
            
        Returns:
            Count of meetings
        """
        query = db.query(func.count(models.Meeting.id)).filter(
            models.Meeting.owner_id == user_id
        )
        
        if status:
            query = query.filter(models.Meeting.status == status)
        
        return query.scalar() or 0


class TranscriptQueries:
    """Optimized queries for transcripts."""
    
    @staticmethod
    def get_transcript_text(
        db: Session,
        meeting_id: int,
        cache_result: bool = True,
    ) -> str:
        """
        Get full transcript text for a meeting.
        
        Cached to avoid repeated DB queries and text formatting.
        
        Args:
            db: Database session
            meeting_id: Meeting ID
            cache_result: Whether to use/update cache
            
        Returns:
            Formatted transcript text
        """
        # Try cache first
        if cache_result:
            cached = CacheManager.get_transcript(meeting_id)
            if cached:
                logger.debug(f"Transcript cache hit: meeting {meeting_id}")
                return cached
        
        # Query from database
        segments = db.query(models.TranscriptSegment).filter(
            models.TranscriptSegment.meeting_id == meeting_id
        ).order_by(models.TranscriptSegment.start_time).all()
        
        # Format transcript
        from ..ai.pipeline import build_transcript_text
        transcript = build_transcript_text(segments)
        
        # Cache result
        if cache_result and transcript:
            CacheManager.cache_transcript(meeting_id, transcript)
        
        return transcript
    
    @staticmethod
    def search_transcript(
        db: Session,
        meeting_id: int,
        search_term: str,
        limit: int = 50,
    ) -> List[models.TranscriptSegment]:
        """
        Search within a meeting's transcript.
        
        Uses PostgreSQL full-text search for performance.
        
        Args:
            db: Database session
            meeting_id: Meeting ID
            search_term: Search query
            limit: Maximum results
            
        Returns:
            List of matching transcript segments
        """
        # Use PostgreSQL full-text search if available
        try:
            from sqlalchemy import func
            
            query = db.query(models.TranscriptSegment).filter(
                and_(
                    models.TranscriptSegment.meeting_id == meeting_id,
                    func.to_tsvector('english', models.TranscriptSegment.text).match(
                        search_term
                    )
                )
            ).order_by(models.TranscriptSegment.start_time).limit(limit)
            
            return query.all()
        except:
            # Fallback to LIKE search
            query = db.query(models.TranscriptSegment).filter(
                and_(
                    models.TranscriptSegment.meeting_id == meeting_id,
                    models.TranscriptSegment.text.ilike(f"%{search_term}%")
                )
            ).order_by(models.TranscriptSegment.start_time).limit(limit)
            
            return query.all()
    
    @staticmethod
    def get_segments_by_speaker(
        db: Session,
        meeting_id: int,
        speaker: str,
    ) -> List[models.TranscriptSegment]:
        """
        Get all segments for a specific speaker.
        
        Args:
            db: Database session
            meeting_id: Meeting ID
            speaker: Speaker name
            
        Returns:
            List of transcript segments
        """
        return db.query(models.TranscriptSegment).filter(
            and_(
                models.TranscriptSegment.meeting_id == meeting_id,
                models.TranscriptSegment.speaker == speaker
            )
        ).order_by(models.TranscriptSegment.start_time).all()


class SummaryQueries:
    """Optimized queries for summaries."""
    
    @staticmethod
    def get_meeting_summary(
        db: Session,
        meeting_id: int,
        cache_result: bool = True,
    ) -> Optional[dict]:
        """
        Get complete summary for a meeting.
        
        Returns all summary fields, decisions, and action items.
        Cached to reduce DB load.
        
        Args:
            db: Database session
            meeting_id: Meeting ID
            cache_result: Whether to use/update cache
            
        Returns:
            Summary dict or None
        """
        # Try cache first
        if cache_result:
            cached = CacheManager.get_meeting_summary(meeting_id)
            if cached:
                logger.debug(f"Summary cache hit: meeting {meeting_id}")
                return cached
        
        # Query from database
        summary = db.query(models.Summary).filter(
            models.Summary.meeting_id == meeting_id
        ).first()
        
        if not summary:
            return None
        
        decisions = db.query(models.Decision).filter(
            models.Decision.meeting_id == meeting_id
        ).all()
        
        action_items = db.query(models.ActionItem).filter(
            models.ActionItem.meeting_id == meeting_id
        ).all()
        
        # Build response
        result = {
            "executive_summary": summary.executive_summary or "",
            "key_points": (summary.key_points or "").split("\n") if summary.key_points else [],
            "topics": (summary.topics or "").split("\n") if summary.topics else [],
            "risks": (summary.risks or "").split("\n") if summary.risks else [],
            "questions": (summary.questions or "").split("\n") if summary.questions else [],
            "next_steps": (summary.next_steps or "").split("\n") if summary.next_steps else [],
            "decisions": [{"text": d.text} for d in decisions],
            "action_items": [
                {
                    "text": item.text,
                    "owner": item.owner,
                    "deadline": item.deadline,
                    "is_completed": item.is_completed,
                }
                for item in action_items
            ],
            "model": summary.model,
        }
        
        # Cache result
        if cache_result:
            CacheManager.cache_meeting_summary(meeting_id, result)
        
        return result
    
    @staticmethod
    def get_pending_action_items(
        db: Session,
        user_id: int,
        limit: int = 50,
    ) -> List[dict]:
        """
        Get all pending action items for a user across all meetings.
        
        Args:
            db: Database session
            user_id: User ID
            limit: Maximum results
            
        Returns:
            List of action items with meeting info
        """
        results = db.query(
            models.ActionItem,
            models.Meeting.title,
            models.Meeting.created_at
        ).join(
            models.Meeting,
            models.ActionItem.meeting_id == models.Meeting.id
        ).filter(
            and_(
                models.Meeting.owner_id == user_id,
                models.ActionItem.is_completed == False
            )
        ).order_by(desc(models.Meeting.created_at)).limit(limit).all()
        
        return [
            {
                "text": item.text,
                "owner": item.owner,
                "deadline": item.deadline,
                "meeting_title": title,
                "meeting_date": created_at,
                "meeting_id": item.meeting_id,
            }
            for item, title, created_at in results
        ]


class ParticipantQueries:
    """Optimized queries for participants."""
    
    @staticmethod
    def get_meeting_participants(
        db: Session,
        meeting_id: int,
    ) -> List[models.Participant]:
        """
        Get all participants for a meeting.
        
        Args:
            db: Database session
            meeting_id: Meeting ID
            
        Returns:
            List of participants
        """
        return db.query(models.Participant).filter(
            models.Participant.meeting_id == meeting_id
        ).order_by(models.Participant.name).all()
    
    @staticmethod
    def get_user_frequent_participants(
        db: Session,
        user_id: int,
        limit: int = 10,
    ) -> List[tuple[str, int]]:
        """
        Get most frequent participants across user's meetings.
        
        Args:
            db: Database session
            user_id: User ID
            limit: Maximum results
            
        Returns:
            List of (participant_name, count) tuples
        """
        results = db.query(
            models.Participant.name,
            func.count(models.Participant.id).label('count')
        ).join(
            models.Meeting,
            models.Participant.meeting_id == models.Meeting.id
        ).filter(
            models.Meeting.owner_id == user_id
        ).group_by(
            models.Participant.name
        ).order_by(
            desc('count')
        ).limit(limit).all()
        
        return [(name, count) for name, count in results]


# Export query classes
__all__ = [
    "MeetingQueries",
    "TranscriptQueries",
    "SummaryQueries",
    "ParticipantQueries",
]

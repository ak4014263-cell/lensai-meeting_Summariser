"""
Complete Database Migration Script for All LensAI Phases
Creates all tables for Phases 1-5
Usage: python create_all_tables.py
"""
from sqlalchemy import create_engine
from app.database import Base, SQLALCHEMY_DATABASE_URL

# Import existing models first
from app import models

# Import Phase 1: Task Management
from app.models_tasks import (
    Task, TaskList, TaskFolder, Workspace, WorkspaceMember,
    TaskComment, TaskAttachment, TaskChecklist, ChecklistItem,
    TaskDependency, TimeEntry
)

# Import Phase 2: Documents & Wiki
from app.models_docs import (
    Document, DocFolder, DocumentVersion, DocumentComment,
    DocumentPermission, DocumentTemplate
)

# Import Phase 3: Enhanced Chat
from app.models_chat import (
    Channel, ChannelMember, ChatMessage, MessageReaction,
    ChatFile, PinnedMessage
)

# Import Phase 4: Goals & Dashboards
from app.models_goals import (
    Goal, KeyResult, GoalUpdate, Dashboard, DashboardWidget, Milestone
)

# Import Phase 5: Time Tracking
from app.models_time import (
    TimeEntryEnhanced, TimeReport, ProductivityMetric,
    WorkBreak, TimeGoal
)


def create_tables():
    """Create all tables for phases 1-5"""
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    
    print("=" * 60)
    print("Creating LensAI-Inspired Feature Tables")
    print("=" * 60)
    
    # This will create all tables defined in all models
    Base.metadata.create_all(bind=engine)
    
    print("\n✓ All tables created successfully!")
    print("\nPhase 1: Task Management System")
    print("  - workspaces")
    print("  - workspace_members")
    print("  - task_folders")
    print("  - task_lists")
    print("  - tasks")
    print("  - task_comments")
    print("  - task_attachments")
    print("  - task_checklists")
    print("  - checklist_items")
    print("  - task_dependencies")
    print("  - time_entries")
    
    print("\nPhase 2: Document & Wiki System")
    print("  - documents")
    print("  - doc_folders")
    print("  - document_versions")
    print("  - document_comments")
    print("  - document_permissions")
    print("  - document_templates")
    
    print("\nPhase 3: Enhanced Chat System")
    print("  - chat_channels")
    print("  - channel_members")
    print("  - chat_messages")
    print("  - message_reactions")
    print("  - chat_files")
    print("  - pinned_messages")
    
    print("\nPhase 4: Goals & Dashboards")
    print("  - goals")
    print("  - key_results")
    print("  - goal_updates")
    print("  - dashboards")
    print("  - dashboard_widgets")
    print("  - milestones")
    
    print("\nPhase 5: Time Tracking Dashboard")
    print("  - time_entries_enhanced")
    print("  - time_reports")
    print("  - productivity_metrics")
    print("  - work_breaks")
    print("  - time_goals")
    
    print("\n" + "=" * 60)
    print(f"Total: ~{40} new tables created!")
    print("=" * 60)
    print("\n🎉 Your AI Meeting Assistant is now a full productivity platform!")
    print("\nNext steps:")
    print("  1. Restart the backend server")
    print("  2. Access new features through the dashboard")
    print("  3. Explore Tasks, Docs, Chat, Goals, and Time Tracking!")


if __name__ == "__main__":
    create_tables()


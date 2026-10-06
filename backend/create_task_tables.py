"""
Database migration script to create task management tables
Run this once to set up the LensAI-inspired task system
Usage: python create_task_tables.py
"""
from sqlalchemy import create_engine
from app.database import Base, SQLALCHEMY_DATABASE_URL
# Import existing models first so Base knows about meetings table
from app import models
from app.models_tasks import (
    Task, TaskList, TaskFolder, Workspace, WorkspaceMember,
    TaskComment, TaskAttachment, TaskChecklist, ChecklistItem,
    TaskDependency, TimeEntry
)

def create_tables():
    """Create all task-related tables"""
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    
    print("Creating task management tables...")
    
    # This will create all tables defined in models_tasks.py
    Base.metadata.create_all(bind=engine)
    
    print("✓ Task tables created successfully!")
    print("\nCreated tables:")
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
    print("\nYou can now start creating tasks!")

if __name__ == "__main__":
    create_tables()


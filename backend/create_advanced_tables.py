"""
Database Migration Script - Advanced Features
Creates tables for Kanban boards, Pomodoro timer, Templates, and Automation
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine, Base
from app import models  # Base models
from app.models_tasks import *  # Task models
from app.models_docs import *  # Document models
from app.models_chat import *  # Chat models
from app.models_goals import *  # Goal models
from app.models_time import *  # Time tracking models

# Import new advanced models
from app.models_kanban import *
from app.models_pomodoro import *
from app.models_templates import *
from app.models_automation import *


def create_all_advanced_tables():
    """Create all advanced feature tables"""
    print("🚀 Creating advanced feature tables...")
    print("=" * 60)
    
    # Get all tables using Inspector
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables_before = set(inspector.get_table_names())
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Get new tables
    inspector = inspect(engine)
    tables_after = set(inspector.get_table_names())
    new_tables = tables_after - tables_before
    
    print(f"\n✅ Database migration completed!")
    print(f"\n📊 Summary:")
    print(f"   - Total tables in database: {len(tables_after)}")
    
    if new_tables:
        print(f"   - New tables created: {len(new_tables)}")
        print(f"\n📝 New tables:")
        for table in sorted(new_tables):
            print(f"   ✓ {table}")
    else:
        print(f"   - No new tables created (all exist)")
    
    # List advanced feature tables
    advanced_tables = [
        # Kanban
        'kanban_boards',
        'kanban_columns',
        'kanban_cards',
        'kanban_swimlanes',
        'board_views',
        
        # Pomodoro
        'pomodoro_settings',
        'pomodoro_sessions',
        'pomodoro_idle_periods',
        'pomodoro_statistics',
        'pomodoro_streaks',
        
        # Templates
        'task_templates',
        'recurring_task_rules',
        'generated_tasks',
        'template_categories',
        'template_usage_logs',
        
        # Automation
        'automation_workflows',
        'workflow_actions',
        'workflow_executions',
        'action_execution_results',
        'integration_mappings'
    ]
    
    print(f"\n🎯 Advanced features enabled:")
    existing_advanced = [t for t in advanced_tables if t in tables_after]
    print(f"   - Kanban Boards: {sum(1 for t in existing_advanced if 'kanban' in t or 'board' in t)} tables")
    print(f"   - Pomodoro Timer: {sum(1 for t in existing_advanced if 'pomodoro' in t)} tables")
    print(f"   - Templates & Recurring: {sum(1 for t in existing_advanced if 'template' in t or 'recurring' in t or 'generated' in t)} tables")
    print(f"   - Automation: {sum(1 for t in existing_advanced if 'workflow' in t or 'automation' in t or 'integration' in t)} tables")
    
    print("\n" + "=" * 60)
    print("✨ Advanced features are ready to use!")
    print("\nAvailable endpoints:")
    print("   📋 /kanban/*         - Kanban board management")
    print("   🍅 /pomodoro/*       - Pomodoro timer & statistics")
    print("   📝 /templates/*      - Task templates & recurring tasks")
    print("   ⚡ /automation/*     - Automation workflows")
    print("   📊 /analytics/*      - Unified analytics dashboard")
    print("\nRestart your backend server to apply changes.")


if __name__ == "__main__":
    try:
        create_all_advanced_tables()
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

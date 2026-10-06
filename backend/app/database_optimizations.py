"""Database optimization utilities and index creation.

Run this script to add performance indexes to the database.
"""

from sqlalchemy import text
from .database import engine
import logging

logger = logging.getLogger("lensai_bot.db_optimization")


# SQL statements to create indexes
OPTIMIZATION_QUERIES = [
    # ─── Meeting indexes ───
    """
    CREATE INDEX IF NOT EXISTS idx_meetings_user_id 
    ON meetings(user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meetings_status 
    ON meetings(status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meetings_user_status 
    ON meetings(user_id, status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meetings_created_at 
    ON meetings(created_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meetings_user_created 
    ON meetings(user_id, created_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meetings_updated_at 
    ON meetings(updated_at DESC);
    """,
    
    # ─── Transcript indexes ───
    """
    CREATE INDEX IF NOT EXISTS idx_transcript_meeting_id 
    ON transcript_segments(meeting_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_transcript_meeting_time 
    ON transcript_segments(meeting_id, start_time);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_transcript_speaker 
    ON transcript_segments(meeting_id, speaker);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_transcript_source 
    ON transcript_segments(source);
    """,
    
    # ─── Summary indexes ───
    """
    CREATE INDEX IF NOT EXISTS idx_summary_meeting_id 
    ON summaries(meeting_id);
    """,
    
    # ─── Decision indexes ───
    """
    CREATE INDEX IF NOT EXISTS idx_decisions_meeting_id 
    ON decisions(meeting_id);
    """,
    
    # ─── Action item indexes ───
    """
    CREATE INDEX IF NOT EXISTS idx_action_items_meeting_id 
    ON action_items(meeting_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_action_items_owner 
    ON action_items(owner);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_action_items_completed 
    ON action_items(is_completed);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_action_items_user_pending 
    ON action_items(meeting_id, is_completed) 
    WHERE is_completed = false;
    """,
    
    # ─── Participant indexes ───
    """
    CREATE INDEX IF NOT EXISTS idx_participants_meeting_id 
    ON participants(meeting_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_participants_name 
    ON participants(name);
    """,
    
    # ─── Meeting event indexes ───
    """
    CREATE INDEX IF NOT EXISTS idx_meeting_events_meeting_id 
    ON meeting_events(meeting_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_meeting_events_created 
    ON meeting_events(meeting_id, created_at DESC);
    """,
    
    # ─── User indexes ───
    """
    CREATE INDEX IF NOT EXISTS idx_users_email 
    ON users(email);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_users_created 
    ON users(created_at DESC);
    """,
    
    # ─── Full-text search indexes (PostgreSQL specific) ───
    """
    CREATE INDEX IF NOT EXISTS idx_transcript_text_search 
    ON transcript_segments 
    USING gin(to_tsvector('english', text));
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_summary_text_search 
    ON summaries 
    USING gin(to_tsvector('english', executive_summary || ' ' || COALESCE(key_points, '')));
    """,
]


# Optimization settings for PostgreSQL
POSTGRES_OPTIMIZATIONS = [
    # Enable parallel query execution
    "SET max_parallel_workers_per_gather = 4;",
    
    # Increase work memory for complex queries
    "SET work_mem = '64MB';",
    
    # Optimize for read-heavy workload
    "SET random_page_cost = 1.1;",
    
    # Enable JIT compilation (PostgreSQL 11+)
    "SET jit = on;",
]


def create_indexes():
    """Create all performance indexes."""
    logger.info("Creating database indexes...")
    
    with engine.connect() as conn:
        for i, query in enumerate(OPTIMIZATION_QUERIES, 1):
            try:
                conn.execute(text(query))
                conn.commit()
                logger.info(f"✓ Index {i}/{len(OPTIMIZATION_QUERIES)} created")
            except Exception as e:
                logger.warning(f"✗ Index {i} failed: {e}")
                conn.rollback()
    
    logger.info("✓ All indexes created successfully")


def apply_postgres_optimizations():
    """Apply PostgreSQL-specific optimizations."""
    logger.info("Applying PostgreSQL optimizations...")
    
    with engine.connect() as conn:
        for setting in POSTGRES_OPTIMIZATIONS:
            try:
                conn.execute(text(setting))
                logger.info(f"✓ Applied: {setting}")
            except Exception as e:
                logger.warning(f"✗ Failed: {setting} - {e}")


def analyze_tables():
    """Run ANALYZE on all tables to update statistics."""
    logger.info("Analyzing tables...")
    
    tables = [
        "meetings",
        "transcript_segments",
        "summaries",
        "decisions",
        "action_items",
        "participants",
        "meeting_events",
        "users",
    ]
    
    with engine.connect() as conn:
        for table in tables:
            try:
                conn.execute(text(f"ANALYZE {table};"))
                conn.commit()
                logger.info(f"✓ Analyzed {table}")
            except Exception as e:
                logger.warning(f"✗ Failed to analyze {table}: {e}")


def vacuum_tables():
    """Run VACUUM on all tables to reclaim space."""
    logger.info("Vacuuming tables...")
    
    tables = [
        "meetings",
        "transcript_segments",
        "summaries",
        "decisions",
        "action_items",
        "participants",
        "meeting_events",
        "users",
    ]
    
    with engine.connect() as conn:
        # Must be outside transaction for VACUUM
        conn.execution_options(isolation_level="AUTOCOMMIT")
        
        for table in tables:
            try:
                conn.execute(text(f"VACUUM ANALYZE {table};"))
                logger.info(f"✓ Vacuumed {table}")
            except Exception as e:
                logger.warning(f"✗ Failed to vacuum {table}: {e}")


def get_table_sizes():
    """Get size information for all tables."""
    query = """
    SELECT 
        schemaname as schema,
        tablename as table,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
        pg_total_relation_size(schemaname||'.'||tablename) as bytes
    FROM pg_tables
    WHERE schemaname = 'public'
    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query))
        rows = result.fetchall()
        
        print("\n" + "="*60)
        print("DATABASE TABLE SIZES")
        print("="*60)
        for row in rows:
            print(f"{row[1]:30s} {row[2]:>15s}")
        print("="*60 + "\n")


def get_index_usage():
    """Get index usage statistics."""
    query = """
    SELECT
        schemaname,
        tablename,
        indexname,
        idx_scan as scans,
        pg_size_pretty(pg_relation_size(indexrelid)) as size
    FROM pg_stat_user_indexes
    WHERE schemaname = 'public'
    ORDER BY idx_scan DESC;
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query))
        rows = result.fetchall()
        
        print("\n" + "="*80)
        print("INDEX USAGE STATISTICS")
        print("="*80)
        print(f"{'Table':25s} {'Index':30s} {'Scans':>10s} {'Size':>10s}")
        print("-"*80)
        for row in rows:
            print(f"{row[1]:25s} {row[2]:30s} {row[3]:10d} {row[4]:>10s}")
        print("="*80 + "\n")


def get_slow_queries():
    """Get slowest queries from pg_stat_statements (if extension is enabled)."""
    query = """
    SELECT
        substring(query, 1, 100) as query_preview,
        calls,
        total_exec_time::numeric(10,2) as total_time_ms,
        mean_exec_time::numeric(10,2) as mean_time_ms,
        max_exec_time::numeric(10,2) as max_time_ms
    FROM pg_stat_statements
    WHERE query NOT LIKE '%pg_stat_statements%'
    ORDER BY mean_exec_time DESC
    LIMIT 10;
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            
            print("\n" + "="*100)
            print("SLOWEST QUERIES (Top 10)")
            print("="*100)
            print(f"{'Query Preview':60s} {'Calls':>8s} {'Avg (ms)':>10s} {'Max (ms)':>10s}")
            print("-"*100)
            for row in rows:
                print(f"{row[0]:60s} {row[1]:8d} {row[3]:10.2f} {row[4]:10.2f}")
            print("="*100 + "\n")
    except Exception as e:
        logger.info("pg_stat_statements not enabled. Enable with: CREATE EXTENSION pg_stat_statements;")


def optimize_database():
    """Run full database optimization suite."""
    logger.info("="*60)
    logger.info("DATABASE OPTIMIZATION STARTED")
    logger.info("="*60)
    
    # Create indexes
    create_indexes()
    
    # Apply PostgreSQL settings
    apply_postgres_optimizations()
    
    # Update statistics
    analyze_tables()
    
    # Reclaim space
    # vacuum_tables()  # Uncomment for full vacuum (takes longer)
    
    # Show statistics
    get_table_sizes()
    get_index_usage()
    get_slow_queries()
    
    logger.info("="*60)
    logger.info("DATABASE OPTIMIZATION COMPLETED")
    logger.info("="*60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    optimize_database()

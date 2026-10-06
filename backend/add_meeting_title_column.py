"""
Add meeting_title column to meetings table
Run this once: python add_meeting_title_column.py
"""
from sqlalchemy import create_engine, text
import os

# Use the same database URL as the app
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db")

def add_meeting_title_column():
    engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://"))
    
    with engine.connect() as conn:
        try:
            # Check if column already exists
            if "sqlite" in DATABASE_URL:
                result = conn.execute(text("PRAGMA table_info(meetings)"))
                columns = [row[1] for row in result]
                if "meeting_title" not in columns:
                    conn.execute(text("ALTER TABLE meetings ADD COLUMN meeting_title VARCHAR"))
                    conn.commit()
                    print("✓ Added meeting_title column to meetings table")
                else:
                    print("✓ meeting_title column already exists")
            else:
                # PostgreSQL
                conn.execute(text("""
                    ALTER TABLE meetings 
                    ADD COLUMN IF NOT EXISTS meeting_title VARCHAR
                """))
                conn.commit()
                print("✓ Added meeting_title column to meetings table")
        except Exception as e:
            print(f"Note: {e}")
            print("This is normal if the column already exists or if there's a minor issue.")

if __name__ == "__main__":
    print("Adding meeting_title column to meetings table...")
    add_meeting_title_column()
    print("Done!")

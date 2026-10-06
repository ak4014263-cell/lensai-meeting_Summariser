"""Minimal, dependency-free schema reconciliation for the SQLite dev database.

`Base.metadata.create_all()` creates missing *tables* but never adds missing
*columns* to tables that already exist. Since this project ships a checked-in
`sql_app.db`, new model fields would silently break queries with
"no such column". This module diffs the SQLAlchemy models against the live
schema and issues `ALTER TABLE ... ADD COLUMN` for anything missing.

It only ever adds columns. It never drops or rewrites data. For anything more
involved (type changes, constraints) switch to Alembic.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .database import Base


def _sql_type(column) -> str:
    try:
        return column.type.compile(dialect=None) or "TEXT"
    except Exception:
        # SQLite is dynamically typed, so TEXT is always a safe fallback.
        return "TEXT"


def sync_schema(engine: Engine) -> list[str]:
    """Add any model columns that are missing from existing tables.

    Returns the list of applied DDL statements (empty when already in sync).
    """
    applied: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all() handles brand new tables

            live_columns = {c["name"] for c in inspector.get_columns(table.name)}

            for column in table.columns:
                if column.name in live_columns:
                    continue
                if column.primary_key:
                    # Can't add a primary key to an existing SQLite table.
                    continue

                col_type = _sql_type(column)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'

                # A NOT NULL column needs a default to backfill existing rows.
                if not column.nullable and column.default is None:
                    ddl += " DEFAULT NULL"

                conn.execute(text(ddl))
                applied.append(ddl)

    if applied:
        print(f"[db] Applied {len(applied)} schema migration(s):")
        for ddl in applied:
            print(f"[db]   {ddl}")

    return applied

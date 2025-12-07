#!/usr/bin/env python3
"""
Database Migration: Add review_state column to segments table.

This migration adds the review_state column to the segments table and populates
it based on existing is_reviewed and is_rejected flags.

Migration logic:
    - is_rejected = 1 → review_state = 'rejected'
    - is_reviewed = 1 → review_state = 'reviewed'
    - Otherwise → review_state = 'pending'

Usage:
    python migrate_add_review_state.py
    python migrate_add_review_state.py --db path/to/database.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.db import DEFAULT_DB_PATH


def check_column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def migrate_add_review_state(db_path: Path) -> None:
    """Add review_state column and populate from existing flags."""
    print(f"Starting migration on database: {db_path}")
    
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Check if column already exists
        if check_column_exists(conn, 'segments', 'review_state'):
            print("✓ Column 'review_state' already exists. Updating values...")
        else:
            print("Adding 'review_state' column to segments table...")
            conn.execute("""
                ALTER TABLE segments 
                ADD COLUMN review_state TEXT DEFAULT 'pending'
                CHECK (review_state IN ('pending', 'reviewed', 'approved', 'rejected'))
            """)
            conn.commit()
            print("✓ Column added successfully")
        
        # Populate review_state based on existing flags
        print("Populating review_state values...")
        
        # Set rejected segments
        cursor = conn.execute("""
            UPDATE segments 
            SET review_state = 'rejected' 
            WHERE is_rejected = 1
        """)
        rejected_count = cursor.rowcount
        print(f"  - Set {rejected_count} segments to 'rejected'")
        
        # Set reviewed segments
        cursor = conn.execute("""
            UPDATE segments 
            SET review_state = 'reviewed' 
            WHERE is_rejected = 0 AND is_reviewed = 1
        """)
        reviewed_count = cursor.rowcount
        print(f"  - Set {reviewed_count} segments to 'reviewed'")
        
        # Set pending segments
        cursor = conn.execute("""
            UPDATE segments 
            SET review_state = 'pending' 
            WHERE is_rejected = 0 AND is_reviewed = 0
        """)
        pending_count = cursor.rowcount
        print(f"  - Set {pending_count} segments to 'pending'")
        
        conn.commit()
        
        # Create index if not exists
        print("Creating index on review_state...")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_segments_review_state ON segments(review_state)")
        conn.commit()
        print("✓ Index created")
        
        # Verify migration
        cursor = conn.execute("""
            SELECT review_state, COUNT(*) as count 
            FROM segments 
            GROUP BY review_state
        """)
        
        print("\n📊 Migration Summary:")
        print("-" * 40)
        for row in cursor.fetchall():
            state = row['review_state'] or 'NULL'
            count = row['count']
            print(f"  {state:12s}: {count:6d} segments")
        print("-" * 40)
        
        total = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        print(f"  {'TOTAL':12s}: {total:6d} segments\n")
        
        print("✅ Migration completed successfully!")
        
    except sqlite3.Error as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Add review_state column to segments table")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})"
    )
    args = parser.parse_args()
    
    migrate_add_review_state(args.db)


if __name__ == "__main__":
    main()

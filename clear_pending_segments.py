"""Clear segments from chunks that are still pending (incomplete processing)."""
from src.db import get_db

with get_db() as db:
    # Delete segments for pending chunks
    result = db.execute(
        """
        DELETE FROM segments 
        WHERE video_id = ? 
        AND chunk_id IN (
            SELECT chunk_id FROM chunks WHERE processing_state = 'pending'
        )
        """,
        ('gBhbKX0pT_0',)
    )
    
    deleted_count = result.rowcount
    print(f"✅ Cleared {deleted_count} leftover segments from pending chunks")

"""Check segment distribution across chunks."""
from src.db import get_db

with get_db() as db:
    segs = db.execute(
        'SELECT chunk_id, COUNT(*) FROM segments WHERE video_id = ? GROUP BY chunk_id',
        ('gBhbKX0pT_0',)
    ).fetchall()
    
    print("Segment distribution:")
    for chunk_id, count in segs:
        print(f"  Chunk ID {chunk_id}: {count} segments")

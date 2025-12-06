"""Quick script to check database state for debugging."""
from src.db import get_db

with get_db() as db:
    # Check segments
    seg_count = db.execute(
        'SELECT COUNT(*) FROM segments WHERE video_id = ?',
        ('gBhbKX0pT_0',)
    ).fetchone()[0]
    
    # Check chunks
    chunks = db.execute(
        'SELECT chunk_id, chunk_index, processing_state FROM chunks WHERE video_id = ?',
        ('gBhbKX0pT_0',)
    ).fetchall()
    
    print(f"Segments for gBhbKX0pT_0: {seg_count}")
    print(f"\nChunks ({len(chunks)}):")
    for chunk_id, chunk_idx, state in chunks:
        print(f"  Chunk {chunk_idx} (ID={chunk_id}): {state}")

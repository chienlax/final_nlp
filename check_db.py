import psycopg2

conn = psycopg2.connect('postgresql://postgres:postgres@localhost:5432/speech_translation_db')
cur = conn.cursor()

# Check for approved chunks
cur.execute("SELECT status, COUNT(*) FROM chunks GROUP BY status")
print("Chunks by status:", cur.fetchall())

# Check for verified segments  
cur.execute("SELECT is_verified, is_rejected, COUNT(*) FROM segments GROUP BY is_verified, is_rejected")
print("Segments by verified/rejected:", cur.fetchall())

conn.close()

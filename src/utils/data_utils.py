"""
Data utilities for the NLP pipeline.

Provides database connectivity (PostgreSQL) and helper functions
for data processing in the speech translation pipeline.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any

import psycopg2
from psycopg2.extras import Json


def get_pg_connection() -> psycopg2.extensions.connection:
    """
    Establishes a connection to the PostgreSQL database.

    Reads connection string from DATABASE_URL environment variable.
    Falls back to default Docker Compose credentials if not set.

    Returns:
        psycopg2 connection object.

    Raises:
        ConnectionError: If database connection fails.
    """
    database_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://admin:secret_password@localhost:5432/data_factory'
    )

    try:
        conn = psycopg2.connect(database_url)
        return conn
    except psycopg2.Error as e:
        raise ConnectionError(f"Error connecting to PostgreSQL: {e}")


def insert_raw_sample(
    file_path: str,
    source_metadata: Dict[str, Any],
    acoustic_meta: Dict[str, Any],
    linguistic_meta: Optional[Dict[str, Any]] = None,
    transcript_raw: Optional[str] = None
) -> str:
    """
    Insert a new raw sample into the dataset_ledger table.

    Args:
        file_path: Path to the audio file (relative to project root).
        source_metadata: JSONB data for source_metadata column.
            Expected keys: url, channel_id, upload_date, subtitle_type
        acoustic_meta: JSONB data for acoustic_meta column.
            Expected keys: sample_rate, duration, channels, format
        linguistic_meta: Optional JSONB data for linguistic_meta column.
            Expected keys: cs_ratio, language_tags
        transcript_raw: Optional raw transcript text.

    Returns:
        The UUID of the inserted sample.

    Raises:
        Exception: If insert fails.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dataset_ledger (
                    file_path,
                    source_metadata,
                    acoustic_meta,
                    linguistic_meta,
                    transcript_raw,
                    processing_state
                ) VALUES (%s, %s, %s, %s, %s, 'RAW')
                RETURNING sample_id
                """,
                (
                    file_path,
                    Json(source_metadata),
                    Json(acoustic_meta),
                    Json(linguistic_meta) if linguistic_meta else None,
                    transcript_raw
                )
            )
            sample_id = cur.fetchone()[0]
            conn.commit()
            return str(sample_id)
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Failed to insert sample: {e}")
    finally:
        conn.close()


def sample_exists(file_path: str) -> bool:
    """
    Check if a sample with the given file path already exists.

    Args:
        file_path: Path to check in the database.

    Returns:
        True if sample exists, False otherwise.
    """
    conn = get_pg_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM dataset_ledger WHERE file_path = %s LIMIT 1",
                (file_path,)
            )
            return cur.fetchone() is not None
    finally:
        conn.close()

def calculate_cs_ratio(text: str) -> float:
    """
    Crudely estimates the ratio of English words in a Vietnamese-English sentence.
    
    Logic:
    - Tokenizes text by whitespace.
    - Identifies Vietnamese words by the presence of specific Vietnamese characters (diacritics).
    - Treats everything else as potentially English.
    
    Args:
        text (str): The code-switched input text.
        
    Returns:
        float: Percentage of English words (0.0 to 1.0).
    """
    if not text or not text.strip():
        return 0.0

    # Regex for Vietnamese specific characters (including lower and upper case)
    # Matches: àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ
    vn_chars_pattern = re.compile(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', re.IGNORECASE)
    
    words = text.strip().split()
    total_words = len(words)
    
    if total_words == 0:
        return 0.0
        
    english_like_count = 0
    
    for word in words:
        # Remove punctuation for cleaner check
        clean_word = re.sub(r'[^\w\s]', '', word)
        
        # Skip if the word became empty after removing punctuation (e.g. just a comma)
        if not clean_word:
            total_words -= 1
            continue
            
        # If it contains Vietnamese characters, it's Vietnamese.
        # If it doesn't, we count it as English (per crude heuristic).
        if not vn_chars_pattern.search(clean_word):
            english_like_count += 1
            
    if total_words == 0:
        return 0.0
    
    return round(english_like_count / total_words, 2)

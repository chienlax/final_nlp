"""
Text processing utilities for the NLP pipeline.

Provides text normalization, teencode replacement, and code-switching
chunk extraction for the text-first pipeline.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Default teencode dictionary path
DEFAULT_TEENCODE_PATH = Path("data/teencode.txt")

# Vietnamese particles for CS detection
VN_PARTICLES = {
    'và', 'là', 'của', 'những', 'các', 'này', 'đó', 'kia', 'ấy',
    'thì', 'mà', 'nên', 'vì', 'nếu', 'khi', 'để', 'cho', 'với',
    'được', 'bị', 'có', 'không', 'cũng', 'đã', 'đang', 'sẽ', 'vẫn',
    'rất', 'quá', 'lắm', 'nhất', 'hơn', 'như', 'bằng', 'về', 'ra',
    'lên', 'xuống', 'vào', 'từ', 'đến', 'theo', 'qua', 'trong', 'ngoài',
    'trên', 'dưới', 'giữa', 'sau', 'trước', 'bên', 'cạnh', 'gần', 'xa',
    'tôi', 'mình', 'bạn', 'anh', 'chị', 'em', 'họ', 'chúng', 'ta',
    'ai', 'gì', 'nào', 'sao', 'bao', 'đâu', 'ở', 'nhé', 'nha', 'ạ',
}

# English stop words for CS detection
EN_STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'so', 'is', 'are', 'was',
    'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does',
    'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must',
    'can', 'to', 'of', 'in', 'on', 'at', 'by', 'for', 'with', 'about',
    'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above',
    'below', 'between', 'under', 'again', 'further', 'then', 'once',
    'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each',
    'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
    'only', 'own', 'same', 'than', 'too', 'very', 'just', 'also',
    'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her',
    'us', 'them', 'my', 'your', 'his', 'its', 'our', 'their',
    'this', 'that', 'these', 'those', 'what', 'which', 'who', 'whom',
}


def load_teencode_dict(file_path: Optional[Path] = None) -> Dict[str, str]:
    """
    Load teencode dictionary from a file.

    File format: one mapping per line, tab-separated (teencode<TAB>replacement).

    Args:
        file_path: Path to teencode dictionary file.

    Returns:
        Dictionary mapping teencode to replacement text.
    """
    if file_path is None:
        file_path = DEFAULT_TEENCODE_PATH

    teencode_dict: Dict[str, str] = {}

    if not file_path.exists():
        print(f"Warning: Teencode file not found at {file_path}")
        return teencode_dict

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                parts = line.split('\t')
                if len(parts) >= 2:
                    teencode_dict[parts[0].strip()] = parts[1].strip()

    except Exception as e:
        print(f"Error reading teencode file: {e}")

    return teencode_dict


def normalize_text(
    text: str,
    teencode_dict: Optional[Dict[str, str]] = None,
    lowercase: bool = True,
    remove_urls: bool = True,
    remove_emojis: bool = True
) -> str:
    """
    Normalize Vietnamese text by applying various cleaning operations.

    Args:
        text: Input text to normalize.
        teencode_dict: Dictionary for teencode replacement.
        lowercase: Whether to convert to lowercase.
        remove_urls: Whether to remove URLs.
        remove_emojis: Whether to remove emojis.

    Returns:
        Normalized text.
    """
    if not text:
        return ""

    # Convert to lowercase if requested
    if lowercase:
        text = text.lower()

    # Remove URLs
    if remove_urls:
        url_pattern = r'https?://\S+|www\.\S+'
        text = re.sub(url_pattern, '', text)

    # Remove emojis
    if remove_emojis:
        emoji_pattern = re.compile(
            "["
            u"\U0001F600-\U0001F64F"  # Emoticons
            u"\U0001F300-\U0001F5FF"  # Symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # Transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # Flags
            u"\U00002702-\U000027B0"  # Dingbats
            u"\U000024C2-\U0001F251"  # Enclosed characters
            u"\U0001f926-\U0001f937"  # Supplemental symbols
            u'\U00010000-\U0010ffff'  # Supplementary planes
            u"\u200d"  # Zero width joiner
            u"\u2640-\u2642"  # Gender symbols
            u"\u2600-\u2B55"  # Misc symbols
            u"\u23cf"  # Eject symbol
            u"\u23e9"  # Fast forward
            u"\u231a"  # Watch
            u"\u3030"  # Wavy dash
            u"\ufe0f"  # Variation selector
            "]+",
            flags=re.UNICODE
        )
        text = re.sub(emoji_pattern, ' ', text)

    # Apply teencode replacements
    if teencode_dict:
        for key, value in teencode_dict.items():
            # Use word boundaries for alphanumeric keys
            if key.isalnum():
                pattern = r'\b' + re.escape(key) + r'\b'
            else:
                pattern = re.escape(key)
            text = re.sub(pattern, value, text, flags=re.IGNORECASE)

    # Normalize whitespace
    text = ' '.join(text.split())

    return text


def contains_code_switching(text: str) -> bool:
    """
    Check if a text contains code-switching (mix of Vietnamese and English).

    Uses the "Intersection Rule": text must contain at least one Vietnamese
    particle AND at least one English stop word.

    Args:
        text: Input text to check.

    Returns:
        True if text contains code-switching, False otherwise.
    """
    if not text:
        return False

    words = set(text.lower().split())

    has_vn_particle = bool(words & VN_PARTICLES)
    has_en_stop_word = bool(words & EN_STOP_WORDS)

    return has_vn_particle and has_en_stop_word


def extract_cs_chunks(
    text: str,
    context_sentences: int = 1,
    min_cs_ratio: float = 0.1
) -> List[Dict[str, Any]]:
    """
    Extract code-switching chunks from text with surrounding context.

    Each chunk includes the CS sentence and neighboring sentences for context.

    Args:
        text: Input text to process.
        context_sentences: Number of sentences to include before/after CS sentence.
        min_cs_ratio: Minimum CS ratio to include a sentence.

    Returns:
        List of chunk dictionaries with keys:
            - 'cs_sentence': The code-switched sentence
            - 'context_before': Sentences before
            - 'context_after': Sentences after
            - 'full_chunk': Complete chunk text
            - 'cs_ratio': Estimated CS ratio
    """
    if not text:
        return []

    # Split into sentences (handle Vietnamese punctuation)
    sentence_pattern = r'(?<=[.!?])\s+'
    sentences = re.split(sentence_pattern, text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: List[Dict[str, Any]] = []

    for i, sentence in enumerate(sentences):
        if not contains_code_switching(sentence):
            continue

        # Calculate CS ratio for this sentence
        cs_ratio = _estimate_cs_ratio(sentence)
        if cs_ratio < min_cs_ratio:
            continue

        # Get context sentences
        start_idx = max(0, i - context_sentences)
        end_idx = min(len(sentences), i + context_sentences + 1)

        context_before = sentences[start_idx:i]
        context_after = sentences[i + 1:end_idx]

        # Build full chunk
        chunk_sentences = context_before + [sentence] + context_after
        full_chunk = ' '.join(chunk_sentences)

        chunks.append({
            'cs_sentence': sentence,
            'context_before': context_before,
            'context_after': context_after,
            'full_chunk': full_chunk,
            'cs_ratio': cs_ratio,
            'sentence_index': i,
        })

    return chunks


def _estimate_cs_ratio(text: str) -> float:
    """
    Estimate the code-switching ratio of a text.

    Args:
        text: Input text.

    Returns:
        Ratio of English-like words (0.0 to 1.0).
    """
    if not text:
        return 0.0

    # Regex for Vietnamese diacritics
    vn_chars_pattern = re.compile(
        r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩ'
        r'òóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]',
        re.IGNORECASE
    )

    words = text.strip().split()
    total_words = len(words)

    if total_words == 0:
        return 0.0

    english_like_count = 0

    for word in words:
        clean_word = re.sub(r'[^\w\s]', '', word)
        if not clean_word:
            total_words -= 1
            continue

        if not vn_chars_pattern.search(clean_word):
            english_like_count += 1

    if total_words == 0:
        return 0.0

    return round(english_like_count / total_words, 4)


def split_into_sentences(text: str) -> List[str]:
    """
    Split text into sentences.

    Handles Vietnamese and English punctuation.

    Args:
        text: Input text.

    Returns:
        List of sentences.
    """
    if not text:
        return []

    # Split on sentence-ending punctuation
    pattern = r'(?<=[.!?])\s+'
    sentences = re.split(pattern, text.strip())

    return [s.strip() for s in sentences if s.strip()]


def merge_short_sentences(
    sentences: List[str],
    min_words: int = 5
) -> List[str]:
    """
    Merge very short sentences with adjacent ones.

    Args:
        sentences: List of sentences.
        min_words: Minimum words for a sentence to stand alone.

    Returns:
        List of merged sentences.
    """
    if not sentences:
        return []

    merged: List[str] = []
    buffer = ""

    for sentence in sentences:
        word_count = len(sentence.split())

        if buffer:
            # Merge with buffer
            buffer = f"{buffer} {sentence}"
            if word_count >= min_words:
                merged.append(buffer.strip())
                buffer = ""
        elif word_count < min_words:
            # Start buffering
            buffer = sentence
        else:
            merged.append(sentence)

    # Don't forget remaining buffer
    if buffer:
        if merged:
            merged[-1] = f"{merged[-1]} {buffer}".strip()
        else:
            merged.append(buffer.strip())

    return merged


if __name__ == "__main__":
    # Test the module
    test_text = """
    Hôm nay mình sẽ review cái sản phẩm này. 
    It's really amazing và mình rất thích.
    The quality is super good, đáng đồng tiền bát gạo.
    """

    print("Loading teencode dictionary...")
    teencode = load_teencode_dict()
    print(f"Loaded {len(teencode)} teencode mappings.")

    print("\nNormalizing text...")
    normalized = normalize_text(test_text, teencode)
    print(f"Normalized: {normalized}")

    print("\nExtracting CS chunks...")
    chunks = extract_cs_chunks(normalized)
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i + 1}:")
        print(f"  CS sentence: {chunk['cs_sentence']}")
        print(f"  CS ratio: {chunk['cs_ratio']}")
        print(f"  Full chunk: {chunk['full_chunk']}")

"""Session naming — auto-generate human-readable names from first prompts."""

from __future__ import annotations

import re
import unicodedata

# Common stop words to strip from generated names
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "i", "me", "my", "we", "our", "you", "your", "it", "its",
    "this", "that", "these", "those", "what", "which", "who", "how", "why",
    "when", "where", "please", "help", "me", "let", "just", "also",
})

# Max number of words in a generated name
_MAX_WORDS = 4
# Max total length of the slug (chars)
_MAX_SLUG_LEN = 40


def generate_session_name(prompt: str) -> str:
    """
    Derive a short, human-readable slug from the first line of a prompt.

    Examples:
      "Write a Python function to sort a list" -> "python-function-sort-list"
      "Optimize the DMRG run for H2 molecule"  -> "optimize-dmrg-run-h2"
      ""                                         -> "unnamed-session"
    """
    if not prompt or not prompt.strip():
        return "unnamed-session"

    # Take first non-empty line only
    first_line = ""
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break

    if not first_line:
        return "unnamed-session"

    # Normalize unicode -> ASCII approximation
    normalized = unicodedata.normalize("NFKD", first_line)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

    # Lowercase
    lowered = ascii_text.lower()

    # Replace punctuation/special chars with spaces
    cleaned = re.sub(r"[^a-z0-9\s]", " ", lowered)

    # Split into words
    words = cleaned.split()

    # Filter stop words, keep meaningful words
    meaningful = [w for w in words if w and w not in _STOP_WORDS and len(w) > 1]

    # Fallback: if filtering removed everything, use original words (no stop filter)
    if not meaningful:
        meaningful = [w for w in words if w]

    # Take up to _MAX_WORDS words
    chosen = meaningful[:_MAX_WORDS]

    if not chosen:
        return "unnamed-session"

    slug = "-".join(chosen)

    # Truncate to max length at a word boundary
    if len(slug) > _MAX_SLUG_LEN:
        slug = slug[:_MAX_SLUG_LEN].rsplit("-", 1)[0]

    # Final safety: ensure slug is not empty
    return slug if slug else "unnamed-session"

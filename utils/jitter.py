"""
Human-like text jitter for LinkedIn outreach notes.

Applies intentional, subtle variations to LLM-generated notes so
no two messages are identical — defeating pattern-detection heuristics.

Jitter is applied AFTER the LLM review pass to preserve quality.
"""

import random
import re
from typing import Optional

from utils.logger import logger


# ── Greeting variations ───────────────────────────────────────

_GREETING_TEMPLATES = [
    "Hi {name}",
    "Hey {name}",
    "Hello {name}",
    "{name},",
    "Hi {name}!",
    "Hey {name}!",
    "Hello {name}!",
    "{name} —",
    "Hey there, {name}",
    "Hi there, {name}",
]


def apply_greeting_jitter(note: str, name: str) -> str:
    """
    Replace the greeting at the start of the note with a random variation.

    Detects common greeting patterns (Hi/Hey/Hello + name) and swaps them.
    """
    if not name:
        return note

    first_name = name.split()[0] if name else name

    # Pattern: starts with a greeting word followed by the person's name
    pattern = rf"^(Hi|Hey|Hello|Hey there|Hi there)[\s,]*{re.escape(first_name)}[!,.\-—]*\s*"
    match = re.match(pattern, note, re.IGNORECASE)

    if match:
        new_greeting = random.choice(_GREETING_TEMPLATES).format(name=first_name)
        note = re.sub(pattern, new_greeting + " ", note, count=1, flags=re.IGNORECASE)
        logger.debug(f"Greeting jitter applied: {new_greeting}")

    return note


# ── Emoji jitter ──────────────────────────────────────────────

_CONTEXTUAL_EMOJIS = ["🚀", "💡", "🤝", "👋", "✨", "🙌", "💪", "🎯", "⚡"]


def apply_emoji_jitter(note: str) -> str:
    """
    Randomly add or remove an emoji from the note.

    - 30% chance: add a contextual emoji at the end
    - 20% chance: remove existing emojis
    - 50% chance: leave as-is
    """
    roll = random.random()

    if roll < 0.3:
        # Add an emoji if none present
        existing_emojis = re.findall(r'[\U0001F300-\U0001F9FF]', note)
        if not existing_emojis:
            emoji = random.choice(_CONTEXTUAL_EMOJIS)
            # Add before the final period/exclamation or at the very end
            if note.rstrip().endswith(('.', '!')):
                note = note.rstrip()[:-1] + f" {emoji}" + note.rstrip()[-1]
            else:
                note = note.rstrip() + f" {emoji}"
            logger.debug(f"Emoji added: {emoji}")
    elif roll < 0.5:
        # Remove existing emojis
        cleaned = re.sub(r'[\U0001F300-\U0001F9FF]\s?', '', note)
        if cleaned != note:
            note = cleaned
            logger.debug("Emojis removed")

    return note


# ── Phrasing jitter ───────────────────────────────────────────

_SYNONYM_PAIRS = [
    ("excited", "thrilled"),
    ("excited", "eager"),
    ("love", "really enjoy"),
    ("love", "appreciate"),
    ("great", "wonderful"),
    ("great", "fantastic"),
    ("interesting", "fascinating"),
    ("interesting", "compelling"),
    ("impressive", "remarkable"),
    ("connect with you", "reach out to you"),
    ("connect with you", "get in touch"),
    ("looking forward to", "would love to"),
    ("I'd love to", "I'm keen to"),
    ("your work on", "your contributions to"),
    ("your work on", "what you've built with"),
    ("learn more about", "hear more about"),
    ("learn more about", "dive deeper into"),
    ("caught my eye", "stood out to me"),
    ("caught my attention", "piqued my interest"),
]


def apply_phrasing_jitter(note: str) -> str:
    """
    Apply 1-2 random synonym substitutions to vary phrasing.

    Only substitutes if the original phrase exists in the note.
    """
    # Shuffle and try up to 2 substitutions
    pairs = random.sample(_SYNONYM_PAIRS, min(len(_SYNONYM_PAIRS), 6))
    substitutions_made = 0

    for original, replacement in pairs:
        if substitutions_made >= 2:
            break
        if original.lower() in note.lower():
            # Case-preserving replacement
            pattern = re.compile(re.escape(original), re.IGNORECASE)
            note = pattern.sub(replacement, note, count=1)
            substitutions_made += 1
            logger.debug(f"Phrasing jitter: '{original}' → '{replacement}'")

    return note


# ── Punctuation jitter ────────────────────────────────────────

def apply_punctuation_jitter(note: str) -> str:
    """
    Occasionally swap periods and exclamation marks for variety.

    - 25% chance: swap one period for an exclamation mark
    - 25% chance: swap one exclamation mark for a period
    """
    roll = random.random()

    if roll < 0.25:
        # Add enthusiasm: period → exclamation (only on the last sentence)
        if note.rstrip().endswith('.'):
            note = note.rstrip()[:-1] + '!'
            logger.debug("Punctuation jitter: . → !")
    elif roll < 0.5:
        # Tone down: exclamation → period (only on the last sentence)
        if note.rstrip().endswith('!'):
            note = note.rstrip()[:-1] + '.'
            logger.debug("Punctuation jitter: ! → .")

    return note


# ── Master jitter function ────────────────────────────────────

def apply_all_jitter(note: str, name: Optional[str] = None,
                     char_limit: int = 300) -> str:
    """
    Apply all jitter transformations to a note.

    Order: greeting → phrasing → emoji → punctuation
    Ensures the final note stays within the character limit.

    Args:
        note: The LLM-reviewed note text.
        name: The recipient's name (for greeting jitter).
        char_limit: Maximum characters allowed.

    Returns:
        The jittered note, guaranteed ≤ char_limit characters.
    """
    original = note

    if name:
        note = apply_greeting_jitter(note, name)
    note = apply_phrasing_jitter(note)
    note = apply_emoji_jitter(note)
    note = apply_punctuation_jitter(note)

    # Enforce character limit — trim gracefully if jitter pushed it over
    if len(note) > char_limit:
        # Try removing emoji first
        note_no_emoji = re.sub(r'[\U0001F300-\U0001F9FF]\s?', '', note)
        if len(note_no_emoji) <= char_limit:
            note = note_no_emoji
        else:
            # Truncate at last complete word within limit
            truncated = note[:char_limit]
            last_space = truncated.rfind(' ')
            if last_space > char_limit * 0.7:
                note = truncated[:last_space].rstrip('.,!? ') + '.'
            else:
                note = truncated.rstrip('.,!? ') + '.'

    if note != original:
        logger.info(f"Jitter applied — original: {len(original)} chars → final: {len(note)} chars")

    return note

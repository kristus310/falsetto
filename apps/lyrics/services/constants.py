from typing import Final

LYRIC_FILLER_WORDS: Final[frozenset] = frozenset({
    "a", "an", "the", "and", "or", "but", "so", "of", "in", "on",
    "at", "to", "is", "it", "i", "me", "my", "we", "oh", "ah",
    "ooh", "yeah", "ya", "na", "la", "mm", "hmm", "hey", "woah",
    "whoa", "uh", "huh", "da", "de", "do", "re", "up", "no",
})
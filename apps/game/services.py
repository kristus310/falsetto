import random
import re
import unicodedata
import logging
from difflib import SequenceMatcher
from typing import Dict, Any, Tuple, Optional

from django.conf import settings

from apps.lyrics.services.api import LastFMAPI, LRCLIBAPI, LyricsResult
from apps.lyrics.services.api import _LYRIC_FILLER_WORDS

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[^\w\s]")

_DIFFICULTY_MULTIPLIER: Dict[str, float] = {
    "easy": 1.0,
    "medium": 1.5,
    "hard": 2.5,
    "insane": 4.0,
}
_BASE_SCORE = 100
_LIVES_BONUS_PER_LIFE = 10
_STREAK_BONUS_PER_ROUND = 15


def calculate_score(difficulty: str, lives: Dict[str, bool], streak: int) -> int:
    multiplier = _DIFFICULTY_MULTIPLIER.get(difficulty, 1.0)
    lives_remaining = sum(1 for v in lives.values() if v)
    lives_bonus = lives_remaining * _LIVES_BONUS_PER_LIFE
    streak_bonus = streak * _STREAK_BONUS_PER_ROUND
    return int((_BASE_SCORE + lives_bonus + streak_bonus) * multiplier)

def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = _PUNCT_RE.sub("", text)
    return " ".join(text.split())

def is_correct_guess(guess: str, answer: str) -> bool:
    threshold: float = getattr(settings, "GAME_FUZZY_THRESHOLD", 0.85)
    g = _normalise(guess)
    a = _normalise(answer)

    if not g:
        return False
    if g == a:
        return True
    if g in a or a in g:
        return True

    ratio = SequenceMatcher(None, g, a).ratio()
    return ratio >= threshold

class GameService:
    def __init__(self):
        self.lastfm = LastFMAPI()
        self.lrclib = LRCLIBAPI()

    def remove_live(self, lives: Dict[str, bool]) -> Tuple[Dict[str, bool], bool]:
        updated_lives = lives.copy()
        for key in sorted(updated_lives.keys(), reverse=True):
            if updated_lives[key]:
                updated_lives[key] = False
                break

        game_over = not any(updated_lives.values())
        return updated_lives, game_over

    def generate_round_data(self, artist: str, difficulty: str) -> Optional[Dict[str, Any]]:
        try:
            track = self.lastfm.get_track(artist, difficulty)
            if not track or "name" not in track:
                return None

            lyrics_res: Optional[LyricsResult] = self.lrclib.get_lyrics_for_track(track, artist)
            if not lyrics_res or not lyrics_res.has_lyrics():
                return None

            excerpt_lines = lyrics_res.random_excerpt(min_lines=3, max_lines=4)
            if not excerpt_lines:
                return None

            full_excerpt = "\n".join(excerpt_lines)

            words = re.findall(r'\b[a-zA-Z]{4,}\b', full_excerpt)
            valid_words = [
                w for w in words
                if w.lower() not in _LYRIC_FILLER_WORDS
            ]

            if not valid_words:
                return None

            answer_word = random.choice(valid_words)

            pattern = re.compile(r'\b' + re.escape(answer_word) + r'\b', re.IGNORECASE)
            blanked_lyrics = pattern.sub("________", full_excerpt)

            return {
                "artist": lyrics_res.artist_name or artist,
                "song": lyrics_res.track_name or track["name"],
                "lyrics": blanked_lyrics,
                "answer": answer_word.lower()
            }

        except Exception as e:
            logger.error(f"Failed to generate game round data for '{artist}': {e}", exc_info=True)
            return None
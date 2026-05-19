import random
import re
import logging
from typing import Dict, Any, Tuple, Optional

from apps.lyrics.services.api import LastFMAPI, LRCLIBAPI, LyricsResult
from apps.lyrics.services.api import _LYRIC_FILLER_WORDS

logger = logging.getLogger(__name__)

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
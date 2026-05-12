import re
import math
import random
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_DIRTY_RE = re.compile(
    r"\b(live|acoustic|remix|remaster(?:ed)?|demo|instrumental|cover|karaoke"
    r"|version|edit|mix|session|radio|medley|tribute|reprise|interlude|bonus"
    r"|intro|outro|ft|feat)\b|\(.*?\)|\[.*?\]",
    re.IGNORECASE,
)

def _is_clean_track(name: str) -> bool:
    return not _DIRTY_RE.search(name)

class LastFMAPI:
    def __init__(self):
        self.api_key = settings.LASTFM_API_KEY
        self.base_url = settings.LASTFM_BASE_URL
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _get(self, params: dict) -> dict:
        params.update({"api_key": self.api_key, "format": "json"})
        try:
            response = self.session.get(self.base_url, params=params, timeout=(3.05, 10))
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise ValueError(f"Last.fm error {data['error']}: {data.get('message')}")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Last.fm API failure: {e}")
            raise

    def get_top_tracks(self, artist: str, limit: int = 200) -> list[dict]:
        cache_key = f"lastfm:v2:tracks:{artist.lower().replace(' ', '_')}"
        cached = cache.get(cache_key)
        if cached:
            return cached[:limit]

        try:
            data = self._get({
                "method": "artist.gettoptracks",
                "artist": artist,
                "limit": limit,
                "autocorrect": 1,
            })

            raw_tracks = data.get("toptracks", {}).get("track", [])
            if not raw_tracks:
                return []

            # Smart Filtering: Adjust floor based on the artist's own scale
            top_pc = int(raw_tracks[0]["playcount"])
            abs_floor = 100 if top_pc < 50000 else 500

            processed = []
            for t in raw_tracks:
                name = t["name"].strip()
                pc = int(t["playcount"])

                if pc >= abs_floor and _is_clean_track(name):
                    processed.append({
                        "name": name,
                        "playcount": pc,
                        "mbid": t.get("mbid", "")
                    })

            cache.set(cache_key, processed, timeout=86400)
            return processed
        except Exception as e:
            logger.error(f"Error in get_top_tracks: {e}")
            return []

    def get_track(self, artist: str, difficulty: str) -> dict | None:
        tracks = self.get_top_tracks(artist)
        if not tracks:
            return None

        count = len(tracks)

        # SMART SLICING:
        # We divide the artist's CLEAN tracks into percentiles.
        # This scales perfectly for superstars (200 tracks) vs niche (20 tracks).
        if difficulty == "easy":
            # Top 15% of their songs. Weighted heavily by popularity.
            pool = tracks[:max(1, math.ceil(count * 0.15))]
            weights = [t["playcount"] for t in pool]
            return random.choices(pool, weights=weights, k=1)[0]

        elif difficulty == "medium":
            # The "Middle Class" of their discography (15% to 50% mark).
            start = math.ceil(count * 0.15)
            end = math.ceil(count * 0.50)
            pool = tracks[start:end] if start < end else tracks[:5]
            # Light weighting: still favors known songs but allows deepish cuts
            weights = [math.sqrt(t["playcount"]) for t in pool]
            return random.choices(pool, weights=weights, k=1)[0]

        else: # HARD MODE
            # The Deep Cuts (Bottom 50% of the available list).
            # NO WEIGHTING. A song with 500 plays is just as likely as one with 5000.
            start = math.ceil(count * 0.50)
            pool = tracks[start:] if start < count else tracks[-5:]
            return random.choice(pool)
import math
import random
import logging
import requests
from typing import Final, Set
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings
from django.core.cache import cache

from . import helper

logger = logging.getLogger(__name__)

_CACHE_VERSION: Final[str] = "v4"


class LastFMAPI:
    _PAGE_LIMIT: Final[int] = 500
    _MAX_PAGES: Final[int] = 3

    DIFFICULTIES: Final[Set[str]] = {"easy", "medium", "hard"}

    def __init__(self):
        self.api_key = settings.LASTFM_API_KEY
        self.base_url = settings.LASTFM_BASE_URL
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _get(self, params: dict) -> dict:
        params.update({"api_key": self.api_key, "format": "json"})
        try:
            response = self.session.get(
                self.base_url, params=params, timeout=(3.05, 10)
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise ValueError(
                    f"Last.fm error {data['error']}: {data.get('message')}"
                )
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Last.fm API failure: {e}")
            raise

    def _fetch_all_raw_tracks(self, artist: str) -> list[dict]:
        raw: list[dict] = []
        for page in range(1, self._MAX_PAGES + 1):
            data = self._get({
                "method": "artist.gettoptracks",
                "artist": artist,
                "limit": self._PAGE_LIMIT,
                "page": page,
                "autocorrect": 1,
            })
            page_tracks = data.get("toptracks", {}).get("track", [])
            if not page_tracks:
                break
            raw.extend(page_tracks)
            if len(page_tracks) < self._PAGE_LIMIT:
                break
        return raw

    def get_top_tracks(self, artist: str) -> list[dict]:
        safe_artist = artist.lower().replace(" ", "_")
        cache_key = f"lastfm:{_CACHE_VERSION}:tracks:{safe_artist}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw_tracks = self._fetch_all_raw_tracks(artist)
            if not raw_tracks:
                return []

            tracks = self._deduplicate(raw_tracks)
            cache.set(cache_key, tracks, timeout=86_400)
            return tracks

        except Exception as e:
            logger.error(f"Error in get_top_tracks for '{artist}': {e}")
            return []

    def get_track(self, artist: str, difficulty: str) -> dict | None:
        if difficulty not in self.DIFFICULTIES:
            logger.warning(
                f"Unknown difficulty '{difficulty}' -- defaulting to 'hard'."
            )
            difficulty = "hard"

        tracks = self.get_top_tracks(artist)
        if not tracks:
            return None

        count = len(tracks)
        MIN_POOL = 3

        if difficulty == "easy":
            cutoff = max(MIN_POOL, math.ceil(count * 0.20))
            pool = tracks[:cutoff]
            weights = [t["playcount"] for t in pool]
            return random.choices(pool, weights=weights, k=1)[0]

        elif difficulty == "medium":
            start = math.ceil(count * 0.20)
            end = math.ceil(count * 0.55)
            pool = tracks[start:end]
            if len(pool) < MIN_POOL:
                mid = count // 2
                half = MIN_POOL // 2
                pool = tracks[max(0, mid - half): mid + half + 1]
            weights = [math.sqrt(t["playcount"]) for t in pool]
            return random.choices(pool, weights=weights, k=1)[0]

        else:
            start = math.ceil(count * 0.55)
            pool = tracks[start:]
            if len(pool) < MIN_POOL:
                pool = tracks[-MIN_POOL:]
            return random.choice(pool)

    def _deduplicate(self, raw_tracks: list[dict]) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for t in raw_tracks:
            name = t["name"].strip()
            pc = int(t.get("playcount", 0))
            key = helper._normalize_title(name)
            if not key:
                continue
            groups.setdefault(key, []).append({
                "name": name,
                "playcount": pc,
                "mbid": t.get("mbid", ""),
                "is_variant": helper._is_variant(name),
            })

        canonical: list[dict] = []
        for members in groups.values():
            total_pc = sum(m["playcount"] for m in members)
            clean = [m for m in members if not m["is_variant"]]
            best = max(
                clean if clean else members,
                key=lambda m: m["playcount"],
            )
            canonical.append({
                "name": best["name"],
                "playcount": total_pc,
                "mbid": best["mbid"],
            })

        if not canonical:
            return []

        canonical.sort(key=lambda t: t["playcount"], reverse=True)
        top_pc = canonical[0]["playcount"]
        threshold = max(50, top_pc * 0.005)
        filtered = [t for t in canonical if t["playcount"] >= threshold]

        return filtered if len(filtered) >= 3 else canonical[:10]

class LRCLIBAPI:
    pass
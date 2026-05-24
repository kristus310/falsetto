import math
import random
import re
import logging
import requests
from dataclasses import dataclass
from typing import Final, Set
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings
from django.db import transaction

from . import helper

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class LyricsResult:
    track_name: str
    artist_name: str
    album_name: str
    duration: int
    plain_lyrics: str | None
    synced_lyrics: str | None
    instrumental: bool

    def has_lyrics(self) -> bool:
        return bool(self.plain_lyrics) and not self.instrumental

    def _line_score(self, line: str) -> int:
        words = line.lower().split()
        if not words:
            return 0
        meaningful = [w for w in words if re.sub(r"[^\w]", "", w) not in _LYRIC_FILLER_WORDS]
        word_score = len(meaningful) * 3
        char_score = min(len(line), 60) // 5
        return word_score + char_score

    def lyric_lines(self) -> list[str]:
        if not self.plain_lyrics:
            return []
        lines = []
        for ln in self.plain_lyrics.splitlines():
            ln = ln.strip()
            if not ln or _SECTION_HEADER_RE.match(ln):
                continue
            lines.append(ln)
        return lines

    def _split_into_blocks(self) -> list[list[str]]:
        if not self.plain_lyrics:
            return []
        blocks: list[list[str]] = []
        current: list[str] = []
        for ln in self.plain_lyrics.splitlines():
            stripped = ln.strip()
            if not stripped or _SECTION_HEADER_RE.match(stripped):
                if current:
                    blocks.append(current)
                    current = []
            else:
                current.append(stripped)
        if current:
            blocks.append(current)
        return blocks

    def random_excerpt(self, min_lines: int = 3, max_lines: int = 4) -> list[str]:
        blocks = self._split_into_blocks()
        if not blocks:
            return []

        track_norm = re.sub(r"[^\w\s]", "", self.track_name).strip().lower()

        def block_score(block: list[str]) -> float:
            if len(block) < min_lines:
                return 0.0
            line_scores = [self._line_score(ln) for ln in block]
            avg = sum(line_scores) / len(line_scores)
            low = min(line_scores)
            length_bonus = min(len(block), max_lines)
            score = avg + low + length_bonus

            unique_norm = {re.sub(r"[^\w\s]", "", ln).strip().lower() for ln in block}
            repetition_ratio = 1 - (len(unique_norm) / len(block))
            score *= max(0.1, 1 - repetition_ratio * 1.5)

            title_lines = sum(
                1 for ln in block
                if track_norm and track_norm in re.sub(r"[^\w\s]", "", ln).strip().lower()
            )
            title_ratio = title_lines / len(block)
            score *= max(0.1, 1 - title_ratio * 1.5)

            return score

        scored = [(block_score(b), b) for b in blocks]
        scored = [(s, b) for s, b in scored if s > 0]
        if not scored:
            all_lines = [ln for b in blocks for ln in b]
            scored_lines = [(self._line_score(ln), ln) for ln in all_lines]
            scored_lines.sort(key=lambda x: x[0], reverse=True)
            best = [ln for _, ln in scored_lines[:max_lines] if self._line_score(ln) > 2]
            return best if len(best) >= min_lines else []

        scores = [s for s, _ in scored]
        total = sum(scores)
        if total == 0:
            return []
        weights = [s / total for s in scores]
        chosen_block = random.choices([b for _, b in scored], weights=weights, k=1)[0]

        if len(chosen_block) <= max_lines:
            return chosen_block

        span = random.randint(min_lines, max_lines)
        start = random.randint(0, len(chosen_block) - span)
        return chosen_block[start: start + span]


class LRCLIBAPIError(Exception):
    pass


class LastFMAPI:
    _PAGE_LIMIT: Final[int] = 500
    _MAX_PAGES: Final[int] = 3
    DIFFICULTIES: Final[Set[str]] = {"easy", "medium", "hard", "insane"}

    def __init__(self):
        self.api_key = settings.LASTFM_API_KEY
        self.base_url = settings.LASTFM_BASE_URL
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
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

    def get_top_tracks(self, artist_name: str) -> list[dict]:
        from apps.lyrics.models import Artist, Track

        clean_artist_name = artist_name.strip()

        try:
            with transaction.atomic():
                artist_obj = Artist.objects.select_for_update().get(name__iexact=clean_artist_name)
                if artist_obj.is_fully_cached:
                    return [
                        {"name": t.name, "playcount": t.playcount, "mbid": t.mbid}
                        for t in artist_obj.tracks.all()
                    ]
        except Artist.DoesNotExist:
            artist_obj = None

        try:
            raw_tracks = self._fetch_all_raw_tracks(clean_artist_name)
            if not raw_tracks:
                return []

            tracks = self._deduplicate(raw_tracks)

            with transaction.atomic():
                if artist_obj is None:
                    artist_obj, _ = Artist.objects.get_or_create(name=clean_artist_name)
                else:
                    artist_obj = Artist.objects.select_for_update().get(pk=artist_obj.pk)

                Track.objects.filter(artist=artist_obj).delete()

                track_batch = [
                    Track(artist=artist_obj, name=t["name"].strip(), playcount=t["playcount"], mbid=t["mbid"])
                    for t in tracks
                ]
                Track.objects.bulk_create(track_batch)

                artist_obj.is_fully_cached = True
                artist_obj.save()

            return tracks
        except Exception as e:
            logger.error(f"Error handling get_top_tracks for '{clean_artist_name}': {e}")
            if artist_obj:
                fallback_tracks = Track.objects.filter(artist=artist_obj)
                if fallback_tracks.exists():
                    return [
                        {"name": t.name, "playcount": t.playcount, "mbid": t.mbid}
                        for t in fallback_tracks
                    ]
            return []

    def get_track(self, artist: str, difficulty: str) -> dict | None:
        if difficulty not in self.DIFFICULTIES:
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

        elif difficulty == "insane":
            start = math.ceil(count * 0.75)
            pool = tracks[start:]
            if len(pool) < MIN_POOL:
                pool = tracks[-MIN_POOL:]
            return random.choice(pool)

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
            best = max(clean if clean else members, key=lambda m: m["playcount"])
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
    _BASE_URL_DEFAULT: Final[str] = "https://lrclib.net/api"
    _UA_DEFAULT: Final[str] = "Falsetto/1.0 (github.com/kristus310/falsetto)"

    def __init__(self) -> None:
        self.base_url: str = getattr(settings, "LRCLIB_BASE_URL", self._BASE_URL_DEFAULT).rstrip("/")
        user_agent: str = getattr(settings, "LRCLIB_USER_AGENT", self._UA_DEFAULT)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _get(self, endpoint: str, params: dict | None = None) -> dict | list:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url, params=params or {}, timeout=(3.05, 10))
        except requests.exceptions.RequestException as exc:
            logger.error("LRCLIB network error [%s]: %s", url, exc)
            raise

        if response.status_code == 404:
            raise LRCLIBAPIError("not_found")
        if response.status_code == 429:
            raise LRCLIBAPIError("rate_limited")

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            logger.error("LRCLIB HTTP error [%s]: %s", url, exc)
            raise LRCLIBAPIError(str(exc)) from exc

        try:
            return response.json()
        except ValueError as exc:
            logger.error("LRCLIB returned non-JSON body [%s]", url)
            raise LRCLIBAPIError("invalid_json") from exc

    @staticmethod
    def _parse_result(data: dict) -> LyricsResult:
        return LyricsResult(
            track_name=data.get("trackName") or data.get("name") or "",
            artist_name=data.get("artistName") or "",
            album_name=data.get("albumName") or "",
            duration=int(data.get("duration") or 0),
            plain_lyrics=data.get("plainLyrics") or None,
            synced_lyrics=data.get("syncedLyrics") or None,
            instrumental=bool(data.get("instrumental", False)),
        )

    def get_lyrics(self, track_name: str, artist_name: str) -> LyricsResult | None:
        from apps.lyrics.models import Artist, Track, LyricCache

        clean_track = track_name.strip()
        clean_artist = artist_name.strip()

        try:
            track_obj = Track.objects.select_related("lyric_cache").get(
                artist__name__iexact=clean_artist,
                name__iexact=clean_track
            )
            if hasattr(track_obj, "lyric_cache"):
                cache_entry = track_obj.lyric_cache
                if cache_entry.has_no_lyrics:
                    return None
                return LyricsResult(
                    track_name=track_obj.name,
                    artist_name=track_obj.artist.name,
                    album_name=cache_entry.album_name,
                    duration=cache_entry.duration,
                    plain_lyrics=cache_entry.plain_lyrics,
                    synced_lyrics=cache_entry.synced_lyrics,
                    instrumental=cache_entry.instrumental
                )
        except Track.DoesNotExist:
            track_obj = None

        result = self._fetch_lyrics_direct(clean_track, clean_artist)
        if result is None:
            result = self._fetch_lyrics_search(clean_track, clean_artist)

        try:
            with transaction.atomic():
                artist_obj, _ = Artist.objects.get_or_create(name=clean_artist)
                if not track_obj:
                    track_obj, _ = Track.objects.get_or_create(artist=artist_obj, name=clean_track)

                if result is not None:
                    LyricCache.objects.update_or_create(
                        track=track_obj,
                        defaults={
                            "album_name": result.album_name,
                            "duration": result.duration,
                            "plain_lyrics": result.plain_lyrics,
                            "synced_lyrics": result.synced_lyrics,
                            "instrumental": result.instrumental,
                            "has_no_lyrics": False,
                        }
                    )
                else:
                    LyricCache.objects.update_or_create(
                        track=track_obj,
                        defaults={"has_no_lyrics": True}
                    )
        except Exception as e:
            logger.error(f"Failed committing lyric cache configuration: {e}")

        return result

    def get_lyrics_for_track(self, track: dict, artist_name: str) -> LyricsResult | None:
        return self.get_lyrics(track_name=track["name"], artist_name=artist_name)

    def _fetch_lyrics_direct(self, track_name: str, artist_name: str) -> LyricsResult | None:
        try:
            data = self._get("/get", params={"track_name": track_name, "artist_name": artist_name})
            return self._parse_result(data) if isinstance(data, dict) else None
        except LRCLIBAPIError as exc:
            if str(exc) != "not_found":
                logger.warning("LRCLIB direct lookup failed for '%s' / '%s': %s", track_name, artist_name, exc)
            return None
        except requests.exceptions.RequestException:
            return None

    def _fetch_lyrics_search(self, track_name: str, artist_name: str) -> LyricsResult | None:
        query = f"{track_name} {artist_name}"
        try:
            data = self._get("/search", params={"q": query})
            if not isinstance(data, list) or not data:
                return None
        except (LRCLIBAPIError, requests.exceptions.RequestException) as exc:
            logger.warning("LRCLIB search failed for '%s': %s", query, exc)
            return None

        artist_norm, track_norm = artist_name.lower(), track_name.lower()
        for item in data:
            item_artist = (item.get("artistName") or "").lower()
            item_track = (item.get("trackName") or item.get("name") or "").lower()
            if artist_norm in item_artist and track_norm in item_track:
                return self._parse_result(item)

        for item in data:
            if artist_norm in (item.get("artistName") or "").lower():
                return self._parse_result(item)

        return self._parse_result(data[0])


_LYRIC_FILLER_WORDS: Final[frozenset] = frozenset({
    "a", "an", "the", "and", "or", "but", "so", "of", "in", "on",
    "at", "to", "is", "it", "i", "me", "my", "we", "oh", "ah",
    "ooh", "yeah", "ya", "na", "la", "mm", "hmm", "hey", "woah",
    "whoa", "uh", "huh", "da", "de", "do", "re", "up", "no",
})

_SECTION_HEADER_RE: Final[re.Pattern] = re.compile(r"^\[.*?\]$", re.IGNORECASE)
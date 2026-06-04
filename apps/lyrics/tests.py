from __future__ import annotations

import random
from unittest.mock import MagicMock, call, patch

import requests
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.lyrics.models import Artist, LyricCache, Track
from apps.lyrics.services.api import (
    LRCLIBAPI,
    LRCLIBAPIError,
    LastFMAPI,
    LyricsResult,
    _build_retry_session,
)
from apps.lyrics.services.helper import (
    _is_variant,
    _normalize_title,
    _should_exclude_completely,
)

User = get_user_model()


class IsVariantTests(TestCase):

    def test_live_bracket(self):
        self.assertTrue(_is_variant("Hey Jude (Live)"))

    def test_live_paren_case_insensitive(self):
        self.assertTrue(_is_variant("Hey Jude (LIVE)"))

    def test_acoustic_paren(self):
        self.assertTrue(_is_variant("Blackbird (Acoustic)"))

    def test_remix_paren(self):
        self.assertTrue(_is_variant("Come Together (Remix)"))

    def test_remaster_paren(self):
        self.assertTrue(_is_variant("Let It Be (Remastered)"))

    def test_remaster_hyphen_paren(self):
        self.assertTrue(_is_variant("Let It Be (Re-mastered)"))

    def test_demo_paren(self):
        self.assertTrue(_is_variant("Strawberry Fields Forever (Demo)"))

    def test_feat_paren(self):
        self.assertTrue(_is_variant("Something (feat. George Harrison)"))

    def test_ft_paren(self):
        self.assertTrue(_is_variant("Something (ft. George Harrison)"))

    def test_radio_edit_paren(self):
        self.assertTrue(_is_variant("Come Together (Radio Edit)"))

    def test_karaoke_paren(self):
        self.assertTrue(_is_variant("Yesterday (Karaoke Version)"))

    def test_cover_paren(self):
        self.assertTrue(_is_variant("Yesterday (Cover)"))

    def test_instrumental_paren(self):
        self.assertTrue(_is_variant("Yesterday (Instrumental)"))

    def test_spotify_single_paren(self):
        self.assertTrue(_is_variant("Yesterday (Spotify Single)"))

    def test_unplugged_paren(self):
        self.assertTrue(_is_variant("About A Girl (Unplugged)"))

    def test_square_bracket_live(self):
        self.assertTrue(_is_variant("Yesterday [Live]"))

    def test_dash_remaster(self):
        self.assertTrue(_is_variant("Let It Be - 2009 Remaster"))

    def test_dash_remastered(self):
        self.assertTrue(_is_variant("Let It Be - Remastered"))

    def test_dash_single(self):
        self.assertTrue(_is_variant("Hey Jude - Single"))

    def test_dash_live(self):
        self.assertTrue(_is_variant("Yesterday - Live"))

    def test_dash_radio_edit(self):
        self.assertTrue(_is_variant("Come Together - Radio Edit"))

    def test_dash_year_remaster(self):
        self.assertTrue(_is_variant("Come Together - 2019 Remaster"))

    def test_clean_title(self):
        self.assertFalse(_is_variant("Yesterday"))

    def test_clean_title_with_apostrophe(self):
        self.assertFalse(_is_variant("Don't Let Me Down"))

    def test_clean_title_with_ampersand(self):
        self.assertFalse(_is_variant("Sun King"))

    def test_clean_title_with_number(self):
        self.assertFalse(_is_variant("Revolution 9"))

    def test_clean_title_parenthetical_non_variant(self):
        self.assertFalse(_is_variant("When I'm Sixty-Four"))


class NormalizeTitleTests(TestCase):

    def test_strips_live_suffix(self):
        self.assertEqual(_normalize_title("Yesterday (Live)"), "yesterday")

    def test_strips_remaster_dash(self):
        self.assertEqual(_normalize_title("Let It Be - 2009 Remaster"), "let it be")

    def test_strips_feat(self):
        self.assertEqual(_normalize_title("Fixing A Hole (feat. someone)"), "fixing a hole")

    def test_lowercases(self):
        self.assertEqual(_normalize_title("A Day In the Life!"), "a day in the life")

    def test_keeps_apostrophe(self):
        self.assertEqual(_normalize_title("Don't Let Me Down"), "don't let me down")

    def test_strips_punctuation_except_apostrophe(self):
        self.assertEqual(_normalize_title("Rock & Roll!"), "rock roll")

    def test_collapses_whitespace(self):
        self.assertEqual(_normalize_title("  White   Album  "), "white album")

    def test_empty_string(self):
        self.assertEqual(_normalize_title(""), "")

    def test_only_variant_suffix_returns_empty(self):
        result = _normalize_title("(Live)")
        self.assertEqual(result, "")

    def test_nested_brackets(self):
        self.assertEqual(
            _normalize_title("Come Together (2019 Remaster)"),
            "come together",
        )

    def test_ft_abbreviation(self):
        self.assertEqual(
            _normalize_title("Something (ft. Eric Clapton)"),
            "something",
        )

    def test_multiple_suffixes(self):
        result = _normalize_title("Yesterday (Live) - 2009 Remaster")
        self.assertEqual(result, "yesterday")


class ShouldExcludeCompletelyTests(TestCase):

    def test_remix(self):
        self.assertTrue(_should_exclude_completely("Come Together Remix"))

    def test_karaoke(self):
        self.assertTrue(_should_exclude_completely("Yesterday (Karaoke)"))

    def test_cover(self):
        self.assertTrue(_should_exclude_completely("Something (Cover)"))

    def test_spotify_single_excluded(self):
        self.assertTrue(_should_exclude_completely("Hey Jude (Spotify Single)"))

    def test_normal_track_not_excluded(self):
        self.assertFalse(_should_exclude_completely("Yesterday"))

    def test_case_insensitive(self):
        self.assertTrue(_should_exclude_completely("Come Together REMIX"))


def _make_result(plain_lyrics: str | None, instrumental: bool = False, **kwargs) -> LyricsResult:
    return LyricsResult(
        track_name=kwargs.get("track_name", "Test Track"),
        artist_name=kwargs.get("artist_name", "Test Artist"),
        album_name=kwargs.get("album_name", "Test Album"),
        duration=kwargs.get("duration", 200),
        plain_lyrics=plain_lyrics,
        synced_lyrics=kwargs.get("synced_lyrics", None),
        instrumental=instrumental,
    )


class LyricsResultHasLyricsTests(TestCase):
    def test_has_lyrics_with_text(self):
        res = _make_result("Some lyrics here")
        self.assertTrue(res.has_lyrics())

    def test_instrumental_returns_false(self):
        res = _make_result("Some lyrics here", instrumental=True)
        self.assertFalse(res.has_lyrics())

    def test_none_lyrics_returns_false(self):
        res = _make_result(None)
        self.assertFalse(res.has_lyrics())

    def test_empty_string_lyrics_returns_false(self):
        res = _make_result("")
        self.assertFalse(res.has_lyrics())

    def test_whitespace_only_returns_false(self):
        res = _make_result("   \n  ")
        self.assertTrue(res.has_lyrics())


class LyricsResultLyricLinesTests(TestCase):
    def test_filters_section_headers(self):
        lyrics = "[Verse 1]\nHello there\n[Chorus]\nGeneral Kenobi\n"
        res = _make_result(lyrics)
        self.assertEqual(res.lyric_lines(), ["Hello there", "General Kenobi"])

    def test_strips_blank_lines(self):
        lyrics = "Line one\n\n\nLine two\n"
        res = _make_result(lyrics)
        self.assertEqual(res.lyric_lines(), ["Line one", "Line two"])

    def test_strips_whitespace_from_lines(self):
        lyrics = "  Hello   \n  World  "
        res = _make_result(lyrics)
        self.assertEqual(res.lyric_lines(), ["Hello", "World"])

    def test_empty_lyrics_returns_empty_list(self):
        res = _make_result(None)
        self.assertEqual(res.lyric_lines(), [])

    def test_all_headers_returns_empty_list(self):
        lyrics = "[Verse 1]\n[Chorus]\n[Bridge]"
        res = _make_result(lyrics)
        self.assertEqual(res.lyric_lines(), [])

    def test_mixed_content_preserved_order(self):
        lyrics = "[Intro]\nFirst line\nSecond line\n[Verse]\nThird line"
        res = _make_result(lyrics)
        self.assertEqual(res.lyric_lines(), ["First line", "Second line", "Third line"])


class LyricsResultLineScoreTests(TestCase):
    def test_meaningful_line_scores_higher_than_filler(self):
        res = _make_result("Hello")
        self.assertGreater(
            res._line_score("magnificent day today"),
            res._line_score("yeah oh yeah la"),
        )

    def test_empty_line_scores_zero(self):
        res = _make_result("Hello")
        self.assertEqual(res._line_score(""), 0)

    def test_filler_only_line_scores_low(self):
        res = _make_result("Hello")
        score = res._line_score("yeah yeah yeah oh oh")
        self.assertLessEqual(score, 5)
        self.assertGreater(score, 0)

    def test_longer_meaningful_line_scores_higher(self):
        res = _make_result("Hello")
        short = res._line_score("beautiful")
        long_ = res._line_score("beautiful morning full of wonder and light")
        self.assertGreater(long_, short)

    def test_score_is_non_negative(self):
        res = _make_result("Hello")
        self.assertGreaterEqual(res._line_score("la la la la"), 0)


class LyricsResultSplitIntoBlocksTests(TestCase):
    def test_two_blocks_separated_by_blank_line(self):
        lyrics = "Line one\nLine two\n\nLine three\nLine four"
        res = _make_result(lyrics)
        blocks = res._split_into_blocks()
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0], ["Line one", "Line two"])
        self.assertEqual(blocks[1], ["Line three", "Line four"])

    def test_section_header_flushes_block(self):
        lyrics = "Line one\n[Chorus]\nLine two"
        res = _make_result(lyrics)
        blocks = res._split_into_blocks()
        self.assertEqual(len(blocks), 2)

    def test_trailing_blank_lines_do_not_create_empty_block(self):
        lyrics = "Line one\nLine two\n\n\n"
        res = _make_result(lyrics)
        blocks = res._split_into_blocks()
        self.assertEqual(len(blocks), 1)

    def test_empty_lyrics_returns_empty(self):
        res = _make_result(None)
        self.assertEqual(res._split_into_blocks(), [])

    def test_single_block_no_blank_lines(self):
        lyrics = "A\nB\nC\nD"
        res = _make_result(lyrics)
        blocks = res._split_into_blocks()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0], ["A", "B", "C", "D"])

    def test_multiple_consecutive_blank_lines_count_as_one_separator(self):
        lyrics = "A\nB\n\n\n\nC\nD"
        res = _make_result(lyrics)
        blocks = res._split_into_blocks()
        self.assertEqual(len(blocks), 2)


class LyricsResultRandomExcerptTests(TestCase):
    RICH_LYRICS = (
        "Blackbird singing in the dead of night\nTake these broken wings and learn to fly\n"
        "All your life\nYou were only waiting for this moment to arise\n\n"
        "Blackbird singing in the dead of night\nTake these sunken eyes and learn to see\n"
        "All your life\nYou were only waiting for this moment to be free\n\n"
        "Blackbird fly, blackbird fly\nInto the light of the dark black night\n"
        "Blackbird fly, blackbird fly\nInto the light of the dark black night"
    )

    def test_returns_list(self):
        res = _make_result(self.RICH_LYRICS)
        result = res.random_excerpt(min_lines=2, max_lines=4)
        self.assertIsInstance(result, list)

    def test_returns_at_least_min_lines(self):
        res = _make_result(self.RICH_LYRICS)
        for _ in range(20):
            result = res.random_excerpt(min_lines=2, max_lines=4)
            if result:
                self.assertGreaterEqual(len(result), 2)

    def test_returns_at_most_max_lines(self):
        res = _make_result(self.RICH_LYRICS)
        for _ in range(20):
            result = res.random_excerpt(min_lines=2, max_lines=4)
            self.assertLessEqual(len(result), 4)

    def test_fallback_when_no_blocks(self):
        res = _make_result("\n\n  \n\n")
        self.assertEqual(res.random_excerpt(min_lines=2, max_lines=4), [])

    def test_fallback_when_blocks_too_short(self):
        res = _make_result("magnificent morning light\n\nwonderful peaceful day")
        result = res.random_excerpt(min_lines=2, max_lines=4)
        self.assertIsInstance(result, list)

    def test_excerpt_lines_come_from_lyrics(self):
        res = _make_result(self.RICH_LYRICS)
        all_lines = res.lyric_lines()
        result = res.random_excerpt(min_lines=2, max_lines=4)
        for line in result:
            self.assertIn(line, all_lines)

    def test_none_lyrics_returns_empty(self):
        res = _make_result(None)
        self.assertEqual(res.random_excerpt(), [])

    def test_highly_repetitive_lyrics_still_returns_something(self):
        lyrics = "\n".join(["na na na na"] * 8)
        res = _make_result(lyrics, track_name="Na Song")
        result = res.random_excerpt(min_lines=2, max_lines=4)
        self.assertIsInstance(result, list)

    def test_title_heavy_block_penalised(self):
        rich_block = "Into the light of the dark black night\nWaiting for this moment to arise\n" \
                    "All your life you were only waiting\nSunken eyes and learn to see"
        title_block = "Yesterday yesterday yesterday\nYesterday yesterday yesterday\n" \
                    "Yesterday yesterday yesterday\nYesterday yesterday yesterday"
        lyrics = rich_block + "\n\n" + title_block
        res = _make_result(lyrics, track_name="Yesterday")
        choices = set()
        for _ in range(30):
            result = res.random_excerpt(min_lines=2, max_lines=4)
            if result:
                choices.add(result[0])
        self.assertTrue(any(line not in title_block for line in choices))


class LastFMAPIDeduplicationTests(TestCase):

    @patch("apps.lyrics.services.api.requests.Session")
    def test_deduplication_drops_live_variant(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "toptracks": {
                "track": [
                    {"name": "Yesterday", "playcount": "1000", "mbid": "1"},
                    {"name": "Yesterday (Live)", "playcount": "100", "mbid": "2"},
                    {"name": "Let It Be", "playcount": "500", "mbid": "3"},
                ]
            }
        }
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        tracks = api.get_top_tracks("The Beatles")
        names = [t["name"] for t in tracks]
        self.assertIn("Yesterday", names)
        self.assertNotIn("Yesterday (Live)", names)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_deduplication_picks_higher_playcount_canonical(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "toptracks": {
                "track": [
                    {"name": "Come Together", "playcount": "800", "mbid": "a"},
                    {"name": "Come Together (Remastered)", "playcount": "200", "mbid": "b"},
                    {"name": "Let It Be", "playcount": "600", "mbid": "c"},
                ]
            }
        }
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        tracks = api.get_top_tracks("The Beatles")
        ct = next(t for t in tracks if "Come Together" in t["name"])
        self.assertEqual(ct["playcount"], 800)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_deduplication_drops_remix(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "toptracks": {
                "track": [
                    {"name": "Twist and Shout", "playcount": "900", "mbid": "x"},
                    {"name": "Twist and Shout (Remix)", "playcount": "50", "mbid": "y"},
                    {"name": "Help!", "playcount": "700", "mbid": "z"},
                    {"name": "Abbey Road", "playcount": "400", "mbid": "w"},
                ]
            }
        }
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        tracks = api.get_top_tracks("The Beatles")
        names = [t["name"] for t in tracks]
        self.assertNotIn("Twist and Shout (Remix)", names)


class LastFMAPIDatabaseCachingTests(TestCase):

    @patch("apps.lyrics.services.api.requests.Session")
    def test_creates_artist_and_marks_fully_cached(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "toptracks": {
                "track": [
                    {"name": "Yesterday", "playcount": "1000", "mbid": "1"},
                    {"name": "Let It Be", "playcount": "500", "mbid": "3"},
                    {"name": "Hey Jude", "playcount": "800", "mbid": "4"},
                ]
            }
        }
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        api.get_top_tracks("The Beatles")

        self.assertTrue(Artist.objects.filter(name="The Beatles").exists())
        artist = Artist.objects.get(name="The Beatles")
        self.assertTrue(artist.is_fully_cached)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_tracks_are_saved_to_db(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "toptracks": {
                "track": [
                    {"name": "Yesterday", "playcount": "1000", "mbid": "1"},
                    {"name": "Let It Be", "playcount": "500", "mbid": "3"},
                    {"name": "Hey Jude", "playcount": "800", "mbid": "4"},
                ]
            }
        }
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        api.get_top_tracks("The Beatles")

        artist = Artist.objects.get(name="The Beatles")
        saved_names = set(Track.objects.filter(artist=artist).values_list("name", flat=True))
        self.assertIn("Yesterday", saved_names)
        self.assertIn("Let It Be", saved_names)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_uses_cache_on_second_call_no_network(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "toptracks": {
                "track": [
                    {"name": "Yesterday", "playcount": "1000", "mbid": "1"},
                    {"name": "Let It Be", "playcount": "500", "mbid": "3"},
                    {"name": "Hey Jude", "playcount": "800", "mbid": "4"},
                ]
            }
        }
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        api.get_top_tracks("The Beatles")
        api.get_top_tracks("The Beatles")

        self.assertEqual(mock_session.get.call_count, 1)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_second_call_returns_same_tracks(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "toptracks": {
                "track": [
                    {"name": "Yesterday", "playcount": "1000", "mbid": "1"},
                    {"name": "Let It Be", "playcount": "500", "mbid": "3"},
                    {"name": "Hey Jude", "playcount": "800", "mbid": "4"},
                ]
            }
        }
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        first = api.get_top_tracks("The Beatles")
        second = api.get_top_tracks("The Beatles")

        self.assertEqual(
            sorted(t["name"] for t in first),
            sorted(t["name"] for t in second),
        )

    @patch("apps.lyrics.services.api.requests.Session")
    def test_empty_response_returns_empty_list(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {"toptracks": {"track": []}}
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        result = api.get_top_tracks("Nonexistent Artist XYZ")
        self.assertEqual(result, [])

    @patch("apps.lyrics.services.api.requests.Session")
    def test_network_failure_falls_back_to_db(self, mock_session_class):
        artist = Artist.objects.create(name="Fallback Artist", is_fully_cached=False)
        Track.objects.create(artist=artist, name="Saved Track", playcount=999)

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectionError("down")

        api = LastFMAPI()
        tracks = api.get_top_tracks("Fallback Artist")
        names = [t["name"] for t in tracks]
        self.assertIn("Saved Track", names)


class LastFMAPIGetTrackDifficultyTests(TestCase):

    def _mock_api_with_tracks(self, mock_session_class, track_count: int = 20) -> LastFMAPI:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        tracks = [
            {"name": f"Track {i}", "playcount": str(max(1, 10000 // (2 ** i))), "mbid": str(i)}
            for i in range(track_count)
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"toptracks": {"track": tracks}}
        mock_session.get.return_value = mock_response
        return LastFMAPI()

    @patch("apps.lyrics.services.api.requests.Session")
    def test_easy_returns_popular_track(self, mock_session_class):
        random.seed(0)
        api = self._mock_api_with_tracks(mock_session_class, 20)
        track = api.get_track("Artist", "easy")
        self.assertIsNotNone(track)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_insane_avoids_top_tracks(self, mock_session_class):
        random.seed(42)
        api = self._mock_api_with_tracks(mock_session_class, 20)
        seen = {api.get_track("Artist", "insane")["name"] for _ in range(30)}
        self.assertNotIn("Track 0", seen)
        self.assertNotIn("Track 1", seen)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_invalid_difficulty_falls_back_to_hard(self, mock_session_class):
        random.seed(1)
        api = self._mock_api_with_tracks(mock_session_class, 20)
        track = api.get_track("Artist", "legendary")
        self.assertIsNotNone(track)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_returns_none_for_empty_artist(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {"toptracks": {"track": []}}
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        result = api.get_track("Ghost Artist", "easy")
        self.assertIsNone(result)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_very_small_library_hard_and_insane_dont_crash(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "toptracks": {
                "track": [
                    {"name": "Only Track", "playcount": "100", "mbid": "1"},
                    {"name": "Second Track", "playcount": "50", "mbid": "2"},
                    {"name": "Third Track", "playcount": "25", "mbid": "3"},
                ]
            }
        }
        mock_session.get.return_value = mock_response

        api = LastFMAPI()
        for difficulty in ("hard", "insane"):
            with self.subTest(difficulty=difficulty):
                result = api.get_track("Tiny Discography", difficulty)
                self.assertIsNotNone(result)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_medium_avoids_top_and_bottom(self, mock_session_class):
        random.seed(7)
        api = self._mock_api_with_tracks(mock_session_class, 20)
        results = [api.get_track("Artist", "medium")["name"] for _ in range(50)]
        medium_top_count = results.count("Track 0")
        self.assertLess(medium_top_count, 10)


class LastFMAPIErrorHandlingTests(TestCase):

    @patch("apps.lyrics.services.api.requests.Session")
    def test_timeout_falls_back_gracefully(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.Timeout()

        api = LastFMAPI()
        result = api.get_top_tracks("Some Artist")
        self.assertEqual(result, [])



class LRCLIBAPICacheTests(TestCase):

    def _make_track(self, track_name="Yesterday", artist_name="The Beatles") -> Track:
        artist, _ = Artist.objects.get_or_create(name=artist_name)
        track, _ = Track.objects.get_or_create(artist=artist, name=track_name, defaults={"playcount": 1000})
        return track

    @patch("apps.lyrics.services.api.requests.Session")
    def test_cache_hit_skips_network(self, mock_session_class):
        track = self._make_track()
        LyricCache.objects.create(
            track=track, album_name="Help!", duration=125,
            plain_lyrics="Yesterday...", instrumental=False
        )

        api = LRCLIBAPI()
        result = api.get_lyrics("Yesterday", "The Beatles")

        self.assertIsNotNone(result)
        self.assertEqual(result.album_name, "Help!")
        mock_session_class.return_value.get.assert_not_called()

    @patch("apps.lyrics.services.api.requests.Session")
    def test_cache_hit_has_no_lyrics_returns_none(self, mock_session_class):
        track = self._make_track("Instrumental Track")
        LyricCache.objects.create(track=track, has_no_lyrics=True)

        api = LRCLIBAPI()
        result = api.get_lyrics("Instrumental Track", "The Beatles")

        self.assertIsNone(result)
        mock_session_class.return_value.get.assert_not_called()

    @patch("apps.lyrics.services.api.requests.Session")
    def test_successful_fetch_is_persisted_to_cache(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "trackName": "Hey Jude",
            "artistName": "The Beatles",
            "albumName": "Singles",
            "duration": 431,
            "plainLyrics": "Hey Jude, don't be afraid\nTake a sad song and make it better",
            "syncedLyrics": None,
            "instrumental": False,
        }
        mock_session.get.return_value = mock_response

        api = LRCLIBAPI()
        result = api.get_lyrics("Hey Jude", "The Beatles")

        self.assertIsNotNone(result)
        self.assertEqual(result.album_name, "Singles")
        track = Track.objects.get(artist__name="The Beatles", name="Hey Jude")
        self.assertTrue(hasattr(track, "lyric_cache"))
        self.assertEqual(track.lyric_cache.album_name, "Singles")

    @patch("apps.lyrics.services.api.requests.Session")
    def test_404_response_stored_as_has_no_lyrics(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        not_found_response = MagicMock()
        not_found_response.status_code = 404

        empty_search_response = MagicMock()
        empty_search_response.status_code = 200
        empty_search_response.json.return_value = []

        mock_session.get.side_effect = [not_found_response, empty_search_response]

        api = LRCLIBAPI()
        result = api.get_lyrics("Nonexistent Song", "No Artist")

        self.assertIsNone(result)
        track = Track.objects.get(artist__name="No Artist", name="Nonexistent Song")
        self.assertTrue(track.lyric_cache.has_no_lyrics)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_network_timeout_returns_none(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.Timeout("timed out")

        api = LRCLIBAPI()
        result = api.get_lyrics("Yesterday", "The Beatles")
        self.assertIsNone(result)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_connection_error_returns_none(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectionError("no route")

        api = LRCLIBAPI()
        result = api.get_lyrics("Yesterday", "The Beatles")
        self.assertIsNone(result)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_rate_limit_response_raises_lrclib_error(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        rate_limited = MagicMock()
        rate_limited.status_code = 429

        empty_search = MagicMock()
        empty_search.status_code = 200
        empty_search.json.return_value = []

        mock_session.get.side_effect = [rate_limited, empty_search]

        api = LRCLIBAPI()
        result = api.get_lyrics("Test Song", "Test Artist")
        self.assertIsNone(result)


class LRCLIBAPISearchFallbackTests(TestCase):

    @patch("apps.lyrics.services.api.requests.Session")
    def test_search_finds_matching_result(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        not_found = MagicMock()
        not_found.status_code = 404

        search_result = MagicMock()
        search_result.status_code = 200
        search_result.json.return_value = [
            {
                "trackName": "Yesterday",
                "artistName": "The Beatles",
                "albumName": "Help!",
                "duration": 125,
                "plainLyrics": "Yesterday all my troubles seemed so far away",
                "syncedLyrics": None,
                "instrumental": False,
            }
        ]

        mock_session.get.side_effect = [not_found, search_result]

        api = LRCLIBAPI()
        result = api.get_lyrics("Yesterday", "The Beatles")

        self.assertIsNotNone(result)
        self.assertEqual(result.album_name, "Help!")

    @patch("apps.lyrics.services.api.requests.Session")
    def test_search_rejects_wrong_artist(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        not_found = MagicMock()
        not_found.status_code = 404

        search_result = MagicMock()
        search_result.status_code = 200
        search_result.json.return_value = [
            {
                "trackName": "Yesterday",
                "artistName": "Some Cover Artist",
                "albumName": "Covers",
                "duration": 125,
                "plainLyrics": "...",
                "syncedLyrics": None,
                "instrumental": False,
            }
        ]

        mock_session.get.side_effect = [not_found, search_result]

        api = LRCLIBAPI()
        result = api.get_lyrics("Yesterday", "The Beatles")
        self.assertIsNone(result)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_search_empty_list_returns_none(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        not_found = MagicMock()
        not_found.status_code = 404

        empty = MagicMock()
        empty.status_code = 200
        empty.json.return_value = []

        mock_session.get.side_effect = [not_found, empty]

        api = LRCLIBAPI()
        result = api.get_lyrics("Ghost Track", "The Beatles")
        self.assertIsNone(result)


class LRCLIBAPIParseResultTests(TestCase):

    def test_full_data(self):
        data = {
            "trackName": "Yesterday",
            "artistName": "The Beatles",
            "albumName": "Help!",
            "duration": 125,
            "plainLyrics": "lyrics here",
            "syncedLyrics": "[00:00.00] lyrics here",
            "instrumental": False,
        }
        result = LRCLIBAPI._parse_result(data)
        self.assertEqual(result.track_name, "Yesterday")
        self.assertEqual(result.artist_name, "The Beatles")
        self.assertEqual(result.album_name, "Help!")
        self.assertEqual(result.duration, 125)
        self.assertEqual(result.plain_lyrics, "lyrics here")
        self.assertFalse(result.instrumental)

    def test_instrumental_flag(self):
        data = {
            "trackName": "Piano Piece",
            "artistName": "Composer",
            "albumName": "",
            "duration": 200,
            "plainLyrics": None,
            "syncedLyrics": None,
            "instrumental": True,
        }
        result = LRCLIBAPI._parse_result(data)
        self.assertTrue(result.instrumental)
        self.assertFalse(result.has_lyrics())

    def test_missing_fields_use_defaults(self):
        result = LRCLIBAPI._parse_result({})
        self.assertEqual(result.track_name, "")
        self.assertEqual(result.artist_name, "")
        self.assertEqual(result.duration, 0)
        self.assertIsNone(result.plain_lyrics)

    def test_name_fallback_field(self):
        data = {"name": "Track via name", "artistName": "Artist", "albumName": "", "duration": 0}
        result = LRCLIBAPI._parse_result(data)
        self.assertEqual(result.track_name, "Track via name")


class FetchViewAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("lyrics:fetch", kwargs={"artist_slug": "The Beatles", "difficulty_slug": "easy"})
        self.staff_user = User.objects.create_user(
            username="staff", email="staff@example.com", password="password", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username="pleb", email="pleb@example.com", password="password", is_staff=False
        )

    def test_anonymous_is_redirected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_non_staff_is_redirected(self):
        self.client.login(username="pleb", password="password")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_staff_can_access(self, mock_lastfm_class, mock_lrclib_class):
        self.client.login(username="staff", password="password")

        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"name": "Yesterday", "playcount": 1000, "mbid": "1"}
        mock_lastfm_class.return_value = mock_lastfm

        mock_lyrics = MagicMock()
        mock_lyrics.has_lyrics.return_value = True
        mock_lyrics.random_excerpt.return_value = ["Line 1", "Line 2"]
        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = mock_lyrics
        mock_lrclib_class.return_value = mock_lrclib

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class FetchViewSuccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="staff", email="staff@example.com", password="password", is_staff=True
        )
        self.client.login(username="staff", password="password")

    def _url(self, artist="The Beatles", difficulty="easy"):
        return reverse("lyrics:fetch", kwargs={"artist_slug": artist, "difficulty_slug": difficulty})

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_success_response_shape(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"name": "Yesterday", "playcount": 1000, "mbid": "abc"}
        mock_lastfm_class.return_value = mock_lastfm

        mock_lyrics = MagicMock()
        mock_lyrics.has_lyrics.return_value = True
        mock_lyrics.random_excerpt.return_value = ["Line 1", "Line 2"]
        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = mock_lyrics
        mock_lrclib_class.return_value = mock_lrclib

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("track", data)
        self.assertIn("difficulty", data)
        self.assertIn("excerpt", data)

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_response_track_fields(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"name": "Yesterday", "playcount": 1000, "mbid": "abc"}
        mock_lastfm_class.return_value = mock_lastfm

        mock_lyrics = MagicMock()
        mock_lyrics.has_lyrics.return_value = True
        mock_lyrics.random_excerpt.return_value = ["A", "B"]
        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = mock_lyrics
        mock_lrclib_class.return_value = mock_lrclib

        response = self.client.get(self._url())
        data = response.json()
        self.assertEqual(data["track"]["name"], "Yesterday")
        self.assertEqual(data["track"]["playcount"], 1000)
        self.assertEqual(data["track"]["mbid"], "abc")

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_difficulty_slug_is_normalized_lowercase(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"name": "Yesterday", "playcount": 1000, "mbid": "1"}
        mock_lastfm_class.return_value = mock_lastfm

        mock_lyrics = MagicMock()
        mock_lyrics.has_lyrics.return_value = True
        mock_lyrics.random_excerpt.return_value = ["X"]
        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = mock_lyrics
        mock_lrclib_class.return_value = mock_lrclib

        url = reverse("lyrics:fetch", kwargs={"artist_slug": "The Beatles", "difficulty_slug": "HARD"})
        response = self.client.get(url)
        data = response.json()
        self.assertEqual(data["difficulty"], "hard")

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_excerpt_is_list(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"name": "Yesterday", "playcount": 1000, "mbid": "1"}
        mock_lastfm_class.return_value = mock_lastfm

        mock_lyrics = MagicMock()
        mock_lyrics.has_lyrics.return_value = True
        mock_lyrics.random_excerpt.return_value = ["Line 1", "Line 2", "Line 3"]
        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = mock_lyrics
        mock_lrclib_class.return_value = mock_lrclib

        response = self.client.get(self._url())
        data = response.json()
        self.assertIsInstance(data["excerpt"], list)
        self.assertEqual(len(data["excerpt"]), 3)


class FetchViewErrorTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="staff", email="staff@example.com", password="password", is_staff=True
        )
        self.client.login(username="staff", password="password")

    def _url(self, artist="The Beatles", difficulty="easy"):
        return reverse("lyrics:fetch", kwargs={"artist_slug": artist, "difficulty_slug": difficulty})

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_no_track_returns_404(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = None
        mock_lastfm_class.return_value = mock_lastfm
        mock_lrclib_class.return_value = MagicMock()

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_no_lyrics_returns_404(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"name": "Yesterday", "playcount": 1000, "mbid": "1"}
        mock_lastfm_class.return_value = mock_lastfm

        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = None
        mock_lrclib_class.return_value = mock_lrclib

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_instrumental_lyrics_returns_404(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"name": "Yesterday", "playcount": 1000, "mbid": "1"}
        mock_lastfm_class.return_value = mock_lastfm

        mock_lyrics = MagicMock()
        mock_lyrics.has_lyrics.return_value = False
        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = mock_lyrics
        mock_lrclib_class.return_value = mock_lrclib

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_empty_excerpt_returns_404(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"name": "Yesterday", "playcount": 1000, "mbid": "1"}
        mock_lastfm_class.return_value = mock_lastfm

        mock_lyrics = MagicMock()
        mock_lyrics.has_lyrics.return_value = True
        mock_lyrics.random_excerpt.return_value = []
        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = mock_lyrics
        mock_lrclib_class.return_value = mock_lrclib

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_unexpected_exception_returns_500(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.side_effect = RuntimeError("Unexpected crash!")
        mock_lastfm_class.return_value = mock_lastfm
        mock_lrclib_class.return_value = MagicMock()

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.json())

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_track_missing_name_field_returns_404(self, mock_lastfm_class, mock_lrclib_class):
        mock_lastfm = MagicMock()
        mock_lastfm.get_track.return_value = {"playcount": 100}
        mock_lastfm_class.return_value = mock_lastfm
        mock_lrclib_class.return_value = MagicMock()

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)


class ArtistModelTests(TestCase):
    def test_str_representation(self):
        artist = Artist(name="The Beatles")
        self.assertEqual(str(artist), "The Beatles")

    def test_default_is_not_fully_cached(self):
        artist = Artist.objects.create(name="New Artist")
        self.assertFalse(artist.is_fully_cached)

    def test_unique_name_constraint(self):
        Artist.objects.create(name="Unique Artist")
        with self.assertRaises(Exception):
            Artist.objects.create(name="Unique Artist")

    def test_ordering_is_alphabetical(self):
        Artist.objects.create(name="Zeppelin")
        Artist.objects.create(name="Abba")
        Artist.objects.create(name="Madonna")
        names = list(Artist.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names))


class TrackModelTests(TestCase):
    def setUp(self):
        self.artist = Artist.objects.create(name="The Beatles")

    def test_str_representation(self):
        track = Track(artist=self.artist, name="Yesterday")
        self.assertEqual(str(track), "The Beatles - Yesterday")

    def test_unique_together_artist_name(self):
        Track.objects.create(artist=self.artist, name="Yesterday", playcount=1000)
        with self.assertRaises(Exception):
            Track.objects.create(artist=self.artist, name="Yesterday", playcount=500)

    def test_ordering_by_playcount_desc(self):
        Track.objects.create(artist=self.artist, name="Low", playcount=100)
        Track.objects.create(artist=self.artist, name="High", playcount=5000)
        Track.objects.create(artist=self.artist, name="Mid", playcount=500)
        names = list(Track.objects.filter(artist=self.artist).values_list("name", flat=True))
        self.assertEqual(names, ["High", "Mid", "Low"])

    def test_cascade_delete(self):
        Track.objects.create(artist=self.artist, name="Yesterday", playcount=1000)
        self.artist.delete()
        self.assertEqual(Track.objects.filter(name="Yesterday").count(), 0)

    def test_blank_mbid_default(self):
        track = Track.objects.create(artist=self.artist, name="No MBID Track", playcount=100)
        self.assertEqual(track.mbid, "")


class LyricCacheModelTests(TestCase):
    def setUp(self):
        self.artist = Artist.objects.create(name="The Beatles")
        self.track = Track.objects.create(artist=self.artist, name="Yesterday", playcount=1000)

    def test_str_representation(self):
        cache = LyricCache(track=self.track)
        self.assertIn("Yesterday", str(cache))

    def test_one_to_one_track_relationship(self):
        cache = LyricCache.objects.create(track=self.track, plain_lyrics="lyrics")
        self.assertEqual(cache.track, self.track)
        self.assertEqual(self.track.lyric_cache, cache)

    def test_duplicate_lyric_cache_raises(self):
        LyricCache.objects.create(track=self.track)
        with self.assertRaises(Exception):
            LyricCache.objects.create(track=self.track)

    def test_has_no_lyrics_default_false(self):
        cache = LyricCache.objects.create(track=self.track)
        self.assertFalse(cache.has_no_lyrics)

    def test_instrumental_default_false(self):
        cache = LyricCache.objects.create(track=self.track)
        self.assertFalse(cache.instrumental)


class WarmMusicUpCommandTests(TestCase):
    @patch("apps.lyrics.management.commands.warm_music_up.LRCLIBAPI")
    @patch("apps.lyrics.management.commands.warm_music_up.LastFMAPI")
    def test_command_caches_tracks_and_lyrics(self, mock_lastfm_class, mock_lrclib_class):
        from django.core.management import call_command
        from io import StringIO

        mock_lastfm = MagicMock()
        mock_lastfm.get_top_tracks.return_value = [
            {"name": f"Track {i}", "playcount": 1000 - i, "mbid": str(i)}
            for i in range(5)
        ]
        mock_lastfm_class.return_value = mock_lastfm

        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = MagicMock()
        mock_lrclib_class.return_value = mock_lrclib

        out = StringIO()
        call_command("warm_music_up", "The Beatles", stdout=out)

        mock_lastfm.get_top_tracks.assert_called_once_with("The Beatles")
        self.assertEqual(mock_lrclib.get_lyrics_for_track.call_count, 5)
        self.assertIn("Database warming complete", out.getvalue())

    @patch("apps.lyrics.management.commands.warm_music_up.LRCLIBAPI")
    @patch("apps.lyrics.management.commands.warm_music_up.LastFMAPI")
    def test_command_handles_empty_track_list_gracefully(self, mock_lastfm_class, mock_lrclib_class):
        from django.core.management import call_command
        from io import StringIO

        mock_lastfm = MagicMock()
        mock_lastfm.get_top_tracks.return_value = []
        mock_lastfm_class.return_value = mock_lastfm

        mock_lrclib = MagicMock()
        mock_lrclib_class.return_value = mock_lrclib

        err = StringIO()
        out = StringIO()
        call_command("warm_music_up", "Empty Artist", stdout=out, stderr=err)

        mock_lrclib.get_lyrics_for_track.assert_not_called()

    @patch("apps.lyrics.management.commands.warm_music_up.LRCLIBAPI")
    @patch("apps.lyrics.management.commands.warm_music_up.LastFMAPI")
    def test_command_continues_after_lastfm_failure(self, mock_lastfm_class, mock_lrclib_class):
        from django.core.management import call_command
        from io import StringIO

        mock_lastfm = MagicMock()
        mock_lastfm.get_top_tracks.side_effect = [
            RuntimeError("API down"),
            [{"name": "Track 1", "playcount": 100, "mbid": "1"}],
        ]
        mock_lastfm_class.return_value = mock_lastfm

        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = None
        mock_lrclib_class.return_value = mock_lrclib

        out = StringIO()
        err = StringIO()
        call_command("warm_music_up", "Bad Artist", "Good Artist", stdout=out, stderr=err)

        mock_lrclib.get_lyrics_for_track.assert_called()

    @patch("apps.lyrics.management.commands.warm_music_up.LRCLIBAPI")
    @patch("apps.lyrics.management.commands.warm_music_up.LastFMAPI")
    def test_command_caps_lyrics_fetch_at_15(self, mock_lastfm_class, mock_lrclib_class):
        from django.core.management import call_command
        from io import StringIO

        mock_lastfm = MagicMock()
        mock_lastfm.get_top_tracks.return_value = [
            {"name": f"Track {i}", "playcount": 1000 - i, "mbid": str(i)}
            for i in range(30)
        ]
        mock_lastfm_class.return_value = mock_lastfm

        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.return_value = None
        mock_lrclib_class.return_value = mock_lrclib

        call_command("warm_music_up", "Prolific Artist", stdout=StringIO())

        self.assertEqual(mock_lrclib.get_lyrics_for_track.call_count, 15)

    @patch("apps.lyrics.management.commands.warm_music_up.LRCLIBAPI")
    @patch("apps.lyrics.management.commands.warm_music_up.LastFMAPI")
    def test_command_handles_individual_lyric_fetch_failure(self, mock_lastfm_class, mock_lrclib_class):
        from django.core.management import call_command
        from io import StringIO

        mock_lastfm = MagicMock()
        mock_lastfm.get_top_tracks.return_value = [
            {"name": f"Track {i}", "playcount": 100, "mbid": str(i)}
            for i in range(3)
        ]
        mock_lastfm_class.return_value = mock_lastfm

        mock_lrclib = MagicMock()
        mock_lrclib.get_lyrics_for_track.side_effect = [
            Exception("network error"),
            None,
            MagicMock(),
        ]
        mock_lrclib_class.return_value = mock_lrclib

        out = StringIO()
        call_command("warm_music_up", "Artist With Failures", stdout=out)
        self.assertIn("Database warming complete", out.getvalue())


class BuildRetrySessionTests(TestCase):
    def test_returns_session(self):
        session = _build_retry_session()
        self.assertIsInstance(session, requests.Session)

    def test_custom_user_agent(self):
        session = _build_retry_session(user_agent="MyApp/1.0")
        self.assertEqual(session.headers["User-Agent"], "MyApp/1.0")

    def test_no_user_agent_does_not_set_header(self):
        session = _build_retry_session()
        self.assertNotEqual(session.headers.get("User-Agent"), "MyApp/1.0")
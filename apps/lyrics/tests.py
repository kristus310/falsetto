from unittest.mock import patch, MagicMock
import requests
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.lyrics.services.helper import _is_variant, _normalize_title
from apps.lyrics.services.api import LyricsResult, LastFMAPI, LRCLIBAPI, LRCLIBAPIError
from apps.lyrics.models import Artist, Track, LyricCache

User = get_user_model()

class HelperTests(TestCase):
    def test_is_variant(self):
        self.assertTrue(_is_variant("Yesterday (Live)"))
        self.assertTrue(_is_variant("Yesterday - Acoustic"))
        self.assertTrue(_is_variant("Yesterday (feat. Paul McCartney)"))
        self.assertFalse(_is_variant("Yesterday"))

    def test_normalize_title(self):
        self.assertEqual(_normalize_title("Yesterday (Live)"), "yesterday")
        self.assertEqual(_normalize_title("Let It Be - 2009 Remaster"), "let it be")
        self.assertEqual(_normalize_title("Fixing A Hole (feat. someone)"), "fixing a hole")
        self.assertEqual(_normalize_title("A Day In the Life!"), "a day in the life")

    def test_normalize_title_keeps_apostrophe(self):
        self.assertEqual(_normalize_title("Don't Let Me Down"), "don't let me down")

class LyricsResultTests(TestCase):
    def test_has_lyrics_and_instrumental(self):
        res1 = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics="Hello world", synced_lyrics=None, instrumental=False
        )
        self.assertTrue(res1.has_lyrics())

        res2 = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics="Hello world", synced_lyrics=None, instrumental=True
        )
        self.assertFalse(res2.has_lyrics())

    def test_lyric_lines_filters_section_headers(self):
        lyrics = "[Verse 1]\nHello there\n[Chorus]\nGeneral Kenobi\n"
        res = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics=lyrics, synced_lyrics=None, instrumental=False
        )
        self.assertEqual(res.lyric_lines(), ["Hello there", "General Kenobi"])

    def test_line_score(self):
        res = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics="Hello", synced_lyrics=None, instrumental=False
        )
        self.assertTrue(res._line_score("magnificent day today") > res._line_score("yeah oh yeah la"))

    def test_split_into_blocks(self):
        lyrics = "Line one\nLine two\n\nLine three\nLine four"
        res = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics=lyrics, synced_lyrics=None, instrumental=False
        )
        blocks = res._split_into_blocks()
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0], ["Line one", "Line two"])

    def test_random_excerpt_fallback_when_unscored(self):
        res = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics="\n\n  \n\n", synced_lyrics=None, instrumental=False
        )
        self.assertEqual(res.random_excerpt(min_lines=2, max_lines=4), [])

class LastFMAPITests(TestCase):
    @patch("apps.lyrics.services.api.requests.Session")
    def test_get_top_tracks_deduplication_and_db_caching(self, mock_session_class):
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

        self.assertTrue(Artist.objects.filter(name__iexact="The Beatles").exists())
        artist = Artist.objects.get(name__iexact="The Beatles")
        self.assertTrue(artist.is_fully_cached)
        self.assertEqual(Track.objects.filter(artist=artist).count(), 2)

    @patch("apps.lyrics.services.api.requests.Session")
    def test_get_track_difficulty_distribution(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        tracks = [{"name": f"Track {i}", "playcount": str(1000 - i * 100), "mbid": str(i)} for i in range(10)]
        mock_response = MagicMock()
        mock_response.json.return_value = {"toptracks": {"track": tracks}}
        mock_session.get.return_value = mock_response

        api = LastFMAPI()

        easy_track = api.get_track("Artist", "easy")
        self.assertIn(easy_track["name"], ["Track 0", "Track 1", "Track 2"])

        insane_results = {api.get_track("Artist", "insane")["name"] for _ in range(20)}
        self.assertFalse(insane_results.intersection({"Track 0", "Track 1", "Track 2"}))

class LRCLIBAPITests(TestCase):
    @patch("apps.lyrics.services.api.requests.Session")
    def test_get_lyrics_cache_hit(self, mock_session_class):
        artist = Artist.objects.create(name="The Beatles")
        track = Track.objects.create(artist=artist, name="Yesterday", playcount=1000)
        LyricCache.objects.create(
            track=track, album_name="Help!", duration=125,
            plain_lyrics="Yesterday...", instrumental=False
        )

        api = LRCLIBAPI()
        res = api.get_lyrics("Yesterday", "The Beatles")
        self.assertIsNotNone(res)
        self.assertEqual(res.album_name, "Help!")
        mock_session_class.return_value.get.assert_not_called()

    @patch("apps.lyrics.services.api.requests.Session")
    def test_fetch_lyrics_network_failure_handling(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.Timeout("Connection timed out")
        mock_session_class.return_value = mock_session

        api = LRCLIBAPI()
        res = api.get_lyrics("Yesterday", "The Beatles")
        self.assertIsNone(res)

class LyricsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("lyrics:fetch", kwargs={"artist_slug": "The Beatles", "difficulty_slug": "easy"})

        self.staff_user = User.objects.create_user(
            username="staff", email="staff@example.com", password="password", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username="pleb", email="pleb@example.com", password="password", is_staff=False
        )

    def test_fetch_endpoint_requires_staff(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        self.client.login(username="pleb", password="password")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    @patch("apps.lyrics.views.LRCLIBAPI")
    @patch("apps.lyrics.views.LastFMAPI")
    def test_fetch_endpoint_success_path(self, mock_lastfm_class, mock_lrclib_class):
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
        data = response.json()
        self.assertEqual(data["track"]["name"], "Yesterday")
        self.assertEqual(data["excerpt"], ["Line 1", "Line 2"])
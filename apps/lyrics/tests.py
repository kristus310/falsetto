from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.lyrics.services.helper import _is_variant, _normalize_title
from apps.lyrics.services.api import LyricsResult, LastFMAPI, LRCLIBAPI

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

        res3 = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics=None, synced_lyrics=None, instrumental=False
        )
        self.assertFalse(res3.has_lyrics())

    def test_lyric_lines_filters_section_headers(self):
        lyrics = "[Verse 1]\nHello there\n[Chorus]\nGeneral Kenobi\n"
        res = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics=lyrics, synced_lyrics=None, instrumental=False
        )
        lines = res.lyric_lines()
        self.assertEqual(lines, ["Hello there", "General Kenobi"])

    def test_line_score(self):
        res = LyricsResult(
            track_name="Song", artist_name="Artist", album_name="Album",
            duration=180, plain_lyrics="Hello", synced_lyrics=None, instrumental=False
        )
        score_meaningful = res._line_score("magnificent day today")
        score_filler = res._line_score("yeah oh yeah la")
        self.assertTrue(score_meaningful > score_filler)

class LastFMAPITests(TestCase):
    @patch("apps.lyrics.services.api.requests.Session")
    def test_get_top_tracks_deduplication(self, mock_session_class):
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
        api.api_key = "test"
        api.base_url = "https://example.com"
        
        tracks = api.get_top_tracks("The Beatles")
        
        names = [t["name"] for t in tracks]
        self.assertIn("Yesterday", names)
        self.assertIn("Let It Be", names)
        self.assertNotIn("Yesterday (Live)", names)

class LRCLIBAPITests(TestCase):
    @patch("apps.lyrics.services.api.requests.Session")
    def test_fetch_lyrics_direct_success(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "trackName": "Yesterday",
            "artistName": "The Beatles",
            "albumName": "Help!",
            "duration": 125,
            "plainLyrics": "Yesterday all my troubles seemed so far away",
            "syncedLyrics": None,
            "instrumental": False,
        }
        mock_session.get.return_value = mock_response

        api = LRCLIBAPI()
        res = api._fetch_lyrics_direct("Yesterday", "The Beatles")
        
        self.assertIsNotNone(res)
        self.assertEqual(res.track_name, "Yesterday")
        self.assertEqual(res.plain_lyrics, "Yesterday all my troubles seemed so far away")



import threading
from unittest.mock import patch, MagicMock, PropertyMock

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.conf import settings

from apps.game.services import (
    GameService,
    is_correct_guess,
    calculate_score,
    _normalise,
    _DIFFICULTY_MULTIPLIER,
    _BASE_SCORE,
    _LIVES_BONUS_PER_LIFE,
    _STREAK_BONUS_PER_ROUND,
)
from apps.game.forms import LyricsGuessForm
from apps.users.models import UserScore

User = get_user_model()

_SIMPLE_STORAGE = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
}

FAKE_MUSIC = {
    "artist": "The Beatles",
    "song": "Yesterday",
    "lyrics": "________ all my troubles seemed so far away",
    "answer": "yesterday",
}

FULL_LIVES = {"1": True, "2": True, "3": True}
TWO_LIVES  = {"1": True, "2": True, "3": False}
ONE_LIFE   = {"1": True, "2": False, "3": False}
NO_LIVES   = {"1": False, "2": False, "3": False}

def _playing_session(
    client,
    *,
    artist="The Beatles",
    difficulty="medium",
    total_rounds=5,
    current_round=1,
    music=None,
    answered=False,
    lives=None,
    correct_count=0,
    round_summary=None,
    score=0,
    streak=0,
):
    s = client.session
    s["game_artist"]   = artist
    s["difficulty"]    = difficulty
    s["total_rounds"]  = total_rounds
    s["current_round"] = current_round
    s["lives"]         = lives or {"1": True, "2": True, "3": True}
    s["music"]         = music
    s["answered"]      = answered
    s["game_status"]   = "playing"
    s["correct_count"] = correct_count
    s["round_summary"] = round_summary or []
    s["score"]         = score
    s["streak"]        = streak
    s["score_saved"]   = False
    s["game_mode"] = "complete_lyrics"
    s.save()


class NormaliseTests(TestCase):

    def test_lowercases(self):
        self.assertEqual(_normalise("Hello World"), "hello world")

    def test_strips_accents(self):
        self.assertEqual(_normalise("naïve café"), "naive cafe")

    def test_strips_punctuation(self):
        self.assertEqual(_normalise("rock'n'roll!"), "rocknroll")

    def test_collapses_whitespace(self):
        self.assertEqual(_normalise("  too   many   spaces  "), "too many spaces")

    def test_empty_string(self):
        self.assertEqual(_normalise(""), "")

    def test_only_punctuation_becomes_empty(self):
        self.assertEqual(_normalise("!!!???..."), "")

    def test_unicode_symbols_stripped(self):
        self.assertEqual(_normalise("★ shining ★"), "shining")

    def test_mixed_case_and_accents(self):
        self.assertEqual(_normalise("Ünïcödë"), "unicode")

    def test_numbers_preserved(self):
        self.assertEqual(_normalise("99 problems"), "99 problems")

    def test_tab_and_newline_collapsed(self):
        self.assertEqual(_normalise("line1\nline2\ttab"), "line1 line2 tab")


class IsCorrectGuessTests(TestCase):

    def test_exact_match(self):
        self.assertTrue(is_correct_guess("beautiful", "beautiful"))

    def test_case_insensitive(self):
        self.assertTrue(is_correct_guess("Beautiful", "beautiful"))
        self.assertTrue(is_correct_guess("BEAUTIFUL", "beautiful"))
        self.assertTrue(is_correct_guess("bEaUtIfUl", "beautiful"))

    def test_leading_trailing_whitespace(self):
        self.assertTrue(is_correct_guess("  beautiful  ", "beautiful"))

    def test_accent_stripped_guess(self):
        self.assertTrue(is_correct_guess("naive", "naïve"))

    def test_accent_stripped_answer(self):
        self.assertTrue(is_correct_guess("naïve", "naive"))

    def test_both_accented(self):
        self.assertTrue(is_correct_guess("café", "cafe"))

    def test_apostrophe_in_guess_stripped(self):
        self.assertTrue(is_correct_guess("lovin'", "loving"))

    def test_hyphen_stripped(self):
        self.assertTrue(is_correct_guess("rock-n-roll", "rocknroll"))

    def test_answer_contains_guess(self):
        self.assertTrue(is_correct_guess("lovin", "loving"))

    def test_guess_too_short_for_substring_rule(self):
        self.assertFalse(is_correct_guess("lo", "loving"))

    def test_guess_less_than_70_percent_of_answer(self):
        self.assertFalse(is_correct_guess("yes", "yesterday"))

    def test_substring_at_exactly_70_percent(self):
        self.assertTrue(is_correct_guess("yesterd", "yesterday"))

    def test_one_char_typo(self):
        self.assertTrue(is_correct_guess("yesterdey", "yesterday"))

    def test_transposition(self):
        self.assertTrue(is_correct_guess("beutiful", "beautiful"))

    def test_double_letter_dropped(self):
        self.assertTrue(is_correct_guess("beatiful", "beautiful"))

    def test_extra_letter_appended(self):
        self.assertTrue(is_correct_guess("beautifull", "beautiful"))

    def test_clearly_wrong_answer(self):
        self.assertFalse(is_correct_guess("elephant", "beautiful"))

    def test_completely_different_word(self):
        self.assertFalse(is_correct_guess("xylophone", "yesterday"))

    def test_empty_string_is_wrong(self):
        self.assertFalse(is_correct_guess("", "beautiful"))

    def test_whitespace_only_is_wrong(self):
        self.assertFalse(is_correct_guess("   ", "beautiful"))

    def test_single_letter_cheat_rejected(self):
        self.assertFalse(is_correct_guess("a", "beautiful"))
        self.assertFalse(is_correct_guess("e", "yesterday"))

    @override_settings(GAME_FUZZY_THRESHOLD=1.0)
    def test_strict_threshold_rejects_near_miss(self):
        self.assertFalse(is_correct_guess("yesterdey", "yesterday"))

    @override_settings(GAME_FUZZY_THRESHOLD=0.5)
    def test_loose_threshold_accepts_rough_match(self):
        self.assertTrue(is_correct_guess("ystrdy", "yesterday"))

    def test_multi_word_exact(self):
        self.assertTrue(is_correct_guess("rolling stones", "rolling stones"))

    def test_multi_word_case_insensitive(self):
        self.assertTrue(is_correct_guess("Rolling Stones", "rolling stones"))


class CalculateScoreTests(TestCase):

    def _score(self, difficulty, lives, streak):
        return calculate_score(difficulty, lives, streak)

    def test_easy_full_lives_streak_1(self):
        # (100 + 3*10 + 1*15) * 1.0 = 145
        self.assertEqual(self._score("easy", FULL_LIVES, 1), 145)

    def test_medium_full_lives_streak_1(self):
        # (100 + 30 + 15) * 1.5 = 217.5 → 217
        self.assertEqual(self._score("medium", FULL_LIVES, 1), 217)

    def test_hard_full_lives_streak_1(self):
        # (100 + 30 + 15) * 2.5 = 362.5 → 362
        self.assertEqual(self._score("hard", FULL_LIVES, 1), 362)

    def test_insane_full_lives_streak_1(self):
        # (100 + 30 + 15) * 4.0 = 580
        self.assertEqual(self._score("insane", FULL_LIVES, 1), 580)

    def test_two_lives_reduces_score(self):
        full = self._score("medium", FULL_LIVES, 1)
        two  = self._score("medium", TWO_LIVES, 1)
        self.assertEqual(full - two, int(_LIVES_BONUS_PER_LIFE * _DIFFICULTY_MULTIPLIER["medium"]))

    def test_one_life_reduces_score(self):
        full = self._score("medium", FULL_LIVES, 1)
        one  = self._score("medium", ONE_LIFE, 1)
        self.assertEqual(full - one, int(2 * _LIVES_BONUS_PER_LIFE * _DIFFICULTY_MULTIPLIER["medium"]))

    def test_zero_lives_gives_base_score_only(self):
        # (100 + 0 + 15) * 1.0 = 115
        self.assertEqual(self._score("easy", NO_LIVES, 1), 115)

    def test_streak_5_vs_streak_1(self):
        s1 = self._score("medium", FULL_LIVES, 1)
        s5 = self._score("medium", FULL_LIVES, 5)
        diff = s5 - s1
        self.assertEqual(diff, int(4 * _STREAK_BONUS_PER_ROUND * _DIFFICULTY_MULTIPLIER["medium"]))

    def test_streak_zero(self):
        # (100 + 30 + 0) * 1.0 = 130
        self.assertEqual(self._score("easy", FULL_LIVES, 0), 130)

    def test_large_streak_insane(self):
        score = self._score("insane", FULL_LIVES, 10)
        expected = int((_BASE_SCORE + 3 * _LIVES_BONUS_PER_LIFE + 10 * _STREAK_BONUS_PER_ROUND) * 4.0)
        self.assertEqual(score, expected)

    def test_unknown_difficulty_falls_back_to_1x(self):
        unknown = self._score("legendary", FULL_LIVES, 1)
        easy    = self._score("easy", FULL_LIVES, 1)
        self.assertEqual(unknown, easy)

    def test_returns_int(self):
        self.assertIsInstance(self._score("hard", FULL_LIVES, 3), int)

    def test_score_always_positive(self):
        self.assertGreater(self._score("easy", NO_LIVES, 0), 0)

    def test_all_difficulties_ordered(self):
        easy   = self._score("easy",   FULL_LIVES, 1)
        medium = self._score("medium", FULL_LIVES, 1)
        hard   = self._score("hard",   FULL_LIVES, 1)
        insane = self._score("insane", FULL_LIVES, 1)
        self.assertLess(easy, medium)
        self.assertLess(medium, hard)
        self.assertLess(hard, insane)


class RemoveLiveTests(TestCase):

    def setUp(self):
        self.svc = GameService()

    def test_removes_highest_key_first(self):
        lives, over = self.svc.remove_live({"1": True, "2": True, "3": True})
        self.assertFalse(lives["3"])
        self.assertTrue(lives["2"])
        self.assertTrue(lives["1"])
        self.assertFalse(over)

    def test_removes_second_life(self):
        lives, over = self.svc.remove_live({"1": True, "2": True, "3": False})
        self.assertFalse(lives["2"])
        self.assertTrue(lives["1"])
        self.assertFalse(over)

    def test_removes_last_life_triggers_game_over(self):
        lives, over = self.svc.remove_live({"1": True, "2": False, "3": False})
        self.assertFalse(lives["1"])
        self.assertTrue(over)

    def test_already_all_dead_returns_game_over(self):
        lives, over = self.svc.remove_live({"1": False, "2": False, "3": False})
        self.assertTrue(over)

    def test_does_not_mutate_input(self):
        original = {"1": True, "2": True, "3": True}
        before = original.copy()
        self.svc.remove_live(original)
        self.assertEqual(original, before)

    def test_sequential_removal_reaches_game_over(self):
        lives = {"1": True, "2": True, "3": True}
        for _ in range(2):
            lives, over = self.svc.remove_live(lives)
            self.assertFalse(over)
        lives, over = self.svc.remove_live(lives)
        self.assertTrue(over)
        self.assertEqual(list(lives.values()), [False, False, False])

class GenerateRoundDataTests(TestCase):

    def setUp(self):
        self.svc = GameService()

    def _mock_lyrics(self, lines):
        lr = MagicMock()
        lr.has_lyrics.return_value = True
        lr.random_excerpt.return_value = lines
        lr.artist_name = "The Beatles"
        lr.track_name  = "Yesterday"
        return lr

    @patch.object(GameService, '__init__', lambda self: None)
    def _make_svc(self, lastfm_mock, lrclib_mock):
        svc = GameService.__new__(GameService)
        svc.lastfm = lastfm_mock
        svc.lrclib = lrclib_mock
        return svc

    def test_returns_none_when_no_track(self):
        with patch.object(self.svc, 'lastfm') as lf:
            lf.get_track.return_value = None
            result = self.svc.generate_round_data("Unknown", "easy")
        self.assertIsNone(result)

    def test_returns_none_when_track_missing_name(self):
        with patch.object(self.svc, 'lastfm') as lf:
            lf.get_track.return_value = {"playcount": 100}
            result = self.svc.generate_round_data("Artist", "easy")
        self.assertIsNone(result)

    def test_returns_none_when_no_lyrics(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Song"}
            ll.get_lyrics_for_track.return_value = None
            result = self.svc.generate_round_data("Artist", "easy")
        self.assertIsNone(result)

    def test_returns_none_when_lyrics_empty(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Song"}
            lr = MagicMock()
            lr.has_lyrics.return_value = False
            ll.get_lyrics_for_track.return_value = lr
            result = self.svc.generate_round_data("Artist", "easy")
        self.assertIsNone(result)

    def test_returns_none_when_no_excerpt(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Song"}
            lr = MagicMock()
            lr.has_lyrics.return_value = True
            lr.random_excerpt.return_value = None
            ll.get_lyrics_for_track.return_value = lr
            result = self.svc.generate_round_data("Artist", "easy")
        self.assertIsNone(result)

    def test_returns_none_when_all_words_are_filler(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Song"}
            ll.get_lyrics_for_track.return_value = self._mock_lyrics(
                ["the oh yeah and so", "yeah yeah yeah", "oh oh oh"]
            )
            result = self.svc.generate_round_data("Artist", "easy")
        self.assertIsNone(result)

    def test_happy_path_returns_correct_shape(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Yesterday"}
            ll.get_lyrics_for_track.return_value = self._mock_lyrics(
                [
                    "Yesterday all my troubles seemed so far away",
                    "Now it looks as though they are here to stay",
                    "Oh I believe in yesterday",
                ]
            )
            result = self.svc.generate_round_data("The Beatles", "easy")

        self.assertIsNotNone(result)
        self.assertIn("artist", result)
        self.assertIn("song", result)
        self.assertIn("lyrics", result)
        self.assertIn("answer", result)

    def test_answer_is_lowercase(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Song"}
            ll.get_lyrics_for_track.return_value = self._mock_lyrics(
                ["Somewhere over the Rainbow", "Way up high", "There is a land that I heard of"]
            )
            result = self.svc.generate_round_data("Artist", "easy")

        if result:
            self.assertEqual(result["answer"], result["answer"].lower())

    def test_blanked_lyrics_contains_placeholder(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Song"}
            ll.get_lyrics_for_track.return_value = self._mock_lyrics(
                ["Somewhere over the Rainbow", "Way up high", "There is a land that I heard of"]
            )
            result = self.svc.generate_round_data("Artist", "easy")

        if result:
            self.assertIn("________", result["lyrics"])

    def test_answer_not_in_blanked_lyrics_as_whole_word(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Song"}
            ll.get_lyrics_for_track.return_value = self._mock_lyrics(
                ["Somewhere over the Rainbow", "Way up high", "There is a land that I heard of"]
            )
            result = self.svc.generate_round_data("Artist", "easy")

        if result:
            import re
            answer = result["answer"]
            pattern = re.compile(r'\b' + re.escape(answer) + r'\b', re.IGNORECASE)
            self.assertIsNone(pattern.search(result["lyrics"]))

    def test_exception_in_lastfm_returns_none(self):
        with patch.object(self.svc, 'lastfm') as lf:
            lf.get_track.side_effect = Exception("network error")
            result = self.svc.generate_round_data("Artist", "easy")
        self.assertIsNone(result)

    def test_fallback_artist_name_from_track(self):
        with patch.object(self.svc, 'lastfm') as lf, \
            patch.object(self.svc, 'lrclib') as ll:
            lf.get_track.return_value = {"name": "Song"}
            lr = self._mock_lyrics(
                ["Somewhere over the Rainbow", "Way up high", "There is a land that I heard of"]
            )
            lr.artist_name = None
            lr.track_name  = None
            ll.get_lyrics_for_track.return_value = lr
            result = self.svc.generate_round_data("FallbackArtist", "easy")

        if result:
            self.assertEqual(result["artist"], "FallbackArtist")
            self.assertEqual(result["song"], "Song")

class LyricsGuessFormTests(TestCase):

    def test_valid_guess(self):
        form = LyricsGuessForm(data={"guess": "hello"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["guess"], "hello")

    def test_empty_guess_invalid(self):
        form = LyricsGuessForm(data={"guess": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("guess", form.errors)

    def test_whitespace_only_invalid(self):
        form = LyricsGuessForm(data={"guess": "   "})
        self.assertFalse(form.is_valid())

    def test_max_length_255(self):
        form = LyricsGuessForm(data={"guess": "a" * 255})
        self.assertTrue(form.is_valid())

    def test_over_max_length_invalid(self):
        form = LyricsGuessForm(data={"guess": "a" * 256})
        self.assertFalse(form.is_valid())

    def test_missing_field_invalid(self):
        form = LyricsGuessForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn("Please enter a guess.", form.errors["guess"])

    def test_unicode_guess_valid(self):
        form = LyricsGuessForm(data={"guess": "naïve"})
        self.assertTrue(form.is_valid())

    def test_leading_trailing_whitespace_stripped(self):
        form = LyricsGuessForm(data={"guess": "  hello  "})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["guess"], "hello")


@override_settings(STORAGES=_SIMPLE_STORAGE)
class IndexViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("game:index")
        self.user = User.objects.create_user(
            username="player", email="player@test.com", password="pass123456789"
        )

    def test_get_anonymous_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/index.html")

    def test_context_defaults_for_anonymous(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["most_played_artist"], "None yet!")
        self.assertEqual(response.context["play_count"], 0)



    def test_most_played_artist_for_authenticated_user(self):
        self.client.force_login(self.user)
        UserScore.objects.create(user=self.user, artist="Radiohead", score=100, completed=True)
        UserScore.objects.create(user=self.user, artist="Radiohead", score=200, completed=True)
        UserScore.objects.create(user=self.user, artist="Blur",      score=300, completed=True)

        response = self.client.get(self.url)
        self.assertEqual(response.context["most_played_artist"], "Radiohead")
        self.assertEqual(response.context["play_count"], 2)

    def test_most_played_artist_defaults_when_no_scores(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.context["most_played_artist"], "None yet!")


@override_settings(STORAGES=_SIMPLE_STORAGE)
class LobbyViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("game:lobby")

    def test_get_renders_lobby(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/lobby.html")

    def test_post_empty_artist_shows_error(self):
        response = self.client.post(self.url, {"artist": "", "difficulty": "easy", "rounds": 5})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("artist" in m.lower() for m in msgs))

    def test_post_whitespace_artist_shows_error(self):
        response = self.client.post(self.url, {"artist": "   ", "difficulty": "easy", "rounds": 5})
        self.assertEqual(response.status_code, 200)

    def test_post_valid_redirects_to_game(self):
        response = self.client.post(self.url, {
            "artist": "The Beatles", "difficulty": "hard", "rounds": "7"
        })
        self.assertRedirects(response, reverse("game:game"))

    def test_post_valid_initialises_all_session_keys(self):
        self.client.post(self.url, {
            "artist": "The Beatles", "difficulty": "hard", "rounds": "7"
        })
        s = self.client.session
        self.assertEqual(s["game_artist"],   "The Beatles")
        self.assertEqual(s["difficulty"],    "hard")
        self.assertEqual(s["total_rounds"],  7)
        self.assertEqual(s["current_round"], 1)
        self.assertEqual(s["lives"],         {"1": True, "2": True, "3": True})
        self.assertEqual(s["game_status"],   "playing")
        self.assertEqual(s["score"],         0)
        self.assertEqual(s["streak"],        0)
        self.assertEqual(s["correct_count"], 0)
        self.assertFalse(s["answered"])
        self.assertFalse(s["score_saved"])
        self.assertIsNone(s["music"])
        self.assertEqual(s["round_summary"], [])

    def test_artist_name_titlecased(self):
        self.client.post(self.url, {
            "artist": "the beatles", "difficulty": "easy", "rounds": "3"
        })
        self.assertEqual(self.client.session["game_artist"], "The Beatles")

    def test_invalid_difficulty_defaults_to_medium(self):
        self.client.post(self.url, {
            "artist": "Blur", "difficulty": "godmode", "rounds": "3"
        })
        self.assertEqual(self.client.session["difficulty"], "medium")

    def test_all_valid_difficulties_accepted(self):
        for diff in ("easy", "medium", "hard", "insane"):
            self.client.post(self.url, {"artist": "Blur", "difficulty": diff, "rounds": "3"})
            self.assertEqual(self.client.session["difficulty"], diff)

    def test_rounds_clamped_to_20(self):
        self.client.post(self.url, {"artist": "Blur", "difficulty": "easy", "rounds": "99"})
        self.assertEqual(self.client.session["total_rounds"], 20)

    def test_rounds_clamped_to_minimum_1(self):
        self.client.post(self.url, {"artist": "Blur", "difficulty": "easy", "rounds": "0"})
        self.assertEqual(self.client.session["total_rounds"], 1)

    def test_non_numeric_rounds_defaults_to_5(self):
        self.client.post(self.url, {"artist": "Blur", "difficulty": "easy", "rounds": "abc"})
        self.assertEqual(self.client.session["total_rounds"], 5)

    def test_missing_rounds_defaults_to_5(self):
        self.client.post(self.url, {"artist": "Blur", "difficulty": "easy"})
        self.assertEqual(self.client.session["total_rounds"], 5)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class GameViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("game:game")

    def test_no_session_redirects_to_lobby(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))

    def test_wrong_status_redirects_to_lobby(self):
        session = self.client.session
        session["game_artist"]  = "Artist"
        session["game_status"]  = "lobby"
        session.save()
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))

    @patch("apps.game.views.GameService")
    def test_fetches_music_when_none_in_session(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        MockSvc.return_value.generate_round_data.assert_called_once()

    @patch("apps.game.views.GameService")
    def test_skips_fetch_when_music_in_session(self, MockSvc):
        _playing_session(self.client, music=FAKE_MUSIC)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        MockSvc.return_value.generate_round_data.assert_not_called()

    @patch("apps.game.views.GameService")
    def test_music_stored_in_session_after_fetch(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client)
        self.client.get(self.url)
        self.assertEqual(self.client.session["music"], FAKE_MUSIC)

    @patch("apps.game.views.GameService")
    def test_retries_up_to_3_times_on_none(self, MockSvc):
        MockSvc.return_value.generate_round_data.side_effect = [None, None, FAKE_MUSIC]
        _playing_session(self.client)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MockSvc.return_value.generate_round_data.call_count, 3)

    @patch("apps.game.views.GameService")
    def test_all_retries_fail_redirects_to_lobby(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = None
        _playing_session(self.client)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))
        self.assertEqual(self.client.session["game_status"], "lobby")

    @patch("apps.game.views.GameService")
    def test_round_exceeds_total_redirects_to_victory(self, MockSvc):
        _playing_session(self.client, current_round=6, total_rounds=5, music=FAKE_MUSIC)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:victory"))
        self.assertEqual(self.client.session["game_status"], "won")

    @patch("apps.game.views.GameService")
    def test_correct_guess_sets_answered(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC)
        self.client.post(self.url, {"guess": "yesterday"})
        self.assertTrue(self.client.session["answered"])

    @patch("apps.game.views.GameService")
    def test_correct_guess_increments_correct_count(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC, correct_count=2)
        self.client.post(self.url, {"guess": "yesterday"})
        self.assertEqual(self.client.session["correct_count"], 3)

    @patch("apps.game.views.GameService")
    def test_correct_guess_increments_streak(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC, streak=4)
        self.client.post(self.url, {"guess": "yesterday"})
        self.assertEqual(self.client.session["streak"], 5)

    @patch("apps.game.views.GameService")
    def test_correct_guess_adds_to_score(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC, score=100)
        self.client.post(self.url, {"guess": "yesterday"})
        self.assertGreater(self.client.session["score"], 100)

    @patch("apps.game.views.GameService")
    def test_correct_guess_appends_to_round_summary(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC)
        self.client.post(self.url, {"guess": "yesterday"})
        summary = self.client.session["round_summary"]
        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0]["correct"])
        self.assertIn("round_score", summary[0])
        self.assertEqual(summary[0]["answer"], "yesterday")

    @patch("apps.game.views.GameService")
    def test_fuzzy_guess_accepted(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC)
        self.client.post(self.url, {"guess": "yesterdey"})
        self.assertTrue(self.client.session["answered"])

    @patch("apps.game.views.GameService")
    def test_wrong_guess_resets_streak(self, MockSvc):
        instance = MockSvc.return_value
        instance.generate_round_data.return_value = FAKE_MUSIC
        instance.remove_live.return_value = (TWO_LIVES, False)
        _playing_session(self.client, music=FAKE_MUSIC, streak=5)
        self.client.post(self.url, {"guess": "completely_wrong_word"})
        self.assertEqual(self.client.session["streak"], 0)

    @patch("apps.game.views.GameService")
    def test_wrong_guess_calls_remove_live(self, MockSvc):
        instance = MockSvc.return_value
        instance.generate_round_data.return_value = FAKE_MUSIC
        instance.remove_live.return_value = (TWO_LIVES, False)
        _playing_session(self.client, music=FAKE_MUSIC)
        self.client.post(self.url, {"guess": "completely_wrong_word"})
        instance.remove_live.assert_called_once()

    @patch("apps.game.views.GameService")
    def test_wrong_guess_updates_lives_in_session(self, MockSvc):
        instance = MockSvc.return_value
        instance.generate_round_data.return_value = FAKE_MUSIC
        instance.remove_live.return_value = (TWO_LIVES, False)
        _playing_session(self.client, music=FAKE_MUSIC)
        self.client.post(self.url, {"guess": "completely_wrong_word"})
        self.assertEqual(self.client.session["lives"], TWO_LIVES)

    @patch("apps.game.views.GameService")
    def test_last_life_lost_redirects_to_game_over(self, MockSvc):
        instance = MockSvc.return_value
        instance.generate_round_data.return_value = FAKE_MUSIC
        instance.remove_live.return_value = (NO_LIVES, True)
        _playing_session(self.client, music=FAKE_MUSIC, lives=ONE_LIFE)
        response = self.client.post(self.url, {"guess": "completely_wrong_word"})
        self.assertRedirects(response, reverse("game:game_over"))
        self.assertEqual(self.client.session["game_status"], "lost")

    @patch("apps.game.views.GameService")
    def test_last_life_lost_appends_incorrect_to_summary(self, MockSvc):
        instance = MockSvc.return_value
        instance.generate_round_data.return_value = FAKE_MUSIC
        instance.remove_live.return_value = (NO_LIVES, True)
        _playing_session(self.client, music=FAKE_MUSIC, lives=ONE_LIFE)
        self.client.post(self.url, {"guess": "completely_wrong_word"})
        summary = self.client.session["round_summary"]
        self.assertEqual(len(summary), 1)
        self.assertFalse(summary[0]["correct"])

    @patch("apps.game.views.GameService")
    def test_action_next_advances_round(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC, answered=True, current_round=2)
        self.client.post(self.url, {"action": "next"})
        s = self.client.session
        self.assertEqual(s["current_round"], 3)
        self.assertIsNone(s["music"])
        self.assertFalse(s["answered"])

    @patch("apps.game.views.GameService")
    def test_action_next_ignored_when_not_answered(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC, answered=False, current_round=2)
        self.client.post(self.url, {"action": "next"})
        self.assertEqual(self.client.session["current_round"], 2)

    @patch("apps.game.views.GameService")
    def test_action_quit_resets_status(self, MockSvc):
        _playing_session(self.client, music=FAKE_MUSIC)
        response = self.client.post(self.url, {"action": "quit"})
        self.assertRedirects(response, reverse("game:lobby"))
        self.assertEqual(self.client.session["game_status"], "lobby")

    @patch("apps.game.views.GameService")
    def test_context_keys_present(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC)
        response = self.client.get(self.url)
        for key in ("music", "lives", "difficulty", "total_rounds",
                    "current_round", "game_artist", "answered", "form"):
            self.assertIn(key, response.context, msg=f"Missing context key: {key}")

    @patch("apps.game.views.GameService")
    def test_context_reflects_session(self, MockSvc):
        MockSvc.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(
            self.client, music=FAKE_MUSIC, difficulty="insane",
            current_round=3, total_rounds=10
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["difficulty"],    "insane")
        self.assertEqual(response.context["current_round"], 3)
        self.assertEqual(response.context["total_rounds"],  10)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class VictoryViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("game:victory")

    def _won_session(self, score=850, correct=4, rounds=5,
                    lives=None, artist="Radiohead", diff="medium"):
        s = self.client.session
        s["game_status"]   = "won"
        s["game_artist"]   = artist
        s["difficulty"]    = diff
        s["score"]         = score
        s["correct_count"] = correct
        s["total_rounds"]  = rounds
        s["lives"]         = lives or {"1": True, "2": True, "3": False}
        s["round_summary"] = []
        s["score_saved"]   = False
        s["game_mode"] = "complete_lyrics"
        s.save()

    def test_redirects_without_won_status(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))

    def test_renders_with_won_status(self):
        self._won_session()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/victory.html")

    def test_context_score(self):
        self._won_session(score=999)
        response = self.client.get(self.url)
        self.assertEqual(response.context["score"], 999)
        self.assertEqual(response.context["points"], 999)

    def test_context_lives_remaining(self):
        self._won_session(lives={"1": True, "2": True, "3": False})
        response = self.client.get(self.url)
        self.assertEqual(response.context["lives_remaining"], 2)

    def test_context_lives_remaining_all_alive(self):
        self._won_session(lives=FULL_LIVES)
        response = self.client.get(self.url)
        self.assertEqual(response.context["lives_remaining"], 3)

    def test_context_correct_count(self):
        self._won_session(correct=3, rounds=5)
        response = self.client.get(self.url)
        self.assertEqual(response.context["correct_count"], 3)
        self.assertEqual(response.context["total_rounds"], 5)

    def test_context_game_artist(self):
        self._won_session(artist="Pink Floyd")
        response = self.client.get(self.url)
        self.assertEqual(response.context["game_artist"], "Pink Floyd")


@override_settings(STORAGES=_SIMPLE_STORAGE)
class GameOverViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("game:game_over")

    def _lost_session(self, score=217, correct=1, rounds=5,
                    lives=None, artist="Pink Floyd", diff="hard"):
        s = self.client.session
        s["game_status"]   = "lost"
        s["game_artist"]   = artist
        s["difficulty"]    = diff
        s["score"]         = score
        s["correct_count"] = correct
        s["total_rounds"]  = rounds
        s["current_round"] = 3
        s["lives"]         = lives or NO_LIVES
        s["round_summary"] = []
        s["score_saved"]   = False
        s["game_mode"] = "complete_lyrics"
        s.save()

    def test_redirects_without_lost_status(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))

    def test_renders_with_lost_status(self):
        self._lost_session()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/game-over.html")

    def test_context_score(self):
        self._lost_session(score=500)
        response = self.client.get(self.url)
        self.assertEqual(response.context["score"], 500)

    def test_context_lives_lost_all(self):
        self._lost_session(lives=NO_LIVES)
        response = self.client.get(self.url)
        self.assertEqual(response.context["lives_lost"], 3)

    def test_context_lives_lost_one(self):
        self._lost_session(lives={"1": False, "2": True, "3": True})
        response = self.client.get(self.url)
        self.assertEqual(response.context["lives_lost"], 1)

    def test_context_game_artist(self):
        self._lost_session(artist="Muse")
        response = self.client.get(self.url)
        self.assertEqual(response.context["game_artist"], "Muse")


@override_settings(STORAGES=_SIMPLE_STORAGE)
class ScorePersistenceTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="tester", email="test@example.com", password="supersecretpass123"
        )

    def _won_session(self, authenticated=True, score=500):
        if authenticated:
            self.client.force_login(self.user)
        s = self.client.session
        s["game_status"]   = "won"
        s["game_artist"]   = "Radiohead"
        s["difficulty"]    = "hard"
        s["score"]         = score
        s["correct_count"] = 5
        s["total_rounds"]  = 5
        s["lives"]         = FULL_LIVES
        s["round_summary"] = []
        s["score_saved"]   = False
        s["game_mode"] = "complete_lyrics"
        s.save()

    def _lost_session(self, authenticated=True, score=217):
        if authenticated:
            self.client.force_login(self.user)
        s = self.client.session
        s["game_status"]   = "lost"
        s["game_artist"]   = "Radiohead"
        s["difficulty"]    = "medium"
        s["score"]         = score
        s["correct_count"] = 2
        s["total_rounds"]  = 5
        s["current_round"] = 3
        s["lives"]         = NO_LIVES
        s["round_summary"] = []
        s["score_saved"]   = False
        s["game_mode"] = "complete_lyrics"
        s.save()

    def test_victory_saves_score_authenticated(self):
        self._won_session(score=500)
        self.client.get(reverse("game:victory"))
        self.assertEqual(UserScore.objects.filter(user=self.user).count(), 1)
        obj = UserScore.objects.get(user=self.user)
        self.assertEqual(obj.game_mode, "complete_lyrics")
        self.assertEqual(obj.score, 500)
        self.assertTrue(obj.completed)
        self.assertEqual(obj.artist, "Radiohead")
        self.assertEqual(obj.difficulty, "hard")

    def test_victory_no_save_for_anonymous(self):
        self._won_session(authenticated=False)
        self.client.get(reverse("game:victory"))
        self.assertEqual(UserScore.objects.count(), 0)

    def test_victory_no_double_save_on_refresh(self):
        self._won_session()
        self.client.get(reverse("game:victory"))
        self.client.get(reverse("game:victory"))
        self.assertEqual(UserScore.objects.filter(user=self.user).count(), 1)

    def test_victory_score_saved_flag_set(self):
        self._won_session()
        self.client.get(reverse("game:victory"))
        self.assertTrue(self.client.session["score_saved"])

    def test_game_over_saves_score_authenticated(self):
        self._lost_session(score=217)
        self.client.get(reverse("game:game_over"))
        self.assertEqual(UserScore.objects.filter(user=self.user).count(), 1)
        obj = UserScore.objects.get(user=self.user)
        self.assertEqual(obj.score, 217)
        self.assertFalse(obj.completed)

    def test_game_over_no_save_for_anonymous(self):
        self._lost_session(authenticated=False)
        self.client.get(reverse("game:game_over"))
        self.assertEqual(UserScore.objects.count(), 0)

    def test_game_over_no_double_save_on_refresh(self):
        self._lost_session()
        self.client.get(reverse("game:game_over"))
        self.client.get(reverse("game:game_over"))
        self.assertEqual(UserScore.objects.filter(user=self.user).count(), 1)

    def test_game_over_score_saved_flag_set(self):
        self._lost_session()
        self.client.get(reverse("game:game_over"))
        self.assertTrue(self.client.session["score_saved"])

    def test_score_zero_still_saved(self):
        self._won_session(score=0)
        self.client.get(reverse("game:victory"))
        self.assertEqual(UserScore.objects.get(user=self.user).score, 0)

    def test_large_score_saved(self):
        self._won_session(score=99999)
        self.client.get(reverse("game:victory"))
        self.assertEqual(UserScore.objects.get(user=self.user).score, 99999)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class HistoryViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("game:history")
        self.user = User.objects.create_user(
            username="player1", email="p1@test.com", password="pass123456789"
        )
        self.other_user = User.objects.create_user(
            username="player2", email="p2@test.com", password="pass123456789"
        )

    def test_anonymous_user_renders_cta(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/history.html")
        self.assertFalse(response.context["is_authenticated"])

    def test_authenticated_user_renders_history(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="Radiohead", score=300,
            correct_count=3, total_rounds=3, completed=True, game_mode="complete_lyrics"
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_authenticated"])
        self.assertEqual(response.context["total_games"], 1)
        self.assertEqual(response.context["highest_score"], 300)
        self.assertEqual(response.context["avg_accuracy"], 100.0)
        self.assertEqual(response.context["victory_rate"], 100.0)
        self.assertEqual(len(response.context["page_obj"]), 1)

    def test_security_isolation_of_scores(self):
        UserScore.objects.create(
            user=self.user, artist="Radiohead", score=300,
            correct_count=3, total_rounds=3, completed=True
        )
        UserScore.objects.create(
            user=self.other_user, artist="Blur", score=500,
            correct_count=3, total_rounds=3, completed=True
        )

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        scores = list(response.context["page_obj"])
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0].artist, "Radiohead")
        self.assertEqual(response.context["total_games"], 1)

    def test_metrics_calculation(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="Radiohead", score=300,
            correct_count=3, total_rounds=4, completed=True
        )
        UserScore.objects.create(
            user=self.user, artist="Blur", score=100,
            correct_count=1, total_rounds=4, completed=False
        )

        response = self.client.get(self.url)
        self.assertEqual(response.context["total_games"], 2)
        self.assertEqual(response.context["highest_score"], 300)
        self.assertEqual(response.context["victory_rate"], 50.0)
        self.assertEqual(response.context["avg_accuracy"], 75.0)

    def test_metrics_calculation_empty_history(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.context["total_games"], 0)
        self.assertEqual(response.context["highest_score"], 0)
        self.assertEqual(response.context["avg_accuracy"], 0.0)
        self.assertEqual(response.context["victory_rate"], 0.0)

    def test_metrics_calculation_only_incomplete_games(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="Radiohead", score=100,
            correct_count=1, total_rounds=4, completed=False
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["total_games"], 1)
        self.assertEqual(response.context["highest_score"], 0)
        self.assertEqual(response.context["avg_accuracy"], 0.0)
        self.assertEqual(response.context["victory_rate"], 0.0)

    def test_metrics_calculation_zero_rounds_protection(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="Radiohead", score=500,
            correct_count=0, total_rounds=0, completed=True
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["total_games"], 1)
        self.assertEqual(response.context["highest_score"], 500)
        self.assertEqual(response.context["avg_accuracy"], 0.0)
        self.assertEqual(response.context["victory_rate"], 100.0)

    def test_filter_by_mode_and_difficulty(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="Radiohead", score=300,
            completed=True, game_mode="complete_lyrics", difficulty="medium"
        )
        UserScore.objects.create(
            user=self.user, artist="Blur", score=200,
            completed=True, game_mode="guess_song", difficulty="easy"
        )

        response = self.client.get(self.url + "?mode=guess_song")
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertEqual(response.context["page_obj"][0].artist, "Blur")

        response = self.client.get(self.url + "?difficulty=medium")
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertEqual(response.context["page_obj"][0].artist, "Radiohead")

    def test_pagination(self):
        self.client.force_login(self.user)
        for i in range(20):
            UserScore.objects.create(
                user=self.user, artist=f"Artist {i}", score=i * 10, completed=True
            )

        response = self.client.get(self.url)
        self.assertEqual(len(response.context["page_obj"]), 15)

        response = self.client.get(self.url + "?page=2")
        self.assertEqual(len(response.context["page_obj"]), 5)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class DailyChallengeViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("game:start_daily_challenge")
        self.user = User.objects.create_user(
            username="player", email="player@test.com", password="pass123456789"
        )

    def test_anonymous_redirects(self):
        response = self.client.post(self.url, {"mode": "complete_lyrics"})
        self.assertEqual(response.status_code, 302)

    def test_authenticated_starts_daily(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"mode": "complete_lyrics"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get("is_daily"))
        self.assertEqual(self.client.session.get("game_mode"), "complete_lyrics")
        self.assertEqual(self.client.session.get("total_rounds"), settings.DAILY_ROUND_COUNT)
        self.assertEqual(self.client.session.get("difficulty"), settings.DAILY_DIFFICULTY)

    def test_prevents_duplicate_daily(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="Radiohead", score=300,
            completed=True, is_daily=True, game_mode="complete_lyrics"
        )
        response = self.client.post(self.url, {"mode": "complete_lyrics"})
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(self.client.session.get("is_daily"), True)

    @patch("apps.game.services.GameService.generate_round_data")
    def test_deterministic_round_generation(self, mock_generate_round):
        mock_generate_round.side_effect = lambda artist, difficulty: {
            "artist": artist,
            "song": "Fake Song",
            "lyrics": "Fake Lyrics...",
            "answer": "fake",
            "mode": "complete_lyrics",
        }

        service = GameService()
        res1 = service.generate_deterministic_round_data("Radiohead", "medium", "2026-05-30", 1, "complete_lyrics")
        res2 = service.generate_deterministic_round_data("Radiohead", "medium", "2026-05-30", 1, "complete_lyrics")

        self.assertEqual(res1, res2)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class DailyChallengeComprehensiveTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="player2", email="player2@test.com", password="pass123456789"
        )
        self.client.force_login(self.user)

    def test_mutual_exclusion_of_daily_challenge_modes(self):
        UserScore.objects.create(
            user=self.user,
            artist="Radiohead",
            score=300,
            completed=True,
            is_daily=True,
            game_mode="guess_song"
        )

        response_guess = self.client.post(reverse("game:start_daily_challenge"), {"mode": "guess_song"})
        response_lyrics = self.client.post(reverse("game:start_daily_challenge"), {"mode": "complete_lyrics"})

        self.assertEqual(response_guess.status_code, 302)
        self.assertEqual(response_lyrics.status_code, 302)

        self.assertNotEqual(self.client.session.get("is_daily"), True)

    def test_daily_lobby_ui_after_completed_daily_guess_song(self):
        summary_data = [
            {"artist": "The Beatles", "song": "Yesterday", "answer": "Yesterday", "correct": True, "mode": "guess_song"}
        ]
        UserScore.objects.create(
            user=self.user,
            artist="The Beatles",
            score=100,
            correct_count=1,
            total_rounds=1,
            completed=True,
            is_daily=True,
            game_mode="guess_song",
            summary_data=summary_data
        )

        response = self.client.get(reverse("game:daily_lobby"))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        self.assertIn("COMPLETED", content)
        self.assertIn("Song: Yesterday", content)
        self.assertNotIn("action=\"/daily/start/\"", content)
        self.assertNotIn("Copy Score", content)
        self.assertNotIn("copy-btn", content)

    def test_daily_lobby_ui_after_completed_daily_complete_lyrics(self):
        summary_data = [
            {"artist": "The Beatles", "song": "Yesterday", "answer": "yesterday", "correct": True, "mode": "complete_lyrics"}
        ]
        UserScore.objects.create(
            user=self.user,
            artist="The Beatles",
            score=100,
            correct_count=1,
            total_rounds=1,
            completed=True,
            is_daily=True,
            game_mode="complete_lyrics",
            summary_data=summary_data
        )

        response = self.client.get(reverse("game:daily_lobby"))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        self.assertIn("COMPLETED", content)
        self.assertIn("Lyric: \"yesterday\"", content)
        self.assertNotIn("action=\"/daily/start/\"", content)
        self.assertNotIn("Copy Score", content)
        self.assertNotIn("copy-btn", content)

    def test_game_over_saves_summary_data_daily(self):
        s = self.client.session
        s["game_status"] = "lost"
        s["game_artist"] = "The Beatles"
        s["difficulty"] = "medium"
        s["score"] = 0
        s["correct_count"] = 0
        s["total_rounds"] = 3
        s["lives"] = {"1": False, "2": False, "3": False}
        s["round_summary"] = [
            {"artist": "The Beatles", "song": "Yesterday", "answer": "yesterday", "correct": False, "mode": "complete_lyrics"}
        ]
        s["score_saved"] = False
        s["game_mode"] = "complete_lyrics"
        s["is_daily"] = True
        s.save()

        response = self.client.get(reverse("game:game_over"))
        self.assertEqual(response.status_code, 200)

        score = UserScore.objects.filter(user=self.user, is_daily=True).first()
        self.assertIsNotNone(score)
        self.assertFalse(score.completed)
        self.assertEqual(score.summary_data[0]["song"], "Yesterday")
        self.assertFalse(score.summary_data[0]["correct"])

    def test_victory_saves_summary_data_daily(self):
        s = self.client.session
        s["game_status"] = "won"
        s["game_artist"] = "The Beatles"
        s["difficulty"] = "medium"
        s["score"] = 150
        s["correct_count"] = 1
        s["total_rounds"] = 1
        s["lives"] = {"1": True, "2": True, "3": True}
        s["round_summary"] = [
            {"artist": "The Beatles", "song": "Yesterday", "answer": "yesterday", "correct": True, "mode": "complete_lyrics"}
        ]
        s["score_saved"] = False
        s["game_mode"] = "complete_lyrics"
        s["is_daily"] = True
        s.save()

        response = self.client.get(reverse("game:victory"))
        self.assertEqual(response.status_code, 200)

        score = UserScore.objects.filter(user=self.user, is_daily=True).first()
        self.assertIsNotNone(score)
        self.assertTrue(score.completed)
        self.assertEqual(score.summary_data[0]["song"], "Yesterday")
        self.assertTrue(score.summary_data[0]["correct"])
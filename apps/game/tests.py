from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

_SIMPLE_STORAGE = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
}

from apps.game.services import GameService, is_correct_guess, calculate_score
from apps.game.forms import LyricsGuessForm
from apps.users.models import UserScore

User = get_user_model()

FAKE_MUSIC = {
    "artist": "The Beatles",
    "song": "Yesterday",
    "lyrics": "________ all my troubles seemed so far away",
    "answer": "yesterday",
}

def _playing_session(client: Client, *, artist="The Beatles", difficulty="medium",
                    total_rounds=5, current_round=1, music=None, answered=False,
                    lives=None, correct_count=0, round_summary=None,
                    score=0, streak=0) -> None:
    session = client.session
    session["game_artist"] = artist
    session["difficulty"] = difficulty
    session["total_rounds"] = total_rounds
    session["current_round"] = current_round
    session["lives"] = lives or {"1": True, "2": True, "3": True}
    session["music"] = music
    session["answered"] = answered
    session["game_status"] = "playing"
    session["correct_count"] = correct_count
    session["round_summary"] = round_summary or []
    session["score"] = score
    session["streak"] = streak
    session["score_saved"] = False
    session.save()


class IsCorrectGuessTests(TestCase):

    def test_exact_match(self):
        self.assertTrue(is_correct_guess("beautiful", "beautiful"))

    def test_case_insensitive(self):
        self.assertTrue(is_correct_guess("Beautiful", "beautiful"))
        self.assertTrue(is_correct_guess("BEAUTIFUL", "beautiful"))

    def test_leading_trailing_whitespace(self):
        self.assertTrue(is_correct_guess("  beautiful  ", "beautiful"))

    def test_accent_stripping(self):
        self.assertTrue(is_correct_guess("naive", "naïve"))

    def test_punctuation_stripped(self):
        self.assertTrue(is_correct_guess("lovin", "lovin'"))

    def test_substring_match_contraction(self):
        self.assertTrue(is_correct_guess("lovin", "loving"))

    def test_fuzzy_near_miss(self):
        self.assertTrue(is_correct_guess("beutiful", "beautiful"))

    def test_clearly_wrong_answer(self):
        self.assertFalse(is_correct_guess("elephant", "beautiful"))

    def test_empty_guess_is_wrong(self):
        self.assertFalse(is_correct_guess("", "beautiful"))
        self.assertFalse(is_correct_guess("   ", "beautiful"))

    def test_single_char_off(self):
        self.assertTrue(is_correct_guess("yesterdey", "yesterday"))


class GameServiceTests(TestCase):
    def setUp(self):
        self.svc = GameService()

    def test_remove_live_loses_one_life(self):
        lives = {"1": True, "2": True, "3": True}

        lives, game_over = self.svc.remove_live(lives)
        self.assertFalse(lives["3"])
        self.assertTrue(lives["2"])
        self.assertTrue(lives["1"])
        self.assertFalse(game_over)

        lives, game_over = self.svc.remove_live(lives)
        self.assertFalse(lives["3"])
        self.assertFalse(lives["2"])
        self.assertTrue(lives["1"])
        self.assertFalse(game_over)

        lives, game_over = self.svc.remove_live(lives)
        self.assertFalse(lives["3"])
        self.assertFalse(lives["2"])
        self.assertFalse(lives["1"])
        self.assertTrue(game_over)

    def test_remove_live_already_dead(self):
        lives = {"1": False, "2": False, "3": False}
        lives, game_over = self.svc.remove_live(lives)
        self.assertTrue(game_over)


class CalculateScoreTests(TestCase):

    def _full_lives(self):
        return {"1": True, "2": True, "3": True}

    def test_easy_no_streak(self):
        # (100 + 3×10 + 1×15) × 1.0 = 145
        score = calculate_score("easy", self._full_lives(), streak=1)
        self.assertEqual(score, 145)

    def test_medium_no_streak(self):
        # (100 + 3×10 + 1×15) × 1.5 = 217
        score = calculate_score("medium", self._full_lives(), streak=1)
        self.assertEqual(score, 217)

    def test_hard_no_streak(self):
        # (100 + 3×10 + 1×15) × 2.5 = 362
        score = calculate_score("hard", self._full_lives(), streak=1)
        self.assertEqual(score, 362)

    def test_insane_no_streak(self):
        # (100 + 3×10 + 1×15) × 4.0 = 580
        self.assertEqual(calculate_score("insane", self._full_lives(), streak=1), 580)

    def test_streak_increases_score(self):
        s1 = calculate_score("medium", self._full_lives(), streak=1)
        s5 = calculate_score("medium", self._full_lives(), streak=5)
        self.assertGreater(s5, s1)

    def test_fewer_lives_lowers_score(self):
        full = calculate_score("medium", {"1": True, "2": True, "3": True}, streak=1)
        one_left = calculate_score("medium", {"1": True, "2": False, "3": False}, streak=1)
        self.assertGreater(full, one_left)

    def test_unknown_difficulty_defaults_to_easy_multiplier(self):
        known = calculate_score("easy", self._full_lives(), streak=1)
        unknown = calculate_score("legendary", self._full_lives(), streak=1)
        self.assertEqual(known, unknown)

    def test_returns_int(self):
        score = calculate_score("hard", self._full_lives(), streak=3)
        self.assertIsInstance(score, int)


class LyricsGuessFormTests(TestCase):
    def test_valid_guess(self):
        form = LyricsGuessForm(data={"guess": "hello"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["guess"], "hello")

    def test_empty_guess(self):
        form = LyricsGuessForm(data={"guess": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("guess", form.errors)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class LobbyViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("game:lobby")

    def test_get_renders_lobby(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/lobby.html")

    def test_rounds_clamped_to_20(self):
        self.client.post(self.url, {"artist": "Blur", "difficulty": "easy", "rounds": "99"})
        self.assertEqual(self.client.session["total_rounds"], 20)

    def test_post_no_artist_shows_error(self):
        response = self.client.post(self.url, {"artist": "", "difficulty": "easy", "rounds": 5})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/lobby.html")
        messages = list(response.context["messages"])
        self.assertTrue(any("artist" in str(m).lower() for m in messages))

    def test_post_valid_initialises_session_and_redirects(self):
        response = self.client.post(self.url, {
            "artist": "The Beatles",
            "difficulty": "hard",
            "rounds": "7",
        })
        self.assertRedirects(response, reverse("game:game"))
        session = self.client.session
        self.assertEqual(session["game_artist"], "The Beatles")
        self.assertEqual(session["difficulty"], "hard")
        self.assertEqual(session["total_rounds"], 7)
        self.assertEqual(session["current_round"], 1)
        self.assertEqual(session["game_status"], "playing")
        self.assertEqual(session["lives"], {"1": True, "2": True, "3": True})
        self.assertEqual(session["score"], 0)
        self.assertEqual(session["streak"], 0)

    def test_post_invalid_rounds_defaults_to_five(self):
        response = self.client.post(self.url, {
            "artist": "Radiohead",
            "difficulty": "medium",
            "rounds": "notanumber",
        })
        self.assertRedirects(response, reverse("game:game"))
        self.assertEqual(self.client.session["total_rounds"], 5)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class GameViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("game:game")

    def test_get_without_session_redirects_to_lobby(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))

    @patch("apps.game.views.GameService")
    def test_get_with_session_fetches_music_and_renders(self, MockService):
        MockService.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/game.html")
        self.assertEqual(response.context["music"], FAKE_MUSIC)

    @patch("apps.game.views.GameService")
    def test_get_skips_api_call_when_music_already_in_session(self, MockService):
        _playing_session(self.client, music=FAKE_MUSIC)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        MockService.return_value.generate_round_data.assert_not_called()

    @patch("apps.game.views.GameService")
    def test_correct_guess_marks_answered_and_increments_count(self, MockService):
        MockService.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC)

        response = self.client.post(self.url, {"guess": "yesterday"})
        self.assertEqual(response.status_code, 200)
        session = self.client.session
        self.assertTrue(session["answered"])
        self.assertEqual(session["correct_count"], 1)
        self.assertTrue(session["round_summary"][0]["correct"])
        self.assertIn("round_score", session["round_summary"][0])
        self.assertGreater(session["score"], 0)
        self.assertEqual(session["streak"], 1)

    @patch("apps.game.views.GameService")
    def test_fuzzy_guess_accepted(self, MockService):
        MockService.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC)

        response = self.client.post(self.url, {"guess": "yesterdey"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.session["answered"])
        self.assertEqual(self.client.session["correct_count"], 1)

    @patch("apps.game.views.GameService")
    def test_wrong_guess_removes_a_life(self, MockService):
        instance = MockService.return_value
        instance.generate_round_data.return_value = FAKE_MUSIC
        instance.remove_live.return_value = (
            {"1": True, "2": True, "3": False}, False
        )
        _playing_session(self.client, music=FAKE_MUSIC, streak=3)

        response = self.client.post(self.url, {"guess": "completely_wrong"})
        self.assertEqual(response.status_code, 200)
        instance.remove_live.assert_called_once()
        self.assertEqual(self.client.session["streak"], 0)

    @patch("apps.game.views.GameService")
    def test_third_wrong_guess_redirects_to_game_over(self, MockService):
        instance = MockService.return_value
        instance.generate_round_data.return_value = FAKE_MUSIC
        instance.remove_live.return_value = (
            {"1": False, "2": False, "3": False}, True
        )
        _playing_session(self.client, music=FAKE_MUSIC,
                        lives={"1": True, "2": False, "3": False})
        response = self.client.post(self.url, {"guess": "wrong"})
        self.assertRedirects(response, reverse("game:game_over"))
        self.assertEqual(self.client.session["game_status"], "lost")

    @patch("apps.game.views.GameService")
    def test_action_next_advances_round(self, MockService):
        MockService.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC, answered=True, current_round=2)

        response = self.client.post(self.url + "?action=next", {"action": "next"}, follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url)

        session = self.client.session

        self.assertEqual(session["current_round"], 3)
        self.assertIsNone(session["music"])
        self.assertFalse(session["answered"])

    @patch("apps.game.views.GameService")
    def test_action_quit_resets_status_and_redirects(self, MockService):
        MockService.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC)

        response = self.client.post(self.url + "?action=quit", {"action": "quit"})
        self.assertRedirects(response, reverse("game:lobby"))
        self.assertEqual(self.client.session["game_status"], "lobby")

    @patch("apps.game.views.GameService")
    def test_all_rounds_complete_redirects_to_victory(self, MockService):
        MockService.return_value.generate_round_data.return_value = FAKE_MUSIC
        _playing_session(self.client, music=FAKE_MUSIC, current_round=6, total_rounds=5)

        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:victory"))
        self.assertEqual(self.client.session["game_status"], "won")

    @patch("apps.game.views.GameService")
    def test_api_failure_redirects_to_lobby_with_error(self, MockService):
        MockService.return_value.generate_round_data.return_value = None
        _playing_session(self.client)

        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))
        self.assertEqual(self.client.session["game_status"], "lobby")


@override_settings(STORAGES=_SIMPLE_STORAGE)
class VictoryViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("game:victory")

    def test_redirects_without_won_status(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))

    def test_renders_with_won_status(self):
        session = self.client.session
        session["game_status"] = "won"
        session["total_rounds"] = 5
        session["correct_count"] = 4
        session["score"] = 850
        session["lives"] = {"1": True, "2": True, "3": False}
        session["round_summary"] = []
        session["difficulty"] = "medium"
        session["game_artist"] = "Radiohead"
        session.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/victory.html")
        self.assertEqual(response.context["correct_count"], 4)
        self.assertEqual(response.context["lives_remaining"], 2)
        self.assertEqual(response.context["game_artist"], "Radiohead")
        self.assertEqual(response.context["score"], 850)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class GameOverViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("game:game_over")

    def test_redirects_without_lost_status(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("game:lobby"))

    def test_renders_with_lost_status(self):
        session = self.client.session
        session["game_status"] = "lost"
        session["total_rounds"] = 5
        session["current_round"] = 3
        session["correct_count"] = 1
        session["score"] = 217
        session["lives"] = {"1": False, "2": False, "3": False}
        session["round_summary"] = []
        session["difficulty"] = "hard"
        session["game_artist"] = "Pink Floyd"
        session.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/game-over.html")
        self.assertEqual(response.context["correct_count"], 1)
        self.assertEqual(response.context["lives_lost"], 3)
        self.assertEqual(response.context["game_artist"], "Pink Floyd")
        self.assertEqual(response.context["score"], 217)

@override_settings(STORAGES=_SIMPLE_STORAGE)
class ScorePersistenceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            username="tester",
            password="supersecretpass123",
        )

    def _won_session(self, authenticated=True):
        if authenticated:
            self.client.force_login(self.user)
        s = self.client.session
        s["game_status"] = "won"
        s["game_artist"] = "Radiohead"
        s["difficulty"] = "hard"
        s["score"] = 500
        s["correct_count"] = 5
        s["total_rounds"] = 5
        s["lives"] = {"1": True, "2": True, "3": True}
        s["round_summary"] = []
        s["score_saved"] = False
        s.save()

    def _lost_session(self, authenticated=True):
        if authenticated:
            self.client.force_login(self.user)
        s = self.client.session
        s["game_status"] = "lost"
        s["game_artist"] = "Radiohead"
        s["difficulty"] = "medium"
        s["score"] = 217
        s["correct_count"] = 2
        s["total_rounds"] = 5
        s["current_round"] = 3
        s["lives"] = {"1": False, "2": False, "3": False}
        s["round_summary"] = []
        s["score_saved"] = False
        s.save()

    def test_victory_saves_score_for_authenticated_user(self):
        self._won_session()
        self.client.get(reverse("game:victory"))
        self.assertEqual(UserScore.objects.filter(user=self.user).count(), 1)
        obj = UserScore.objects.get(user=self.user)
        self.assertEqual(obj.score, 500)
        self.assertTrue(obj.completed)

    def test_victory_no_save_for_anonymous_user(self):
        self._won_session(authenticated=False)
        self.client.get(reverse("game:victory"))
        self.assertEqual(UserScore.objects.count(), 0)

    def test_victory_no_double_save_on_refresh(self):
        self._won_session()
        self.client.get(reverse("game:victory"))
        self.client.get(reverse("game:victory"))
        self.assertEqual(UserScore.objects.filter(user=self.user).count(), 1)

    def test_game_over_saves_score_for_authenticated_user(self):
        self._lost_session()
        self.client.get(reverse("game:game_over"))
        self.assertEqual(UserScore.objects.filter(user=self.user).count(), 1)
        obj = UserScore.objects.get(user=self.user)
        self.assertEqual(obj.score, 217)
        self.assertFalse(obj.completed)

    def test_game_over_no_save_for_anonymous_user(self):
        self._lost_session(authenticated=False)
        self.client.get(reverse("game:game_over"))
        self.assertEqual(UserScore.objects.count(), 0)

    def test_game_over_no_double_save_on_refresh(self):
        self._lost_session()
        self.client.get(reverse("game:game_over"))
        self.client.get(reverse("game:game_over"))
        self.assertEqual(UserScore.objects.filter(user=self.user).count(), 1)


class ProductionReadinessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testplayer", email="player@test.com", password="password123")
        self.user_hidden = User.objects.create_user(username="ghostplayer", email="ghost@test.com", password="password123")

        profile = self.user_hidden.profile
        profile.show_on_leaderboard = False
        profile.save()

        UserScore.objects.create(user=self.user, artist="Muse", score=500, completed=True)
        UserScore.objects.create(user=self.user_hidden, artist="Muse", score=1000, completed=True)
        UserScore.objects.create(user=self.user, artist="Radiohead", score=300, completed=False)

    def test_index_view_top_scores_in_context(self):
        response = self.client.get(reverse("game:index"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("top_scores", response.context)
        top_scores = response.context["top_scores"]
        self.assertEqual(len(top_scores), 1)
        self.assertEqual(top_scores[0].user, self.user)
        self.assertEqual(top_scores[0].score, 500)

    def test_victory_view_points_in_context(self):
        self.client.force_login(self.user)
        s = self.client.session
        s["game_status"] = "won"
        s["game_artist"] = "Muse"
        s["difficulty"] = "medium"
        s["score"] = 500
        s["correct_count"] = 5
        s["total_rounds"] = 5
        s["lives"] = {"1": True, "2": True, "3": True}
        s["round_summary"] = []
        s["score_saved"] = False
        s.save()

        response = self.client.get(reverse("game:victory"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("points", response.context)
        self.assertEqual(response.context["points"], 500)

    def test_leaderboard_view_status_and_filtering(self):
        response = self.client.get(reverse("game:leaderboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("top_scores", response.context)
        top_scores = response.context["top_scores"]
        self.assertEqual(len(top_scores), 1)
        self.assertEqual(top_scores[0].user, self.user)
        self.assertEqual(top_scores[0].score, 500)
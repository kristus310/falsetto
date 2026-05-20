from django.test import TestCase
from apps.game.services import GameService
from apps.game.forms import LyricsGuessForm

class GameServiceTests(TestCase):
    def setUp(self):
        self.game_service = GameService()

    def test_remove_live_loses_one_life(self):
        lives = {"1": True, "2": True, "3": True}
        
        lives, game_over = self.game_service.remove_live(lives)
        self.assertFalse(lives["3"])
        self.assertTrue(lives["2"])
        self.assertTrue(lives["1"])
        self.assertFalse(game_over)

        lives, game_over = self.game_service.remove_live(lives)
        self.assertFalse(lives["3"])
        self.assertFalse(lives["2"])
        self.assertTrue(lives["1"])
        self.assertFalse(game_over)

        lives, game_over = self.game_service.remove_live(lives)
        self.assertFalse(lives["3"])
        self.assertFalse(lives["2"])
        self.assertFalse(lives["1"])
        self.assertTrue(game_over)

class LyricsGuessFormTests(TestCase):
    def test_valid_guess(self):
        form = LyricsGuessForm(data={"guess": "hello"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["guess"], "hello")

    def test_empty_guess(self):
        form = LyricsGuessForm(data={"guess": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("guess", form.errors)



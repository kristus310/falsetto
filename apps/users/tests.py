from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.users.models import UserScore

User = get_user_model()

class UserScoreModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            username="tester",
            password="testpassword123",
        )

    def test_str(self):
        s = UserScore(user=self.user, artist="Radiohead", difficulty="hard", score=500)
        self.assertEqual(str(s), "test@example.com | Radiohead | hard | 500")

    def test_accuracy_full(self):
        s = UserScore(correct_count=4, total_rounds=5)
        self.assertEqual(s.accuracy, 80.0)

    def test_accuracy_zero_rounds(self):
        s = UserScore(correct_count=0, total_rounds=0)
        self.assertEqual(s.accuracy, 0.0)

    def test_anonymous_score_allowed(self):
        s = UserScore.objects.create(artist="Blur", difficulty="easy", score=100,
                                    correct_count=1, total_rounds=3, completed=False)
        self.assertIsNone(s.user)

    def test_default_ordering_is_score_descending(self):
        UserScore.objects.create(user=self.user, artist="A", score=100, difficulty="easy")
        UserScore.objects.create(user=self.user, artist="B", score=500, difficulty="hard")
        scores = list(UserScore.objects.filter(user=self.user))
        self.assertEqual(scores[0].score, 500)
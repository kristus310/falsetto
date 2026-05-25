from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.users.models import UserScore, UserProfile

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
        s = UserScore.objects.create(
            artist="Blur", difficulty="easy", score=100,
            correct_count=1, total_rounds=3, completed=False,
        )
        self.assertIsNone(s.user)

    def test_default_ordering_is_score_descending(self):
        UserScore.objects.create(user=self.user, artist="A", score=100, difficulty="easy")
        UserScore.objects.create(user=self.user, artist="B", score=500, difficulty="hard")
        scores = list(UserScore.objects.filter(user=self.user))
        self.assertEqual(scores[0].score, 500)


class UserProfileSignalTests(TestCase):
    def test_profile_created_on_user_creation(self):
        user = User.objects.create_user(
            email="signal@example.com",
            username="signaluser",
            password="testpassword123",
        )
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_profile_defaults(self):
        user = User.objects.create_user(
            email="defaults@example.com",
            username="defaultsuser",
            password="testpassword123",
        )
        profile = user.profile
        self.assertTrue(profile.show_on_leaderboard)
        self.assertFalse(profile.strict_matching)
        self.assertTrue(profile.email_notifications)

    def test_get_or_create_idempotent(self):
        user = User.objects.create_user(
            email="idem@example.com",
            username="idemuser",
            password="testpassword123",
        )
        user.save()
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)


class SettingsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="settings@example.com",
            username="settingsuser",
            password="testpassword123",
        )
        self.client.force_login(self.user)

    def test_settings_page_loads(self):
        response = self.client.get(reverse("users:settings"))
        self.assertEqual(response.status_code, 200)

    def test_update_username(self):
        response = self.client.post(reverse("users:settings"), {
            "action": "profile",
            "username": "newusername",
            "email": self.user.email,
        })
        self.assertRedirects(response, reverse("users:settings"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newusername")

    def test_update_preferences(self):
        response = self.client.post(reverse("users:settings"), {
            "action": "preferences",
            "strict_matching": "on",
        })
        self.assertRedirects(response, reverse("users:settings"))
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.strict_matching)
        self.assertFalse(self.user.profile.show_on_leaderboard)

    def test_delete_account_wrong_password(self):
        response = self.client.post(reverse("users:delete_account"), {
            "password": "wrongpassword",
        })
        self.assertRedirects(response, reverse("users:settings"))
        self.assertTrue(User.objects.filter(email="settings@example.com").exists())

    def test_delete_account_correct_password(self):
        response = self.client.post(reverse("users:delete_account"), {
            "password": "testpassword123",
        })
        self.assertRedirects(response, reverse("account_login"))
        self.assertFalse(User.objects.filter(email="settings@example.com").exists())

    def test_settings_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("users:settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login", response["Location"])
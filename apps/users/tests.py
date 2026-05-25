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


from unittest.mock import patch, MagicMock
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.test import override_settings
from core.email_backends import ResendEmailBackend
from email.mime.base import MIMEBase

class ResendEmailBackendTests(TestCase):
    @override_settings(RESEND_API_KEY=None)
    def test_backend_requires_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as context:
            ResendEmailBackend()
        self.assertIn("RESEND_API_KEY must be defined", str(context.exception))

    @override_settings(RESEND_API_KEY="re_test_key_123")
    @patch("resend.Emails.send")
    def test_send_basic_email(self, mock_send):
        mock_send.return_value = {"id": "email_id_123"}

        email = EmailMessage(
            subject="Test Subject",
            body="Hello, this is a test.",
            from_email="sender@example.com",
            to=["receiver@example.com"],
        )

        backend = ResendEmailBackend()
        sent_count = backend.send_messages([email])

        self.assertEqual(sent_count, 1)
        mock_send.assert_called_once_with({
            "from": "sender@example.com",
            "to": ["receiver@example.com"],
            "subject": "Test Subject",
            "text": "Hello, this is a test.",
        })

    @override_settings(RESEND_API_KEY="re_test_key_123")
    @patch("resend.Emails.send")
    def test_send_html_email(self, mock_send):
        mock_send.return_value = {"id": "email_id_html"}

        email = EmailMultiAlternatives(
            subject="HTML Subject",
            body="Text body",
            from_email="sender@example.com",
            to=["receiver@example.com"],
        )
        email.attach_alternative("<p>HTML body</p>", "text/html")

        backend = ResendEmailBackend()
        sent_count = backend.send_messages([email])

        self.assertEqual(sent_count, 1)
        mock_send.assert_called_once_with({
            "from": "sender@example.com",
            "to": ["receiver@example.com"],
            "subject": "HTML Subject",
            "text": "Text body",
            "html": "<p>HTML body</p>",
        })

    @override_settings(RESEND_API_KEY="re_test_key_123")
    @patch("resend.Emails.send")
    def test_send_email_with_cc_bcc_reply_to(self, mock_send):
        mock_send.return_value = {"id": "email_id_headers"}

        email = EmailMessage(
            subject="Subject",
            body="Body",
            from_email="sender@example.com",
            to=["receiver@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            reply_to=["reply@example.com"],
        )

        backend = ResendEmailBackend()
        sent_count = backend.send_messages([email])

        self.assertEqual(sent_count, 1)
        mock_send.assert_called_once_with({
            "from": "sender@example.com",
            "to": ["receiver@example.com"],
            "cc": ["cc@example.com"],
            "bcc": ["bcc@example.com"],
            "reply_to": ["reply@example.com"],
            "subject": "Subject",
            "text": "Body",
        })

    @override_settings(RESEND_API_KEY="re_test_key_123")
    @patch("resend.Emails.send")
    def test_send_email_with_attachments(self, mock_send):
        mock_send.return_value = {"id": "email_id_attachments"}

        email = EmailMessage(
            subject="Attachments",
            body="Body",
            from_email="sender@example.com",
            to=["receiver@example.com"],
        )

        email.attach("test.txt", "Hello World File", "text/plain")

        mime_attachment = MIMEBase("text", "plain")
        mime_attachment.set_payload(b"Binary Content")
        mime_attachment.add_header("Content-Disposition", "attachment", filename="mime.txt")
        email.attach(mime_attachment)

        backend = ResendEmailBackend()
        sent_count = backend.send_messages([email])

        self.assertEqual(sent_count, 1)

        import base64
        expected_txt_b64 = base64.b64encode(b"Hello World File").decode("utf-8")
        expected_mime_b64 = base64.b64encode(b"Binary Content").decode("utf-8")

        mock_send.assert_called_once_with({
            "from": "sender@example.com",
            "to": ["receiver@example.com"],
            "subject": "Attachments",
            "text": "Body",
            "attachments": [
                {"filename": "test.txt", "content": expected_txt_b64},
                {"filename": "mime.txt", "content": expected_mime_b64},
            ]
        })

    @override_settings(RESEND_API_KEY="re_test_key_123")
    @patch("resend.Emails.send")
    def test_fail_silently_behavior(self, mock_send):
        mock_send.side_effect = Exception("API Connection failure")

        email = EmailMessage(
            subject="Fail Test",
            body="Body",
            from_email="sender@example.com",
            to=["receiver@example.com"],
        )

        backend = ResendEmailBackend(fail_silently=False)
        with self.assertRaises(Exception):
            backend.send_messages([email])

        backend_silent = ResendEmailBackend(fail_silently=True)
        sent_count = backend_silent.send_messages([email])
        self.assertEqual(sent_count, 0)
import io
import os
import uuid
from unittest.mock import patch, MagicMock, PropertyMock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, FieldDoesNotExist
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.users.forms import (
    UsernameForm, EmailForm, AvatarForm, DeleteAccountForm, UserSignupForm
)
from apps.users.models import UserProfile, UserScore, avatar_upload_path
from apps.users.validators import validate_avatar
from apps.users.views import _compute_win_streak
from apps.users.adapters import AccountAdapter

User = get_user_model()

_SIMPLE_STORAGE = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
}

def _make_image_file(fmt="PNG", size=(100, 100), color=(255, 0, 0), filename="test.png"):
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    img.save(buf, format=fmt)
    buf.seek(0)
    content_type = {
        "PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"
    }.get(fmt, "image/png")
    return SimpleUploadedFile(filename, buf.read(), content_type=content_type)


def _make_oversized_image(max_dim=2000):
    return _make_image_file(size=(max_dim + 1, max_dim + 1))


class UserManagerTests(TestCase):

    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="pass12345678")

    def test_create_user_normalises_email(self):
        user = User.objects.create_user(
            email="Test@EXAMPLE.COM", username="norm", password="pass12345678"
        )
        self.assertEqual(user.email, "Test@example.com")

    def test_create_user_hashes_password(self):
        user = User.objects.create_user(
            email="hash@example.com", username="hashuser", password="plainpassword"
        )
        self.assertNotEqual(user.password, "plainpassword")
        self.assertTrue(user.check_password("plainpassword"))

    def test_create_user_is_not_staff_or_superuser(self):
        user = User.objects.create_user(
            email="normal@example.com", username="normal", password="pass12345678"
        )
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser_sets_flags(self):
        su = User.objects.create_superuser(
            email="su@example.com", username="superuser", password="pass12345678"
        )
        self.assertTrue(su.is_staff)
        self.assertTrue(su.is_superuser)
        self.assertTrue(su.is_active)

    def test_create_superuser_rejects_non_staff(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="su2@example.com", username="su2",
                password="pass12345678", is_staff=False
            )

    def test_create_superuser_rejects_non_superuser(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="su3@example.com", username="su3",
                password="pass12345678", is_superuser=False
            )

    def test_extra_fields_passed_through(self):
        user = User.objects.create_user(
            email="extra@example.com", username="extra",
            password="pass12345678", is_active=False
        )
        self.assertFalse(user.is_active)


class UserModelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com", username="testuser", password="pass12345678"
        )

    def test_str_returns_email(self):
        self.assertEqual(str(self.user), "user@example.com")

    def test_primary_key_is_uuid(self):
        self.assertIsInstance(self.user.pk, uuid.UUID)

    def test_email_is_username_field(self):
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_first_last_name_removed(self):
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field('first_name')
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field('last_name')

    def test_email_unique_enforced(self):
        from django.db import IntegrityError
        with self.assertRaises(Exception):
            User.objects.create_user(
                email="user@example.com", username="other", password="pass12345678"
            )

    def test_username_unique_enforced(self):
        with self.assertRaises(Exception):
            User.objects.create_user(
                email="other@example.com", username="testuser", password="pass12345678"
            )

    def test_username_max_length_50(self):
        field = User._meta.get_field("username")
        self.assertEqual(field.max_length, 50)


class UserProfileModelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="profile@example.com", username="profileuser", password="pass12345678"
        )

    def test_profile_auto_created_on_user_save(self):
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())

    def test_profile_created_only_once(self):
        self.user.save()
        self.assertEqual(UserProfile.objects.filter(user=self.user).count(), 1)

    def test_profile_defaults(self):
        profile = self.user.profile
        self.assertTrue(profile.show_on_leaderboard)
        self.assertTrue(self.user.profile.default_difficulty)
        self.assertTrue(self.user.profile.default_rounds)
        self.assertFalse(bool(profile.avatar))

    def test_str(self):
        self.assertEqual(str(self.user.profile), "profile@example.com - profile")

    def test_avatar_url_default_when_no_avatar(self):
        self.assertEqual(self.user.profile.avatar_url, "/static/images/user.png")

    def test_avatar_url_returns_url_when_avatar_set(self):
        profile = self.user.profile
        profile.avatar = MagicMock()
        profile.avatar.__bool__ = lambda s: True
        profile.avatar.url = "/media/avatars/test.png"
        self.assertEqual(profile.avatar_url, "/media/avatars/test.png")

    def test_profile_deleted_with_user(self):
        uid = self.user.pk
        self.user.delete()
        self.assertFalse(UserProfile.objects.filter(user_id=uid).exists())

    def test_one_to_one_relationship(self):
        self.assertEqual(self.user.profile.user, self.user)


class AvatarUploadPathTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="av@example.com", username="avuser", password="pass12345678"
        )

    def test_path_starts_with_avatars(self):
        path = avatar_upload_path(self.user.profile, "photo.jpg")
        self.assertTrue(path.startswith("avatars/"))

    def test_extension_preserved_lowercased(self):
        path = avatar_upload_path(self.user.profile, "photo.JPG")
        self.assertTrue(path.endswith(".jpg"))

    def test_png_extension_preserved(self):
        path = avatar_upload_path(self.user.profile, "photo.png")
        self.assertTrue(path.endswith(".png"))

    def test_filename_is_uuid(self):
        path = avatar_upload_path(self.user.profile, "photo.jpg")
        stem = path[len("avatars/"):-len(".jpg")]
        self.assertEqual(len(stem), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in stem))

    def test_unique_paths_for_same_filename(self):
        path1 = avatar_upload_path(self.user.profile, "photo.jpg")
        path2 = avatar_upload_path(self.user.profile, "photo.jpg")
        self.assertNotEqual(path1, path2)


class AvatarSignalTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="sig@example.com", username="siguser", password="pass12345678"
        )
        self.profile = self.user.profile

    def test_old_avatar_deleted_on_update(self):
        old_field = MagicMock()
        old_field.__bool__ = lambda s: True
        old_field.path = "/fake/old_avatar.jpg"
        old_field.__ne__ = lambda s, o: True

        with patch("apps.users.models.UserProfile.objects.get") as mock_get, \
            patch("apps.users.signals._delete_file") as mock_del:
            old_profile = MagicMock()
            old_profile.avatar = old_field
            mock_get.return_value = old_profile

            from apps.users.signals import delete_old_avatar_on_update
            delete_old_avatar_on_update(
                sender=UserProfile, instance=self.profile
            )
            mock_del.assert_called_once_with(old_field)

    def test_avatar_deleted_on_profile_delete(self):
        fake_field = MagicMock()
        fake_field.__bool__ = lambda s: True
        fake_field.path = "/fake/avatar.jpg"
        self.profile.avatar = fake_field

        with patch("apps.users.signals._delete_file") as mock_del:
            from apps.users.signals import delete_avatar_on_profile_delete
            delete_avatar_on_profile_delete(
                sender=UserProfile, instance=self.profile
            )
            mock_del.assert_called_once_with(fake_field)

    def test_delete_file_ignores_missing_file(self):
        field = MagicMock()
        field.__bool__ = lambda s: True
        field.path = "/this/does/not/exist.jpg"

        from apps.users.signals import _delete_file
        try:
            _delete_file(field)
        except Exception as e:
            self.fail(f"_delete_file raised unexpectedly: {e}")

    def test_delete_file_noop_on_empty_field(self):
        from apps.users.signals import _delete_file
        _delete_file(None)
        _delete_file("")

    def test_pre_save_skipped_for_new_profile(self):
        new_profile = UserProfile.__new__(UserProfile)
        new_profile.pk = None

        with patch("apps.users.signals._delete_file") as mock_del:
            from apps.users.signals import delete_old_avatar_on_update
            delete_old_avatar_on_update(sender=UserProfile, instance=new_profile)
            mock_del.assert_not_called()


@override_settings(AVATAR_MAX_SIZE_MB=2, AVATAR_MAX_DIMENSIONS=2000)
class ValidateAvatarTests(TestCase):

    def test_valid_png(self):
        f = _make_image_file("PNG", filename="test.png")
        try:
            validate_avatar(f)
        except ValidationError as e:
            self.fail(f"validate_avatar raised for valid PNG: {e}")

    def test_valid_jpeg(self):
        f = _make_image_file("JPEG", filename="test.jpg")
        try:
            validate_avatar(f)
        except ValidationError as e:
            self.fail(f"validate_avatar raised for valid JPEG: {e}")

    def test_valid_webp(self):
        f = _make_image_file("WEBP", filename="test.webp")
        try:
            validate_avatar(f)
        except ValidationError as e:
            self.fail(f"validate_avatar raised for valid WebP: {e}")

    def test_file_too_large_raises(self):
        f = _make_image_file("PNG", filename="big.png")
        f.size = 3 * 1024 * 1024
        with self.assertRaises(ValidationError) as ctx:
            validate_avatar(f)
        self.assertIn("too large", str(ctx.exception).lower())

    def test_dimensions_too_large_raises(self):
        f = _make_oversized_image(max_dim=2000)
        with self.assertRaises(ValidationError) as ctx:
            validate_avatar(f)
        self.assertIn("2000", str(ctx.exception))

    def test_invalid_image_data_raises(self):
        bad = SimpleUploadedFile("bad.png", b"this is not an image", content_type="image/png")
        with self.assertRaises(ValidationError) as ctx:
            validate_avatar(bad)
        self.assertIn("valid image", str(ctx.exception).lower())

    def test_unsupported_format_raises(self):
        from PIL import Image
        buf = io.BytesIO()
        img = Image.new("RGB", (10, 10))
        img.save(buf, format="BMP")
        buf.seek(0)
        f = SimpleUploadedFile("test.bmp", buf.read(), content_type="image/bmp")
        with self.assertRaises(ValidationError) as ctx:
            validate_avatar(f)
        self.assertIn("unsupported", str(ctx.exception).lower())

    def test_fieldfile_skips_validation(self):
        from django.db.models.fields.files import FieldFile
        ff = MagicMock(spec=FieldFile)
        try:
            validate_avatar(ff)
        except ValidationError as e:
            self.fail(f"validate_avatar should skip FieldFile: {e}")

    @override_settings(AVATAR_MAX_SIZE_MB=1)
    def test_respects_custom_max_size_setting(self):
        f = _make_image_file("PNG")
        f.size = 1.5 * 1024 * 1024
        with self.assertRaises(ValidationError) as ctx:
            validate_avatar(f)
        self.assertIn("1 MB", str(ctx.exception))

    @override_settings(AVATAR_MAX_DIMENSIONS=100)
    def test_respects_custom_max_dimensions_setting(self):
        f = _make_image_file("PNG", size=(101, 101))
        with self.assertRaises(ValidationError) as ctx:
            validate_avatar(f)
        self.assertIn("100", str(ctx.exception))


class UsernameFormTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", username="originalname", password="pass12345678"
        )

    def test_valid_username(self):
        form = UsernameForm(data={"username": "newname"}, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_empty_username_invalid(self):
        form = UsernameForm(data={"username": ""}, instance=self.user)
        self.assertFalse(form.is_valid())

    def test_username_too_long_invalid(self):
        form = UsernameForm(data={"username": "a" * 51}, instance=self.user)
        self.assertFalse(form.is_valid())

    def test_username_50_chars_valid(self):
        form = UsernameForm(data={"username": "a" * 50}, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_save_updates_username(self):
        form = UsernameForm(data={"username": "updated"}, instance=self.user)
        self.assertTrue(form.is_valid())
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "updated")


class EmailFormTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="original@example.com", username="emailuser", password="pass12345678"
        )
        self.other = User.objects.create_user(
            email="taken@example.com", username="other", password="pass12345678"
        )

    def test_valid_email(self):
        form = EmailForm(data={"email": "new@example.com"}, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_duplicate_email_invalid(self):
        form = EmailForm(data={"email": "taken@example.com"}, instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("already in use", str(form.errors["email"]))

    def test_same_email_as_own_is_valid(self):
        form = EmailForm(data={"email": "original@example.com"}, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_email_lowercased(self):
        form = EmailForm(data={"email": "NEW@EXAMPLE.COM"}, instance=self.user)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["email"], "new@example.com")


class DeleteAccountFormTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="del@example.com", username="deluser", password="correctpassword123"
        )

    def test_correct_password_valid(self):
        form = DeleteAccountForm(data={"password": "correctpassword123"}, user=self.user)
        self.assertTrue(form.is_valid())

    def test_wrong_password_invalid(self):
        form = DeleteAccountForm(data={"password": "wrongpassword"}, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("Incorrect password", str(form.errors["password"]))

    def test_empty_password_invalid(self):
        form = DeleteAccountForm(data={"password": ""}, user=self.user)
        self.assertFalse(form.is_valid())

    def test_user_stored_on_form(self):
        form = DeleteAccountForm(data={"password": "correctpassword123"}, user=self.user)
        self.assertEqual(form.user, self.user)


class AvatarFormTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="av@example.com", username="avform", password="pass12345678"
        )

    def test_valid_png_upload(self):
        f = _make_image_file("PNG", filename="avatar.png")
        form = AvatarForm(
            data={}, files={"avatar": f}, instance=self.user.profile
        )
        self.assertTrue(form.is_valid())

    def test_invalid_file_fails_validation(self):
        bad = SimpleUploadedFile("bad.png", b"not an image", content_type="image/png")
        form = AvatarForm(
            data={}, files={"avatar": bad}, instance=self.user.profile
        )
        self.assertFalse(form.is_valid())
        self.assertIn("avatar", form.errors)


class UserScoreModelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="score@example.com", username="scoreuser", password="pass12345678"
        )

    def test_str(self):
        s = UserScore(user=self.user, artist="Radiohead", difficulty="hard", score=500)
        self.assertEqual(str(s), "score@example.com | Radiohead | hard | 500")

    def test_str_no_user(self):
        s = UserScore(user=None, artist="Blur", difficulty="easy", score=100)
        self.assertIn("Blur", str(s))

    def test_accuracy_full(self):
        s = UserScore(correct_count=4, total_rounds=5)
        self.assertEqual(s.accuracy, 80.0)

    def test_accuracy_perfect(self):
        s = UserScore(correct_count=5, total_rounds=5)
        self.assertEqual(s.accuracy, 100.0)

    def test_accuracy_zero(self):
        s = UserScore(correct_count=0, total_rounds=5)
        self.assertEqual(s.accuracy, 0.0)

    def test_accuracy_zero_rounds(self):
        s = UserScore(correct_count=0, total_rounds=0)
        self.assertEqual(s.accuracy, 0.0)

    def test_accuracy_rounds_to_one_decimal(self):
        s = UserScore(correct_count=1, total_rounds=3)
        self.assertEqual(s.accuracy, 33.3)

    def test_points_property_mirrors_score(self):
        s = UserScore(score=750)
        self.assertEqual(s.points, 750)

    def test_anonymous_score_allowed(self):
        s = UserScore.objects.create(
            artist="Blur", difficulty="easy", score=100,
            correct_count=1, total_rounds=3, completed=False,
        )
        self.assertIsNone(s.user)

    def test_default_ordering_score_desc(self):
        UserScore.objects.create(user=self.user, artist="A", score=100, difficulty="easy")
        UserScore.objects.create(user=self.user, artist="B", score=500, difficulty="easy")
        scores = list(UserScore.objects.filter(user=self.user))
        self.assertEqual(scores[0].score, 500)
        self.assertEqual(scores[1].score, 100)

    def test_difficulty_choices(self):
        valid = {"easy", "medium", "hard", "insane"}
        choices = {c[0] for c in UserScore.DIFFICULTIES}
        self.assertEqual(choices, valid)

    def test_completed_defaults_false(self):
        s = UserScore.objects.create(
            user=self.user, artist="X", difficulty="easy", score=0
        )
        self.assertFalse(s.completed)

    def test_score_is_positive_integer(self):
        field = UserScore._meta.get_field("score")
        self.assertEqual(field.get_internal_type(), "PositiveIntegerField")

    def test_cascade_delete_with_user(self):
        UserScore.objects.create(user=self.user, artist="X", score=100, difficulty="easy")
        self.user.delete()
        self.assertEqual(UserScore.objects.count(), 0)


class ComputeWinStreakTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="streak@example.com", username="streakuser", password="pass12345678"
        )

    def _make_scores(self, pattern):
        import datetime
        from django.utils import timezone
        scores_qs = MagicMock()
        scores_qs.order_by.return_value.values_list.return_value = pattern
        return scores_qs

    def test_no_games(self):
        qs = self._make_scores([])
        current, best = _compute_win_streak(qs)
        self.assertEqual(current, 0)
        self.assertEqual(best, 0)

    def test_all_wins(self):
        qs = self._make_scores([True, True, True])
        current, best = _compute_win_streak(qs)
        self.assertEqual(current, 3)
        self.assertEqual(best, 3)

    def test_current_streak_broken_by_loss(self):
        qs = self._make_scores([False, True, True])
        current, best = _compute_win_streak(qs)
        self.assertEqual(current, 0)

    def test_best_streak_across_history(self):
        qs = self._make_scores([True, False, True, True, True])
        current, best = _compute_win_streak(qs)
        self.assertEqual(current, 1)
        self.assertEqual(best, 3)

    def test_current_streak_all_wins(self):
        qs = self._make_scores([True, True, False, True])
        current, best = _compute_win_streak(qs)
        self.assertEqual(current, 2)

    def test_all_losses(self):
        qs = self._make_scores([False, False, False])
        current, best = _compute_win_streak(qs)
        self.assertEqual(current, 0)
        self.assertEqual(best, 0)

    def test_single_win(self):
        qs = self._make_scores([True])
        current, best = _compute_win_streak(qs)
        self.assertEqual(current, 1)
        self.assertEqual(best, 1)

    def test_single_loss(self):
        qs = self._make_scores([False])
        current, best = _compute_win_streak(qs)
        self.assertEqual(current, 0)
        self.assertEqual(best, 0)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class ProfileViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="pv@example.com", username="pvuser", password="pass12345678"
        )
        self.url = reverse("users:profile")

    def test_redirects_anonymous(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login", response["Location"])

    def test_authenticated_200(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/profile.html")

    def test_context_keys_present(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        for key in ("scores", "total_games", "total_correct",
                    "accuracy", "best_score", "win_streak", "best_streak"):
            self.assertIn(key, response.context)

    def test_total_games_count(self):
        self.client.force_login(self.user)
        UserScore.objects.create(user=self.user, artist="A", score=100, difficulty="easy", completed=True)
        UserScore.objects.create(user=self.user, artist="B", score=200, difficulty="hard", completed=False)
        response = self.client.get(self.url)
        self.assertEqual(response.context["total_games"], 2)

    def test_best_score_value(self):
        self.client.force_login(self.user)
        UserScore.objects.create(user=self.user, artist="A", score=300, difficulty="easy")
        UserScore.objects.create(user=self.user, artist="B", score=700, difficulty="hard")
        response = self.client.get(self.url)
        self.assertEqual(response.context["best_score"], 700)

    def test_accuracy_calculation(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="A", score=100,
            difficulty="easy", correct_count=4, total_rounds=5
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["accuracy"], 80)

    def test_recent_scores_limited_to_5(self):
        self.client.force_login(self.user)
        for i in range(10):
            UserScore.objects.create(
                user=self.user, artist=f"Artist{i}", score=i*100, difficulty="easy"
            )
        response = self.client.get(self.url)
        self.assertLessEqual(len(response.context["scores"]), 5)

    def test_zero_games_defaults(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.context["total_games"],  0)
        self.assertEqual(response.context["best_score"],   0)
        self.assertEqual(response.context["accuracy"],     0)
        self.assertEqual(response.context["total_correct"], 0)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class SettingsViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="settings@example.com", username="settingsuser", password="testpassword123"
        )
        self.url = reverse("users:settings")

    def test_redirects_anonymous(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login", response["Location"])

    def test_get_renders_settings(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/settings.html")

    def test_context_has_all_forms(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        for key in ("username_form", "email_form", "avatar_form", "delete_form"):
            self.assertIn(key, response.context)

    def test_update_username(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            "action": "profile",
            "username": "newusername",
            "email": self.user.email,
        })
        self.assertRedirects(response, self.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newusername")

    def test_update_email(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            "action": "profile",
            "username": self.user.username,
            "email": "newemail@example.com",
        })
        self.assertRedirects(response, self.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "newemail@example.com")

    def test_duplicate_username_shows_error(self):
        User.objects.create_user(
            email="taken@example.com", username="takenname", password="pass12345678"
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            "action": "profile",
            "username": "takenname",
            "email": self.user.email,
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.username, "takenname")

    def test_duplicate_email_shows_error(self):
        User.objects.create_user(
            email="taken@example.com", username="other", password="pass12345678"
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            "action": "profile",
            "username": self.user.username,
            "email": "taken@example.com",
        })
        self.assertEqual(response.status_code, 200)

    def test_no_file_selected_shows_error(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"action": "avatar"})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("pick" in m.lower() or "image" in m.lower() for m in msgs))

    def test_update_preferences(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            "action": "preferences",
            "default_difficulty": "insane",
            "default_rounds": 10,
        })
        self.assertRedirects(response, self.url)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_difficulty, "insane")
        self.assertEqual(self.user.profile.default_rounds, 10)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class DeleteAccountViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="delete@example.com", username="deleteuser", password="testpassword123"
        )
        self.url = reverse("users:delete_account")

    def test_requires_login(self):
        response = self.client.post(self.url, {"password": "testpassword123"})
        self.assertEqual(response.status_code, 302)

    def test_correct_password_deletes_user(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"password": "testpassword123"})
        self.assertRedirects(response, reverse("account_login"))
        self.assertFalse(User.objects.filter(email="delete@example.com").exists())

    def test_wrong_password_keeps_user(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"password": "wrongpassword"})
        self.assertRedirects(response, reverse("users:settings"))
        self.assertTrue(User.objects.filter(email="delete@example.com").exists())

    def test_delete_logs_user_out(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": "testpassword123"})
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 302)

    def test_get_request_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_delete_cascades_scores(self):
        UserScore.objects.create(
            user=self.user, artist="Muse", score=100, difficulty="easy"
        )
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": "testpassword123"})
        self.assertEqual(UserScore.objects.count(), 0)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class DeleteAvatarViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="avdel@example.com", username="avdeluser", password="pass12345678"
        )
        self.url = reverse("users:delete_avatar")

    def test_requires_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("settings", response["Location"])

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_delete_avatar_clears_field(self):
        self.client.force_login(self.user)
        profile = self.user.profile
        with patch.object(profile.__class__, "delete_avatar") as mock_del:
            self.client.post(self.url)

    def test_redirects_to_settings(self):
        self.client.force_login(self.user)
        with patch.object(UserProfile, "delete_avatar", return_value=None):
            response = self.client.post(self.url)
        self.assertRedirects(response, reverse("users:settings"))


class AccountAdapterTests(TestCase):

    def test_signup_open_by_default(self):
        adapter = AccountAdapter()
        request = MagicMock()
        self.assertTrue(adapter.is_open_for_signup(request))

    @override_settings(ACCOUNT_ALLOW_REGISTRATION=False)
    def test_signup_closed_when_setting_false(self):
        adapter = AccountAdapter()
        request = MagicMock()
        self.assertFalse(adapter.is_open_for_signup(request))

    @override_settings(ACCOUNT_ALLOW_REGISTRATION=True)
    def test_signup_open_when_setting_true(self):
        adapter = AccountAdapter()
        request = MagicMock()
        self.assertTrue(adapter.is_open_for_signup(request))
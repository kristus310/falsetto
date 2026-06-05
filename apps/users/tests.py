import io
import uuid
import datetime
from unittest.mock import patch, MagicMock, PropertyMock, call

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError, FieldDoesNotExist
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse, resolve
from django.utils import timezone

from apps.users.context_processors import daily_challenge_status
from apps.users.forms import (
    AvatarForm,
    DeleteAccountForm,
    EmailForm,
    UserSignupForm,
    UsernameForm,
)
from apps.users.models import UserProfile, UserScore, avatar_upload_path
from apps.users.validators import validate_avatar
from apps.users.views import _compute_win_streak

User = get_user_model()

_SIMPLE_STORAGE = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
}


def _img(fmt="PNG", size=(100, 100), color=(255, 0, 0), filename="test.png"):
    from PIL import Image

    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    img.save(buf, format=fmt)
    buf.seek(0)
    ct = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
        fmt, "image/png"
    )
    return SimpleUploadedFile(filename, buf.read(), content_type=ct)


def _make_user(email="u@example.com", username="user", password="pass12345678", **kw):
    return User.objects.create_user(email=email, username=username, password=password, **kw)


class UserManagerCreateUserTests(TestCase):

    def test_requires_non_empty_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="secret")

    def test_requires_non_whitespace_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="secret", username="x")

    def test_normalises_email_domain(self):
        u = _make_user(email="Test@EXAMPLE.COM", username="norm")
        self.assertEqual(u.email, "Test@example.com")

    def test_password_is_hashed(self):
        u = _make_user(email="hash@example.com", username="hashme")
        self.assertNotEqual(u.password, "pass12345678")
        self.assertTrue(u.check_password("pass12345678"))

    def test_normal_user_not_staff(self):
        u = _make_user(email="normal@example.com", username="normal")
        self.assertFalse(u.is_staff)

    def test_normal_user_not_superuser(self):
        u = _make_user(email="normal2@example.com", username="normal2")
        self.assertFalse(u.is_superuser)

    def test_extra_fields_propagated(self):
        u = _make_user(email="extra@example.com", username="extra", is_active=False)
        self.assertFalse(u.is_active)

    def test_none_password_creates_unusable(self):
        u = User.objects.create_user(
            email="nopass@example.com", username="nopass", password=None
        )
        self.assertFalse(u.has_usable_password())


class UserManagerCreateSuperuserTests(TestCase):

    def _su(self, **kw):
        defaults = dict(email="su@example.com", username="su", password="pass12345678")
        defaults.update(kw)
        return User.objects.create_superuser(**defaults)

    def test_sets_is_staff(self):
        self.assertTrue(self._su().is_staff)

    def test_sets_is_superuser(self):
        self.assertTrue(self._su().is_superuser)

    def test_sets_is_active(self):
        self.assertTrue(self._su().is_active)

    def test_rejects_is_staff_false(self):
        with self.assertRaises(ValueError):
            self._su(email="x@e.com", username="x2", is_staff=False)

    def test_rejects_is_superuser_false(self):
        with self.assertRaises(ValueError):
            self._su(email="y@e.com", username="y2", is_superuser=False)

    def test_email_still_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email="", username="z", password="pass")


class UserModelFieldTests(TestCase):

    def setUp(self):
        self.user = _make_user()

    def test_pk_is_uuid(self):
        self.assertIsInstance(self.user.pk, uuid.UUID)

    def test_str_returns_email(self):
        self.assertEqual(str(self.user), "u@example.com")

    def test_username_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_required_fields_contains_username(self):
        self.assertIn("username", User.REQUIRED_FIELDS)

    def test_first_name_field_removed(self):
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field("first_name")

    def test_last_name_field_removed(self):
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field("last_name")

    def test_email_max_is_unique(self):
        with self.assertRaises(Exception):
            _make_user(email="u@example.com", username="dup")

    def test_username_is_unique(self):
        with self.assertRaises(Exception):
            _make_user(email="other@example.com", username="user")

    def test_username_max_length_50(self):
        self.assertEqual(User._meta.get_field("username").max_length, 50)

    def test_email_field_unique_constraint(self):
        field = User._meta.get_field("email")
        self.assertTrue(field.unique)

    def test_uuid_different_per_user(self):
        u2 = _make_user(email="u2@example.com", username="u2")
        self.assertNotEqual(self.user.pk, u2.pk)

    def test_verbose_names(self):
        self.assertEqual(User._meta.verbose_name, "user")
        self.assertEqual(User._meta.verbose_name_plural, "users")


class UserProfileAutoCreateTests(TestCase):

    def test_profile_created_on_user_save(self):
        u = _make_user(email="p1@example.com", username="p1")
        self.assertTrue(UserProfile.objects.filter(user=u).exists())

    def test_profile_created_exactly_once(self):
        u = _make_user(email="p2@example.com", username="p2")
        u.save()
        u.save()
        self.assertEqual(UserProfile.objects.filter(user=u).count(), 1)

    def test_profile_deleted_with_user(self):
        u = _make_user(email="p3@example.com", username="p3")
        uid = u.pk
        u.delete()
        self.assertFalse(UserProfile.objects.filter(user_id=uid).exists())


class UserProfileDefaultsTests(TestCase):

    def setUp(self):
        self.profile = _make_user(email="def@example.com", username="def").profile

    def test_show_on_leaderboard_default_true(self):
        self.assertTrue(self.profile.show_on_leaderboard)

    def test_default_difficulty_is_medium(self):
        self.assertEqual(self.profile.default_difficulty, "medium")

    def test_default_rounds_is_3(self):
        self.assertEqual(self.profile.default_rounds, 3)

    def test_avatar_is_blank_by_default(self):
        self.assertFalse(bool(self.profile.avatar))

    def test_str_contains_email(self):
        self.assertIn("def@example.com", str(self.profile))

    def test_str_format(self):
        self.assertEqual(str(self.profile), "def@example.com - profile")

    def test_one_to_one_reverse(self):
        self.assertEqual(self.profile.user.profile, self.profile)


class UserProfileAvatarURLTests(TestCase):

    def setUp(self):
        self.profile = _make_user(email="av@example.com", username="av").profile

    def test_avatar_url_fallback_when_no_avatar(self):
        self.assertEqual(self.profile.avatar_url, "/static/images/user.png")

    def test_avatar_url_when_avatar_set(self):
        self.profile.avatar = MagicMock()
        self.profile.avatar.__bool__ = lambda s: True
        self.profile.avatar.url = "/media/avatars/test.png"
        self.assertEqual(self.profile.avatar_url, "/media/avatars/test.png")


class UserProfileDeleteAvatarTests(TestCase):

    def setUp(self):
        self.user = _make_user(email="davt@example.com", username="davt")
        self.profile = self.user.profile

    def test_delete_avatar_removes_file_when_exists(self):
        mock_field = MagicMock()
        mock_field.__bool__ = lambda s: True
        mock_field.path = "/tmp/real.png"
        self.profile.avatar = mock_field

        with patch("os.path.isfile", return_value=True) as mock_isfile, patch(
            "os.remove"
        ) as mock_remove, patch("apps.users.models.UserProfile.save"):
            self.profile.delete_avatar()
            mock_remove.assert_called_once_with("/tmp/real.png")

    def test_delete_avatar_noop_when_no_avatar(self):
        self.profile.avatar = None
        with patch("os.remove") as mock_remove, patch(
            "apps.users.models.UserProfile.save"
        ) as mock_save:
            self.profile.delete_avatar()
            mock_remove.assert_not_called()
            mock_save.assert_not_called()


class AvatarUploadPathTests(TestCase):

    def setUp(self):
        self.profile = _make_user(email="up@example.com", username="up").profile

    def test_starts_with_avatars_prefix(self):
        self.assertTrue(avatar_upload_path(self.profile, "x.jpg").startswith("avatars/"))

    def test_extension_lowercased(self):
        self.assertTrue(avatar_upload_path(self.profile, "X.JPG").endswith(".jpg"))

    def test_webp_extension_preserved(self):
        self.assertTrue(avatar_upload_path(self.profile, "x.webp").endswith(".webp"))

    def test_stem_is_32_hex_chars(self):
        path = avatar_upload_path(self.profile, "photo.jpg")
        stem = path[len("avatars/") : -len(".jpg")]
        self.assertEqual(len(stem), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in stem))

    def test_returns_unique_paths(self):
        p1 = avatar_upload_path(self.profile, "photo.png")
        p2 = avatar_upload_path(self.profile, "photo.png")
        self.assertNotEqual(p1, p2)

    def test_no_original_filename_in_path(self):
        path = avatar_upload_path(self.profile, "my_face_photo.png")
        self.assertNotIn("my_face_photo", path)


class UserScoreModelTests(TestCase):

    def setUp(self):
        self.user = _make_user(email="score@example.com", username="scorer")

    def _score(self, **kw):
        defaults = dict(user=self.user, artist="Radiohead", difficulty="hard", score=500)
        defaults.update(kw)
        return UserScore(**defaults)

    def test_str_with_user(self):
        s = self._score()
        self.assertEqual(str(s), "score@example.com | Radiohead | hard | 500")

    def test_str_without_user(self):
        s = UserScore(user=None, artist="Blur", difficulty="easy", score=100)
        self.assertIn("Blur", str(s))

    def test_points_property_mirrors_score(self):
        self.assertEqual(self._score(score=999).points, 999)

    def test_accuracy_full(self):
        self.assertEqual(UserScore(correct_count=4, total_rounds=5).accuracy, 80.0)

    def test_accuracy_perfect(self):
        self.assertEqual(UserScore(correct_count=5, total_rounds=5).accuracy, 100.0)

    def test_accuracy_zero_correct(self):
        self.assertEqual(UserScore(correct_count=0, total_rounds=5).accuracy, 0.0)

    def test_accuracy_zero_rounds_returns_zero(self):
        self.assertEqual(UserScore(correct_count=0, total_rounds=0).accuracy, 0.0)

    def test_accuracy_rounded_to_one_decimal(self):
        self.assertEqual(UserScore(correct_count=1, total_rounds=3).accuracy, 33.3)

    def test_default_ordering_highest_score_first(self):
        UserScore.objects.create(user=self.user, artist="A", score=100, difficulty="easy")
        UserScore.objects.create(user=self.user, artist="B", score=500, difficulty="easy")
        scores = list(UserScore.objects.filter(user=self.user))
        self.assertEqual(scores[0].score, 500)

    def test_completed_defaults_false(self):
        s = UserScore.objects.create(user=self.user, artist="X", difficulty="easy", score=0)
        self.assertFalse(s.completed)

    def test_is_daily_defaults_false(self):
        s = UserScore.objects.create(user=self.user, artist="X", difficulty="easy", score=0)
        self.assertFalse(s.is_daily)

    def test_anonymous_score_allowed(self):
        s = UserScore.objects.create(
            user=None, artist="Blur", difficulty="easy", score=100
        )
        self.assertIsNone(s.user)

    def test_cascade_delete_with_user(self):
        UserScore.objects.create(user=self.user, artist="X", score=100, difficulty="easy")
        self.user.delete()
        self.assertEqual(UserScore.objects.count(), 0)

    def test_difficulty_choices_set(self):
        expected = {"easy", "medium", "hard", "insane"}
        self.assertEqual({c[0] for c in UserScore.DIFFICULTIES}, expected)

    def test_game_mode_choices_set(self):
        expected = {"complete_lyrics", "guess_song", "pick_song"}
        self.assertEqual({c[0] for c in UserScore.GAME_MODES}, expected)

    def test_score_field_is_positive_integer(self):
        self.assertEqual(
            UserScore._meta.get_field("score").get_internal_type(),
            "PositiveIntegerField",
        )

    def test_summary_data_defaults_to_list(self):
        s = UserScore.objects.create(user=self.user, artist="X", difficulty="easy")
        self.assertEqual(s.summary_data, [])

    def test_summary_data_stores_json(self):
        payload = [{"round": 1, "correct": True}]
        s = UserScore.objects.create(
            user=self.user, artist="Y", difficulty="easy", summary_data=payload
        )
        s.refresh_from_db()
        self.assertEqual(s.summary_data, payload)

    def test_meta_verbose_names(self):
        self.assertEqual(UserScore._meta.verbose_name, "user score")
        self.assertEqual(UserScore._meta.verbose_name_plural, "user scores")

    def test_indexes_defined(self):
        index_fields = [
            tuple(idx.fields) for idx in UserScore._meta.indexes
        ]
        self.assertTrue(len(index_fields) >= 4)

    def test_get_difficulty_display(self):
        s = UserScore(difficulty="insane")
        self.assertEqual(s.get_difficulty_display(), "Insane")

    def test_artist_max_length(self):
        self.assertEqual(UserScore._meta.get_field("artist").max_length, 120)


@override_settings(AVATAR_MAX_SIZE_MB=2, AVATAR_MAX_DIMENSIONS=2000)
class ValidateAvatarTests(TestCase):

    def test_valid_png(self):
        validate_avatar(_img("PNG"))

    def test_valid_jpeg(self):
        validate_avatar(_img("JPEG", filename="t.jpg"))

    def test_valid_webp(self):
        validate_avatar(_img("WEBP", filename="t.webp"))

    def test_fieldfile_instance_skipped(self):
        from django.db.models.fields.files import FieldFile

        validate_avatar(MagicMock(spec=FieldFile))

    def test_file_too_large_raises(self):
        f = _img()
        f.size = 3 * 1024 * 1024
        with self.assertRaisesRegex(ValidationError, "too large"):
            validate_avatar(f)

    def test_file_exactly_at_limit_passes(self):
        f = _img()
        f.size = 2 * 1024 * 1024
        validate_avatar(f)

    @override_settings(AVATAR_MAX_SIZE_MB=1)
    def test_custom_max_size_respected(self):
        f = _img()
        f.size = int(1.5 * 1024 * 1024)
        with self.assertRaisesRegex(ValidationError, "1 MB"):
            validate_avatar(f)

    def test_image_too_wide_raises(self):
        f = _img(size=(2001, 100))
        with self.assertRaisesRegex(ValidationError, "2000"):
            validate_avatar(f)

    def test_image_too_tall_raises(self):
        f = _img(size=(100, 2001))
        with self.assertRaisesRegex(ValidationError, "2000"):
            validate_avatar(f)

    def test_image_exactly_at_max_dimension_passes(self):
        f = _img()
        import PIL.Image as PILImage

        mock_img = MagicMock()
        mock_img.width = 2000
        mock_img.height = 2000
        mock_img.format = "PNG"
        with patch.object(PILImage, "open", return_value=mock_img):
            validate_avatar(f)

    @override_settings(AVATAR_MAX_DIMENSIONS=100)
    def test_custom_max_dimensions_respected(self):
        f = _img(size=(101, 101))
        with self.assertRaisesRegex(ValidationError, "100"):
            validate_avatar(f)

    def test_non_image_bytes_raises(self):
        f = SimpleUploadedFile("bad.png", b"not an image", content_type="image/png")
        with self.assertRaisesRegex(ValidationError, "valid image"):
            validate_avatar(f)

    def test_bmp_format_rejected(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="BMP")
        buf.seek(0)
        f = SimpleUploadedFile("t.bmp", buf.read(), content_type="image/bmp")
        with self.assertRaisesRegex(ValidationError, "Unsupported"):
            validate_avatar(f)

    def test_gif_format_rejected(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("P", (10, 10)).save(buf, format="GIF")
        buf.seek(0)
        f = SimpleUploadedFile("t.gif", buf.read(), content_type="image/gif")
        with self.assertRaisesRegex(ValidationError, "Unsupported"):
            validate_avatar(f)

    def test_decompression_bomb_raises(self):
        from PIL.Image import DecompressionBombError

        f = _img()
        with patch("PIL.Image.open", side_effect=DecompressionBombError("boom")):
            with self.assertRaisesRegex(ValidationError, "safely"):
                validate_avatar(f)

    def test_unidentified_image_raises(self):
        from PIL.Image import UnidentifiedImageError

        f = _img()
        with patch("PIL.Image.open", side_effect=UnidentifiedImageError("nope")):
            with self.assertRaisesRegex(ValidationError, "valid image"):
                validate_avatar(f)

    def test_generic_open_exception_raises(self):
        f = _img()
        with patch("PIL.Image.open", side_effect=OSError("disk error")):
            with self.assertRaisesRegex(ValidationError, "valid image"):
                validate_avatar(f)

    def test_file_pointer_reset_after_validation(self):
        f = _img()
        validate_avatar(f)
        self.assertEqual(f.file.tell(), 0)


class UsernameFormTests(TestCase):

    def setUp(self):
        self.user = _make_user()

    def test_valid_username(self):
        form = UsernameForm(data={"username": "newname"}, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_empty_username_invalid(self):
        form = UsernameForm(data={"username": ""}, instance=self.user)
        self.assertFalse(form.is_valid())

    def test_username_51_chars_invalid(self):
        form = UsernameForm(data={"username": "a" * 51}, instance=self.user)
        self.assertFalse(form.is_valid())

    def test_username_50_chars_valid(self):
        form = UsernameForm(data={"username": "a" * 50}, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_save_persists_username(self):
        form = UsernameForm(data={"username": "updated"}, instance=self.user)
        self.assertTrue(form.is_valid())
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "updated")

    def test_widget_has_placeholder(self):
        form = UsernameForm()
        self.assertEqual(
            form.fields["username"].widget.attrs.get("placeholder"), "Username"
        )

    def test_only_username_field_present(self):
        form = UsernameForm()
        self.assertEqual(list(form.fields.keys()), ["username"])


class EmailFormTests(TestCase):

    def setUp(self):
        self.user = _make_user(email="orig@example.com", username="orig")
        self.other = _make_user(email="taken@example.com", username="taken")

    def test_valid_new_email(self):
        form = EmailForm(data={"email": "new@example.com"}, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_own_current_email_valid(self):
        form = EmailForm(data={"email": "orig@example.com"}, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_duplicate_email_invalid(self):
        form = EmailForm(data={"email": "taken@example.com"}, instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("already in use", str(form.errors["email"]))

    def test_email_lowercased_on_clean(self):
        form = EmailForm(data={"email": "NEW@EXAMPLE.COM"}, instance=self.user)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["email"], "new@example.com")

    def test_case_insensitive_duplicate_check(self):
        form = EmailForm(data={"email": "TAKEN@EXAMPLE.COM"}, instance=self.user)
        self.assertFalse(form.is_valid())

    def test_widget_has_placeholder(self):
        form = EmailForm()
        self.assertEqual(
            form.fields["email"].widget.attrs.get("placeholder"), "email@example.com"
        )

    def test_only_email_field_present(self):
        form = EmailForm()
        self.assertEqual(list(form.fields.keys()), ["email"])


class DeleteAccountFormTests(TestCase):

    def setUp(self):
        self.user = _make_user(
            email="del@example.com", username="del", password="correctpassword"
        )

    def test_correct_password_valid(self):
        form = DeleteAccountForm(data={"password": "correctpassword"}, user=self.user)
        self.assertTrue(form.is_valid())

    def test_wrong_password_invalid(self):
        form = DeleteAccountForm(data={"password": "wrong"}, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("Incorrect password", str(form.errors["password"]))

    def test_empty_password_invalid(self):
        form = DeleteAccountForm(data={"password": ""}, user=self.user)
        self.assertFalse(form.is_valid())

    def test_user_stored_on_form(self):
        form = DeleteAccountForm(data={}, user=self.user)
        self.assertEqual(form.user, self.user)

    def test_password_widget_is_password_input(self):
        form = DeleteAccountForm(user=self.user)
        from django import forms as django_forms

        self.assertIsInstance(
            form.fields["password"].widget, django_forms.PasswordInput
        )

    def test_autocomplete_attribute_set(self):
        form = DeleteAccountForm(user=self.user)
        self.assertEqual(
            form.fields["password"].widget.attrs.get("autocomplete"),
            "current-password",
        )


class AvatarFormTests(TestCase):

    def setUp(self):
        self.profile = _make_user(email="avf@example.com", username="avf").profile

    def test_valid_png_accepted(self):
        form = AvatarForm(
            data={}, files={"avatar": _img("PNG")}, instance=self.profile
        )
        self.assertTrue(form.is_valid())

    def test_valid_jpeg_accepted(self):
        form = AvatarForm(
            data={}, files={"avatar": _img("JPEG", filename="t.jpg")}, instance=self.profile
        )
        self.assertTrue(form.is_valid())

    def test_valid_webp_accepted(self):
        form = AvatarForm(
            data={}, files={"avatar": _img("WEBP", filename="t.webp")}, instance=self.profile
        )
        self.assertTrue(form.is_valid())

    def test_invalid_file_rejected(self):
        bad = SimpleUploadedFile("bad.png", b"not an image", content_type="image/png")
        form = AvatarForm(data={}, files={"avatar": bad}, instance=self.profile)
        self.assertFalse(form.is_valid())
        self.assertIn("avatar", form.errors)

    def test_no_file_is_valid(self):
        form = AvatarForm(data={}, files={}, instance=self.profile)
        self.assertTrue(form.is_valid())

    def test_file_input_widget_used(self):
        from django import forms as django_forms

        form = AvatarForm()
        self.assertIsInstance(form.fields["avatar"].widget, django_forms.FileInput)

    def test_accept_attribute_restricts_types(self):
        form = AvatarForm()
        accept = form.fields["avatar"].widget.attrs.get("accept", "")
        for mime in ("image/jpeg", "image/png", "image/webp"):
            self.assertIn(mime, accept)

    def test_oversized_file_rejected(self):
        f = _img()
        f.size = 3 * 1024 * 1024
        form = AvatarForm(data={}, files={"avatar": f}, instance=self.profile)
        self.assertFalse(form.is_valid())


class ComputeWinStreakTests(TestCase):

    def _qs(self, pattern):
        qs = MagicMock()
        qs.order_by.return_value.values_list.return_value = pattern
        return qs

    def test_empty_sequence_both_zero(self):
        c, b = _compute_win_streak(self._qs([]))
        self.assertEqual((c, b), (0, 0))

    def test_single_win(self):
        c, b = _compute_win_streak(self._qs([True]))
        self.assertEqual((c, b), (1, 1))

    def test_single_loss(self):
        c, b = _compute_win_streak(self._qs([False]))
        self.assertEqual((c, b), (0, 0))

    def test_all_wins(self):
        c, b = _compute_win_streak(self._qs([True, True, True]))
        self.assertEqual((c, b), (3, 3))

    def test_all_losses(self):
        c, b = _compute_win_streak(self._qs([False, False, False]))
        self.assertEqual((c, b), (0, 0))

    def test_current_broken_by_first_loss(self):
        c, _ = _compute_win_streak(self._qs([False, True, True]))
        self.assertEqual(c, 0)

    def test_current_streak_two_wins_then_loss(self):
        c, _ = _compute_win_streak(self._qs([True, True, False, True]))
        self.assertEqual(c, 2)

    def test_best_across_history(self):
        _, b = _compute_win_streak(self._qs([True, False, True, True, True]))
        self.assertEqual(b, 3)

    def test_best_and_current_independent(self):
        c, b = _compute_win_streak(self._qs([True, False, True, True, True]))
        self.assertEqual(c, 1)
        self.assertEqual(b, 3)

    def test_best_resets_on_loss(self):
        _, b = _compute_win_streak(
            self._qs([False, True, True, False, True, True, True])
        )
        self.assertEqual(b, 3)

    def test_alternating_wl(self):
        c, b = _compute_win_streak(self._qs([True, False, True, False, True]))
        self.assertEqual(c, 1)
        self.assertEqual(b, 1)

    def test_single_win_at_end(self):
        c, b = _compute_win_streak(self._qs([False, False, True]))
        self.assertEqual(c, 0)
        self.assertEqual(b, 1)

    def test_large_streak(self):
        pattern = [True] * 100
        c, b = _compute_win_streak(self._qs(pattern))
        self.assertEqual(c, 100)
        self.assertEqual(b, 100)


class SignalDeleteFileTests(TestCase):

    def test_deletes_existing_file(self):
        field = MagicMock()
        field.__bool__ = lambda s: True
        field.path = "/fake/avatar.png"
        with patch("os.remove") as mock_rm:
            from apps.users.signals import _delete_file
            _delete_file(field)
            mock_rm.assert_called_once_with("/fake/avatar.png")

    def test_ignores_file_not_found(self):
        field = MagicMock()
        field.__bool__ = lambda s: True
        field.path = "/nonexistent/path.png"
        from apps.users.signals import _delete_file
        _delete_file(field)

    def test_noop_on_falsy_field(self):
        from apps.users.signals import _delete_file
        _delete_file(None)
        _delete_file("")

    def test_noop_when_no_path_attr(self):
        from apps.users.signals import _delete_file
        _delete_file(object())


class SignalDeleteOldAvatarOnUpdateTests(TestCase):

    def setUp(self):
        self.profile = _make_user(email="sig@example.com", username="sig").profile

    def test_skipped_for_new_profile_no_pk(self):
        new_profile = UserProfile.__new__(UserProfile)
        new_profile.pk = None
        with patch("apps.users.signals._delete_file") as mock_del:
            from apps.users.signals import delete_old_avatar_on_update
            delete_old_avatar_on_update(sender=UserProfile, instance=new_profile)
            mock_del.assert_not_called()

    def test_old_avatar_deleted_when_changed(self):
        old_avatar = MagicMock()
        old_avatar.__bool__ = lambda s: True
        old_avatar.__ne__ = lambda s, o: True

        old_profile = MagicMock()
        old_profile.avatar = old_avatar

        with patch(
            "apps.users.signals.UserProfile.objects.get", return_value=old_profile
        ), patch("apps.users.signals._delete_file") as mock_del:
            from apps.users.signals import delete_old_avatar_on_update
            delete_old_avatar_on_update(sender=UserProfile, instance=self.profile)
            mock_del.assert_called_once_with(old_avatar)

    def test_old_avatar_not_deleted_when_unchanged(self):
        same_avatar = MagicMock()
        same_avatar.__bool__ = lambda s: True
        same_avatar.__ne__ = lambda s, o: False

        old_profile = MagicMock()
        old_profile.avatar = same_avatar

        self.profile.avatar = same_avatar

        with patch(
            "apps.users.signals.UserProfile.objects.get", return_value=old_profile
        ), patch("apps.users.signals._delete_file") as mock_del:
            from apps.users.signals import delete_old_avatar_on_update
            delete_old_avatar_on_update(sender=UserProfile, instance=self.profile)
            mock_del.assert_not_called()

    def test_handles_profile_does_not_exist(self):
        with patch(
            "apps.users.signals.UserProfile.objects.get",
            side_effect=UserProfile.DoesNotExist,
        ), patch("apps.users.signals._delete_file") as mock_del:
            from apps.users.signals import delete_old_avatar_on_update
            delete_old_avatar_on_update(sender=UserProfile, instance=self.profile)
            mock_del.assert_not_called()


class SignalDeleteAvatarOnProfileDeleteTests(TestCase):

    def setUp(self):
        self.profile = _make_user(email="pdel@example.com", username="pdel").profile

    def test_avatar_deleted_on_profile_delete(self):
        fake = MagicMock()
        fake.__bool__ = lambda s: True
        self.profile.avatar = fake
        with patch("apps.users.signals._delete_file") as mock_del:
            from apps.users.signals import delete_avatar_on_profile_delete
            delete_avatar_on_profile_delete(sender=UserProfile, instance=self.profile)
            mock_del.assert_called_once_with(fake)


class SignalSyncEmailToAllauthTests(TestCase):

    def setUp(self):
        self.user = _make_user(email="sync@example.com", username="sync")

    def test_no_op_on_created(self):
        from allauth.account.models import EmailAddress
        from apps.users.signals import sync_user_email_to_allauth

        initial_count = EmailAddress.objects.count()
        sync_user_email_to_allauth(
            sender=User, instance=self.user, created=True
        )
        self.assertEqual(EmailAddress.objects.count(), initial_count)

    def test_sets_primary_on_update(self):
        from allauth.account.models import EmailAddress
        from apps.users.signals import sync_user_email_to_allauth

        sync_user_email_to_allauth(
            sender=User, instance=self.user, created=False
        )
        ea = EmailAddress.objects.get(user=self.user, email__iexact="sync@example.com")
        self.assertTrue(ea.primary)


class DailyChallengeStatusTests(TestCase):

    def setUp(self):
        self.user = _make_user(email="ctx@example.com", username="ctx")
        self.factory = RequestFactory()

    def _req(self, user=None):
        r = self.factory.get("/")
        r.user = user or MagicMock(is_authenticated=False)
        return r

    def test_anonymous_user_returns_false(self):
        ctx = daily_challenge_status(self._req())
        self.assertFalse(ctx["has_played_daily"])

    def test_authenticated_not_played_returns_false(self):
        ctx = daily_challenge_status(self._req(user=self.user))
        self.assertFalse(ctx["has_played_daily"])

    def test_authenticated_played_today_returns_true(self):
        UserScore.objects.create(
            user=self.user,
            artist="X",
            difficulty="easy",
            score=0,
            is_daily=True,
        )
        ctx = daily_challenge_status(self._req(user=self.user))
        self.assertTrue(ctx["has_played_daily"])

    def test_old_daily_score_does_not_count(self):
        score = UserScore.objects.create(
            user=self.user, artist="X", difficulty="easy", score=0, is_daily=True
        )
        yesterday = timezone.now() - datetime.timedelta(days=1)
        UserScore.objects.filter(pk=score.pk).update(created_at=yesterday)

        ctx = daily_challenge_status(self._req(user=self.user))
        self.assertFalse(ctx["has_played_daily"])

    def test_non_daily_score_does_not_count(self):
        UserScore.objects.create(
            user=self.user, artist="X", difficulty="easy", score=0, is_daily=False
        )
        ctx = daily_challenge_status(self._req(user=self.user))
        self.assertFalse(ctx["has_played_daily"])

    def test_context_key_always_present(self):
        ctx = daily_challenge_status(self._req())
        self.assertIn("has_played_daily", ctx)


class URLResolutionTests(TestCase):

    def test_profile_url_resolves(self):
        self.assertEqual(reverse("users:profile"), "/users/profile/")

    def test_settings_url_resolves(self):
        self.assertEqual(reverse("users:settings"), "/users/settings/")

    def test_delete_account_url_resolves(self):
        self.assertEqual(reverse("users:delete_account"), "/users/delete/")

    def test_delete_avatar_url_resolves(self):
        self.assertEqual(reverse("users:delete_avatar"), "/users/avatar/delete/")

    def test_profile_resolves_to_correct_view(self):
        match = resolve("/users/profile/")
        self.assertEqual(match.url_name, "profile")

    def test_settings_resolves_to_correct_view(self):
        match = resolve("/users/settings/")
        self.assertEqual(match.url_name, "settings")

    def test_delete_account_resolves_to_correct_view(self):
        match = resolve("/users/delete/")
        self.assertEqual(match.url_name, "delete_account")

    def test_delete_avatar_resolves_to_correct_view(self):
        match = resolve("/users/avatar/delete/")
        self.assertEqual(match.url_name, "delete_avatar")


@override_settings(STORAGES=_SIMPLE_STORAGE)
class ProfileViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(email="pv@example.com", username="pv")
        self.url = reverse("users:profile")

    def test_anonymous_redirected(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_redirect_contains_login(self):
        r = self.client.get(self.url)
        self.assertIn("login", r["Location"])

    def test_authenticated_gets_200(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_correct_template(self):
        self.client.force_login(self.user)
        self.assertTemplateUsed(self.client.get(self.url), "users/profile.html")

    def test_all_expected_context_keys(self):
        self.client.force_login(self.user)
        ctx = self.client.get(self.url).context
        for key in (
            "scores", "total_games", "total_correct",
            "accuracy", "best_score", "win_streak", "best_streak",
        ):
            self.assertIn(key, ctx)

    def test_zero_games_defaults(self):
        self.client.force_login(self.user)
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["total_games"], 0)
        self.assertEqual(ctx["best_score"], 0)
        self.assertEqual(ctx["accuracy"], 0)
        self.assertEqual(ctx["total_correct"], 0)
        self.assertEqual(ctx["win_streak"], 0)
        self.assertEqual(ctx["best_streak"], 0)

    def test_total_games_count(self):
        self.client.force_login(self.user)
        UserScore.objects.create(user=self.user, artist="A", score=100, difficulty="easy")
        UserScore.objects.create(user=self.user, artist="B", score=200, difficulty="hard")
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["total_games"], 2)

    def test_best_score(self):
        self.client.force_login(self.user)
        UserScore.objects.create(user=self.user, artist="A", score=300, difficulty="easy")
        UserScore.objects.create(user=self.user, artist="B", score=700, difficulty="hard")
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["best_score"], 700)

    def test_accuracy_calculation(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="A", score=100, difficulty="easy",
            correct_count=4, total_rounds=5,
        )
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["accuracy"], 80)

    def test_recent_scores_capped_at_5(self):
        self.client.force_login(self.user)
        for i in range(10):
            UserScore.objects.create(
                user=self.user, artist=f"Artist{i}", score=i * 100, difficulty="easy"
            )
        ctx = self.client.get(self.url).context
        self.assertLessEqual(len(ctx["scores"]), 5)

    def test_best_score_difficulty_string(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="A", score=500, difficulty="insane"
        )
        ctx = self.client.get(self.url).context
        self.assertIn("Insane", ctx["best_score_difficulty"])

    def test_best_score_difficulty_none_with_no_scores(self):
        self.client.force_login(self.user)
        ctx = self.client.get(self.url).context
        self.assertIsNone(ctx["best_score_difficulty"])

    def test_does_not_leak_other_user_scores(self):
        other = _make_user(email="other@example.com", username="other")
        UserScore.objects.create(user=other, artist="X", score=9999, difficulty="hard")
        self.client.force_login(self.user)
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["total_games"], 0)
        self.assertEqual(ctx["best_score"], 0)

    def test_total_correct_summed(self):
        self.client.force_login(self.user)
        UserScore.objects.create(
            user=self.user, artist="A", score=100, difficulty="easy",
            correct_count=3, total_rounds=5,
        )
        UserScore.objects.create(
            user=self.user, artist="B", score=200, difficulty="hard",
            correct_count=4, total_rounds=5,
        )
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["total_correct"], 7)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class SettingsViewGetTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(email="sv@example.com", username="sv")
        self.url = reverse("users:settings")

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_get_renders_200(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_correct_template(self):
        self.client.force_login(self.user)
        self.assertTemplateUsed(self.client.get(self.url), "users/settings.html")

    def test_all_forms_in_context(self):
        self.client.force_login(self.user)
        ctx = self.client.get(self.url).context
        for key in ("username_form", "email_form", "avatar_form", "delete_form"):
            self.assertIn(key, ctx)

    def test_delete_method_not_allowed(self):
        self.client.force_login(self.user)
        r = self.client.delete(self.url)
        self.assertEqual(r.status_code, 405)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class SettingsViewProfileActionTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            email="profile_action@example.com", username="profile_action"
        )
        self.url = reverse("users:settings")

    def _post(self, **kw):
        data = {"action": "profile", "username": self.user.username, "email": self.user.email}
        data.update(kw)
        return self.client.post(self.url, data)

    def test_update_username_redirects(self):
        self.client.force_login(self.user)
        r = self._post(username="newusername")
        self.assertRedirects(r, self.url)

    def test_update_username_persisted(self):
        self.client.force_login(self.user)
        self._post(username="newusername")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newusername")

    def test_update_email_persisted(self):
        self.client.force_login(self.user)
        self._post(email="updated@example.com")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "updated@example.com")

    def test_success_message_shown(self):
        self.client.force_login(self.user)
        r = self._post(follow=True)
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any("updated" in m.lower() for m in msgs))

    def test_duplicate_username_returns_200(self):
        _make_user(email="taken@example.com", username="takenname")
        self.client.force_login(self.user)
        r = self._post(username="takenname")
        self.assertEqual(r.status_code, 200)

    def test_duplicate_username_not_saved(self):
        _make_user(email="taken2@example.com", username="takenname2")
        self.client.force_login(self.user)
        self._post(username="takenname2")
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.username, "takenname2")

    def test_duplicate_email_returns_200(self):
        _make_user(email="taken3@example.com", username="other3")
        self.client.force_login(self.user)
        r = self._post(email="taken3@example.com")
        self.assertEqual(r.status_code, 200)

    def test_error_message_on_invalid_form(self):
        _make_user(email="clash@example.com", username="clash")
        self.client.force_login(self.user)
        r = self._post(username="clash", follow=True)
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any("fix" in m.lower() or "error" in m.lower() for m in msgs))

    def test_empty_username_returns_200(self):
        self.client.force_login(self.user)
        r = self._post(username="")
        self.assertEqual(r.status_code, 200)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class SettingsViewPreferencesActionTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(email="pref@example.com", username="pref")
        self.url = reverse("users:settings")

    def _post(self, **kw):
        data = {"action": "preferences", "default_difficulty": "medium", "default_rounds": 3}
        data.update(kw)
        return self.client.post(self.url, data)

    def test_valid_preferences_redirect(self):
        self.client.force_login(self.user)
        self.assertRedirects(self._post(), self.url)

    def test_difficulty_saved(self):
        self.client.force_login(self.user)
        self._post(default_difficulty="insane")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_difficulty, "insane")

    def test_rounds_saved(self):
        self.client.force_login(self.user)
        self._post(default_rounds=10)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 10)

    def test_invalid_difficulty_coerced_to_medium(self):
        self.client.force_login(self.user)
        self._post(default_difficulty="extreme")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_difficulty, "medium")

    def test_rounds_clamped_to_minimum_1(self):
        self.client.force_login(self.user)
        self._post(default_rounds=0)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 1)

    def test_rounds_clamped_to_maximum_20(self):
        self.client.force_login(self.user)
        self._post(default_rounds=99)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 20)

    def test_non_integer_rounds_defaults_to_3(self):
        self.client.force_login(self.user)
        self._post(default_rounds="banana")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 3)

    def test_success_message_shown(self):
        self.client.force_login(self.user)
        r = self._post(follow=True)
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any("preferences" in m.lower() for m in msgs))

    def test_all_valid_difficulties_accepted(self):
        self.client.force_login(self.user)
        for diff in ("easy", "medium", "hard", "insane"):
            self._post(default_difficulty=diff)
            self.user.profile.refresh_from_db()
            self.assertEqual(self.user.profile.default_difficulty, diff)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class SettingsViewAvatarActionTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(email="ava@example.com", username="ava")
        self.url = reverse("users:settings")

    def test_no_file_selected_error_message(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url, {"action": "avatar"}, follow=True)
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(
            any("pick" in m.lower() or "image" in m.lower() for m in msgs)
        )

    def test_no_file_returns_200(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url, {"action": "avatar"})
        self.assertEqual(r.status_code, 200)

    def test_invalid_file_shows_error(self):
        self.client.force_login(self.user)
        bad = SimpleUploadedFile("bad.png", b"notanimage", content_type="image/png")
        r = self.client.post(
            self.url, {"action": "avatar", "avatar": bad}, follow=True
        )
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(len(msgs) > 0)

    def test_unknown_action_renders_page(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url, {"action": "nonexistent"})
        self.assertEqual(r.status_code, 200)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class DeleteAccountViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            email="delete@example.com", username="deleteuser", password="testpassword123"
        )
        self.url = reverse("users:delete_account")

    def test_requires_authentication(self):
        r = self.client.post(self.url, {"password": "testpassword123"})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("account_login", r["Location"])

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_correct_password_deletes_user(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": "testpassword123"})
        self.assertFalse(User.objects.filter(email="delete@example.com").exists())

    def test_correct_password_redirects_to_login(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url, {"password": "testpassword123"})
        self.assertRedirects(r, reverse("account_login"))

    def test_correct_password_logs_user_out(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": "testpassword123"})
        r = self.client.get(reverse("users:profile"))
        self.assertEqual(r.status_code, 302)

    def test_wrong_password_keeps_user(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": "wrongpassword"})
        self.assertTrue(User.objects.filter(email="delete@example.com").exists())

    def test_wrong_password_redirects_to_settings(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url, {"password": "wrongpassword"})
        self.assertRedirects(r, reverse("users:settings"))

    def test_wrong_password_error_message(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url, {"password": "wrongpassword"}, follow=True)
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any("incorrect" in m.lower() for m in msgs))

    def test_delete_cascades_scores(self):
        UserScore.objects.create(
            user=self.user, artist="Muse", score=100, difficulty="easy"
        )
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": "testpassword123"})
        self.assertEqual(UserScore.objects.count(), 0)

    def test_delete_cascades_profile(self):
        uid = self.user.pk
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": "testpassword123"})
        self.assertFalse(UserProfile.objects.filter(user_id=uid).exists())

    def test_success_message_present(self):
        self.client.force_login(self.user)
        r = self.client.post(
            self.url, {"password": "testpassword123"}, follow=True
        )
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any("deleted" in m.lower() for m in msgs))

    def test_empty_password_keeps_user(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"password": ""})
        self.assertTrue(User.objects.filter(email="delete@example.com").exists())



@override_settings(STORAGES=_SIMPLE_STORAGE)
class DeleteAvatarViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(email="avdel@example.com", username="avdel")
        self.url = reverse("users:delete_avatar")

    def test_requires_authentication(self):
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("settings", r["Location"])

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_redirects_to_settings(self):
        self.client.force_login(self.user)
        with patch.object(UserProfile, "delete_avatar", return_value=None):
            r = self.client.post(self.url)
        self.assertRedirects(r, reverse("users:settings"))

    def test_calls_delete_avatar(self):
        self.client.force_login(self.user)
        with patch.object(UserProfile, "delete_avatar") as mock_del:
            self.client.post(self.url)
            mock_del.assert_called_once()

    def test_success_message_shown(self):
        self.client.force_login(self.user)
        with patch.object(UserProfile, "delete_avatar", return_value=None):
            r = self.client.post(self.url, follow=True)
        msgs = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any("removed" in m.lower() or "avatar" in m.lower() for m in msgs))


class AdminRegistrationTests(TestCase):

    def test_user_registered_with_admin(self):
        from django.contrib import admin
        from apps.users.models import User

        self.assertIn(User, admin.site._registry)

    def test_userprofile_registered_with_admin(self):
        from django.contrib import admin

        self.assertIn(UserProfile, admin.site._registry)

    def test_userscore_registered_with_admin(self):
        from django.contrib import admin

        self.assertIn(UserScore, admin.site._registry)

    def test_user_admin_list_display(self):
        from django.contrib import admin
        from apps.users.admin import CustomUserAdmin

        ua = admin.site._registry[User]
        self.assertIn("email", ua.list_display)
        self.assertIn("username", ua.list_display)
        self.assertIn("is_staff", ua.list_display)

    def test_user_admin_search_fields(self):
        from apps.users.admin import CustomUserAdmin
        from django.contrib import admin

        ua = admin.site._registry[User]
        self.assertIn("email", ua.search_fields)
        self.assertIn("username", ua.search_fields)

    def test_user_admin_ordering(self):
        from apps.users.admin import CustomUserAdmin
        from django.contrib import admin

        ua = admin.site._registry[User]
        self.assertEqual(ua.ordering, ["-date_joined"])

    def test_userscore_admin_list_filter_includes_difficulty(self):
        from django.contrib import admin

        ua = admin.site._registry[UserScore]
        self.assertIn("difficulty", ua.list_filter)

    def test_userscore_admin_ordering(self):
        from django.contrib import admin

        ua = admin.site._registry[UserScore]
        self.assertEqual(ua.ordering, ["-score"])

    def test_user_admin_add_fieldsets_contains_email(self):
        from django.contrib import admin

        ua = admin.site._registry[User]
        all_fields = []
        for _, opts in ua.add_fieldsets:
            all_fields.extend(opts.get("fields", []))
        self.assertIn("email", all_fields)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class HTTPMethodEnforcementTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(email="meth@example.com", username="meth", password="pass123456")
        self.client.force_login(self.user)

    def test_settings_put_not_allowed(self):
        r = self.client.put(reverse("users:settings"))
        self.assertEqual(r.status_code, 405)

    def test_delete_account_get_not_allowed(self):
        r = self.client.get(reverse("users:delete_account"))
        self.assertEqual(r.status_code, 405)

    def test_delete_avatar_get_not_allowed(self):
        r = self.client.get(reverse("users:delete_avatar"))
        self.assertEqual(r.status_code, 405)


@override_settings(STORAGES=_SIMPLE_STORAGE)
class CrossUserIsolationTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user_a = _make_user(email="a@example.com", username="a")
        self.user_b = _make_user(email="b@example.com", username="b")

    def test_profile_stats_isolated_per_user(self):
        UserScore.objects.create(
            user=self.user_b, artist="B-Artist", score=9999, difficulty="insane"
        )
        self.client.force_login(self.user_a)
        ctx = self.client.get(reverse("users:profile")).context
        self.assertEqual(ctx["total_games"], 0)
        self.assertEqual(ctx["best_score"], 0)

    def test_cannot_delete_other_user_via_form(self):
        self.client.force_login(self.user_a)
        self.client.post(
            reverse("users:delete_account"), {"password": "pass12345678"}
        )
        self.assertTrue(User.objects.filter(email="b@example.com").exists())

    def test_settings_update_only_affects_logged_in_user(self):
        self.client.force_login(self.user_a)
        self.client.post(
            reverse("users:settings"),
            {
                "action": "profile",
                "username": "changedname",
                "email": "a@example.com",
            },
        )
        self.user_b.refresh_from_db()
        self.assertEqual(self.user_b.username, "b")


@override_settings(STORAGES=_SIMPLE_STORAGE)
class PreferenceBoundaryTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = _make_user(email="bound@example.com", username="bound")
        self.client.force_login(self.user)
        self.url = reverse("users:settings")

    def _prefs(self, **kw):
        data = {"action": "preferences", "default_difficulty": "medium", "default_rounds": 5}
        data.update(kw)
        return self.client.post(self.url, data)

    def test_rounds_1_accepted(self):
        self._prefs(default_rounds=1)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 1)

    def test_rounds_20_accepted(self):
        self._prefs(default_rounds=20)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 20)

    def test_rounds_minus_1_clamped_to_1(self):
        self._prefs(default_rounds=-1)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 1)

    def test_rounds_21_clamped_to_20(self):
        self._prefs(default_rounds=21)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 20)

    def test_float_rounds_defaults_to_3(self):
        self._prefs(default_rounds="3.7")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 3)

    def test_empty_rounds_defaults_to_3(self):
        self._prefs(default_rounds="")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.default_rounds, 3)
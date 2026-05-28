import os
import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from .managers import UserManager
from .validators import validate_avatar

def avatar_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"avatars/{uuid.uuid4().hex}{ext}"

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=50, unique=True)

    first_name = None
    last_name = None
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.ImageField(
        upload_to=avatar_upload_path,
        null=True,
        blank=True,
        validators=[validate_avatar],
    )
    show_on_leaderboard = models.BooleanField(default=True)
    email_notifications = models.BooleanField(default=True)

    @property
    def avatar_url(self):
        if self.avatar:
            return self.avatar.url
        return "/static/images/user.png"

    def __str__(self):
        return f"{self.user.email} - profile"

    def delete_avatar(self):
        if self.avatar:
            if os.path.isfile(self.avatar.path):
                os.remove(self.avatar.path)
            self.avatar = None
            self.save(update_fields=["avatar"])

@receiver(post_save, sender=User)
def create_or_save_user_profile(sender, instance, created, **kwargs):
    UserProfile.objects.get_or_create(user=instance)

class UserScore(models.Model):
    class Difficulties(models.TextChoices):
        EASY = "easy", "Easy"
        MEDIUM = "medium", "Medium"
        HARD = "hard", "Hard"
        INSANE = "insane", "Insane"

    class GameModes(models.TextChoices):
        COMPLETE_LYRICS = "complete_lyrics", "Complete Lyrics"
        GUESS_SONG = "guess_song", "Guess Song"
        PICK_SONG = "pick_song", "Pick Song"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="scores", null=True, blank=True
    )
    artist = models.CharField(max_length=120)
    difficulty = models.CharField(
        max_length=12,
        choices=Difficulties.choices,
        default=Difficulties.MEDIUM
    )
    game_mode = models.CharField(
        max_length=20,
        choices=GameModes.choices,
        default=GameModes.COMPLETE_LYRICS,
        db_index=True
    )
    score = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveSmallIntegerField(default=0)
    total_rounds = models.PositiveSmallIntegerField(default=0)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "user score"
        verbose_name_plural = "user scores"
        ordering = ["-score", "-created_at"]
        indexes = [
            models.Index(fields=["completed", "game_mode", "-score", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user} | {self.artist} | {self.game_mode} | {self.difficulty} | {self.score}"

    @property
    def points(self) -> int:
        return self.score

    @property
    def accuracy(self) -> float:
        if not self.total_rounds:
            return 0.0
        return round(self.correct_count / self.total_rounds * 100, 1)
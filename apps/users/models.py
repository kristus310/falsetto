import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from .managers import UserManager

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

class UserScore(models.Model):
    DIFFICULTIES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
        ("insane", "Insane"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scores", null=True, blank=True)
    artist = models.CharField(max_length=120)
    difficulty = models.CharField(max_length=12, choices=DIFFICULTIES, default="medium")
    score = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveSmallIntegerField(default=0)
    total_rounds = models.PositiveSmallIntegerField(default=0)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "user score"
        verbose_name_plural = "user scores"
        ordering = ["-score", "-created_at"]

    def __str__(self):
        return f"{self.user} | {self.artist} | {self.difficulty} | {self.score}"

    @property
    def accuracy(self) -> float:
        if self.total_rounds == 0:
            return 0.0
        return round(self.correct_count / self.total_rounds * 100, 1)

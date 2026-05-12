from django.urls import path
from . import views

app_name = "game"
urlpatterns = [
    path("", views.index, name="index"),
    path("lobby/", views.lobby, name="lobby"),
    path("game/", views.game, name="game"),
    path("game-over/", views.game_over, name="game_over")
]
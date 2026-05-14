from django.urls import path
from django.urls.resolvers import URLPattern
from . import views

app_name = "game"
urlpatterns: list[URLPattern] = [
    path("", views.index, name="index"),
    path("lobby/", views.lobby, name="lobby"),
    path("game/", views.game, name="game"),
    path("game-over/", views.game_over, name="game_over")
]
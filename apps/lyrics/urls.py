from django.urls import path
from django.urls.resolvers import URLPattern
from . import views

app_name = "lyrics"
urlpatterns: list[URLPattern] = [
    path("fetch/<str:artist_slug>/<str:difficulty_slug>", views.fetch, name="fetch")
]

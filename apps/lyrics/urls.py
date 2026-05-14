from django.urls import path
from . import views

app_name = "lyrics"
urlpatterns = [
    path("fetch/<slug:artist_slug>/<slug:difficulty_slug>", views.fetch, name="fetch")
]

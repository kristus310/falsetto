from django.urls import path
from django.urls.resolvers import URLPattern
from . import views

app_name = "users"
urlpatterns: list[URLPattern] = [
    path("profile/", views.profile, name="profile"),
    path("settings/", views.settings, name="settings"),
]
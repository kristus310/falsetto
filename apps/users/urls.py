from django.urls import path
from django.urls.resolvers import URLPattern
from . import views

app_name = "users"
urlpatterns: list[URLPattern] = [
    path("profile/", views.profile, name="profile"),
    path("settings/", views.settings, name="settings"),
    path("delete/", views.delete_account, name="delete_account"),
    path("avatar/delete/", views.delete_avatar, name="delete_avatar"),
]
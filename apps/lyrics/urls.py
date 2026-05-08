from django.urls import path
from . import views

app_name = "lyrics"
urlpatterns = [
    path("fetch/", views.fetch, name="fetch")
]

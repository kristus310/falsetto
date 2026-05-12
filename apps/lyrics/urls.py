from django.urls import path
from . import views

app_name = "lyrics"
urlpatterns = [
    path("fetch/<slug:slug>", views.fetch, name="fetch")
]

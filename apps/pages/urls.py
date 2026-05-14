from django.urls import path
from django.urls.resolvers import URLPattern
from . import views

app_name = "pages"
urlpatterns: list[URLPattern] = [
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("legal/", views.legal, name="legal"),
]

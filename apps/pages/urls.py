from django.urls import path
from django.urls.resolvers import URLPattern
from . import views

app_name = "pages"
urlpatterns: list[URLPattern] = [
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("faq/", views.faq, name="faq"),
    path("legal/", views.legal, name="legal"),
    path("set-theme/", views.set_theme, name="set_theme"),
]

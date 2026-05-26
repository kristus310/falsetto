from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.urls.resolvers import URLPattern, URLResolver
from apps.pages.seo import robots_txt, sitemap_xml

urlpatterns: list[URLPattern | URLResolver] = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path("users/", include("apps.users.urls", namespace="users")),
    path("lyrics/", include("apps.lyrics.urls", namespace="lyrics")),
    path("robots.txt", robots_txt),
    path("sitemap.xml", sitemap_xml),
    path("", include("apps.pages.urls", namespace="pages")),
    path("", include("apps.game.urls", namespace="game")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
from django.contrib import admin
from .models import Artist, Track, LyricCache

@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ("name", "is_fully_cached", "updated_at")
    search_fields = ("name",)
    list_filter = ("is_fully_cached",)

@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ("name", "artist", "playcount", "mbid")
    search_fields = ("name", "artist__name", "mbid")
    list_filter = ("artist",)

@admin.register(LyricCache)
class LyricCacheAdmin(admin.ModelAdmin):
    list_display = ("track", "album_name", "duration", "instrumental", "has_no_lyrics")
    list_filter = ("instrumental", "has_no_lyrics")
    search_fields = ("track__name", "track__artist__name", "album_name")
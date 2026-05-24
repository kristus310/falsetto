from django.db import models

class Artist(models.Model):
    name = models.CharField(max_length=255, unique=True, db_index=True)
    is_fully_cached = models.BooleanField(default=False, help_text="True if top tracks are locally stored.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

class Track(models.Model):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="tracks")
    name = models.CharField(max_length=255, db_index=True)
    playcount = models.IntegerField(default=0)
    mbid = models.CharField(max_length=36, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("artist", "name")
        ordering = ["-playcount"]

    def __str__(self):
        return f"{self.artist.name} - {self.name}"

class LyricCache(models.Model):
    track = models.OneToOneField(Track, on_delete=models.CASCADE, related_name="lyric_cache")
    album_name = models.CharField(max_length=255, blank=True, default="")
    duration = models.IntegerField(default=0)
    plain_lyrics = models.TextField(null=True, blank=True)
    synced_lyrics = models.TextField(null=True, blank=True)
    instrumental = models.BooleanField(default=False)
    has_no_lyrics = models.BooleanField(default=False, help_text="Flag true if API explicitly yields 404.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lyrics for {self.track.name}"
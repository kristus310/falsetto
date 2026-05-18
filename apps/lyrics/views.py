from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from django.http import JsonResponse
from .services import LastFMAPI, LRCLIBAPI

def fetch(request: HttpRequest, artist_slug: str, difficulty_slug: str) -> HttpResponse:
    artist = artist_slug
    difficulty = difficulty_slug
    lastFM = LastFMAPI()
    lrclib = LRCLIBAPI()

    list = []

    try:
        track = lastFM.get_track(artist, difficulty)
        if not track:
            return JsonResponse({"error": f"No tracks found for {artist}"}, status=404)

        lyrics = lrclib.get_lyrics_for_track(track, artist)
        if not lyrics or not lyrics.has_lyrics():
            return JsonResponse({"error": f"No lyrics found for {track['name']} by {artist}"}, status=404)

        excerpt = lyrics.random_excerpt()
        if not excerpt:
            return JsonResponse({"error": f"Could not extract a usable excerpt for {track['name']}"}, status=404)

    except Exception as e:
        return JsonResponse({"error": "An internal error occurred", "details": str(e)}, status=500)

    return JsonResponse({"track": track, "difficulty": difficulty, "excerpt": excerpt})
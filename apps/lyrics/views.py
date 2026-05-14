from django.shortcuts import render
from django.http import JsonResponse
from .services import LastFMAPI

def fetch(request, artist_slug, difficulty_slug):
    artist = artist_slug
    difficulty = difficulty_slug
    api = LastFMAPI()

    piss = []

    for i in range(5):
        try:
            track = api.get_track(artist, difficulty)

            if not track:
                return JsonResponse({"error": f"No tracks found for {artist}"}, status=404)

            piss.append(track)

        except Exception as e:
            return JsonResponse({"error": "An internal error occurred", "details": str(e)}, status=500)

    return JsonResponse({"track": piss, "diff": difficulty})

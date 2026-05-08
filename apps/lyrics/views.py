from django.shortcuts import render
from django.http import JsonResponse
from .services import get_top_tracks


def fetch(request):
    artist_name = "Muse"
    difficulty = "medium"
    track_data = get_top_tracks(artist_name, difficulty)

    if not track_data:
        return JsonResponse({"error": "Could not fetch tracks"}, status=500)

    return JsonResponse({"artist": artist_name, "tracks": track_data}, safe=False)
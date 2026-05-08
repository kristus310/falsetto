import requests
from django.conf import settings

BASE_LASTFM_URL = "http://ws.audioscrobbler.com/2.0/"

def get_top_tracks(artist_name: str, difficulty: str):
    params = {
        "method": "artist.gettoptracks",
        "artist": artist_name,
        "limit": "50",
        "autocorrect": "1",
        "format": "json",
        "api_key": settings.LASTFM_API_KEY,
    }

    try:
        response = requests.get(BASE_LASTFM_URL, params=params)
        response.raise_for_status()
        data = response.json()

        tracks = data.get('toptracks', {}).get('track', [])

        return tracks

    except (requests.RequestException, KeyError):
        return []
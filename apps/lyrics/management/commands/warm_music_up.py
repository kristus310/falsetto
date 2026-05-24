from django.core.management.base import BaseCommand
from apps.lyrics.services.api import LastFMAPI, LRCLIBAPI

class Command(BaseCommand):
    help = "Pre-populates the database with target artist portfolios"

    def add_arguments(self, parser):
        parser.add_argument('artists', nargs='+', type=str, help='Names of artists to seed')

    def handle(self, *args, **options):
        lastfm = LastFMAPI()
        lrclib = LRCLIBAPI()

        for artist in options['artists']:
            self.stdout.write(f"Caching tracks for: {artist}...")
            tracks = lastfm.get_top_tracks(artist)
            self.stdout.write(f"Found {len(tracks)} tracks. Pre-fetching lyric profiles...")

            for track in tracks[:15]:
                lrclib.get_lyrics_for_track(track, artist)

        self.stdout.write(self.style.SUCCESS("Database warming complete!"))
import logging
from django.core.management.base import BaseCommand
from apps.lyrics.services.api import LastFMAPI, LRCLIBAPI

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Pre-populates the database with top tracks and lyrics for the given artists"

    def add_arguments(self, parser):
        parser.add_argument("artists", nargs="+", type=str, help="Names of artists to seed")

    def handle(self, *args, **options):
        lastfm = LastFMAPI()
        lrclib = LRCLIBAPI()

        for artist in options["artists"]:
            self.stdout.write(f"Caching tracks for: {artist}...")
            try:
                tracks = lastfm.get_top_tracks(artist)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  Failed to fetch tracks for '{artist}': {e}"))
                logger.exception("warm_music_up: failed fetching tracks for '%s'", artist)
                continue

            if not tracks:
                self.stdout.write(self.style.WARNING(f"  No tracks found for '{artist}', skipping."))
                continue

            self.stdout.write(f"  Found {len(tracks)} tracks. Pre-fetching lyrics...")

            success = 0
            for track in tracks[:15]:
                try:
                    lrclib.get_lyrics_for_track(track, artist)
                    success += 1
                except Exception as e:
                    logger.warning(
                        "warm_music_up: lyric fetch failed for '%s' / '%s': %s",
                        artist, track.get("name"), e,
                    )

            self.stdout.write(f"  Cached lyrics for {success}/{min(len(tracks), 15)} tracks.")

        self.stdout.write(self.style.SUCCESS("Database warming complete!"))
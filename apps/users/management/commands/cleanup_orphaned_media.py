import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.users.models import UserProfile

class Command(BaseCommand):
    help = "Delete media files not referenced by any user profile"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview only, don't delete")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        avatar_dir = Path(settings.MEDIA_ROOT) / "avatars"

        if not avatar_dir.exists():
            self.stdout.write("No avatars directory found.")
            return

        files_on_disk = {f for f in avatar_dir.rglob("*") if f.is_file()}

        used_paths = set(
            Path(settings.MEDIA_ROOT) / p
            for p in UserProfile.objects.exclude(avatar="")
                                        .exclude(avatar=None)
                                        .values_list("avatar", flat=True)
        )

        orphans = files_on_disk - used_paths
        self.stdout.write(f"Found {len(orphans)} orphaned file(s).")

        for path in sorted(orphans):
            if dry_run:
                self.stdout.write(f"  [dry-run] Would delete: {path}")
            else:
                path.unlink()
                self.stdout.write(f"  Deleted: {path}")

        if not dry_run and orphans:
            self.stdout.write(self.style.SUCCESS("Cleanup complete."))
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models.fields.files import FieldFile
from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError

def validate_avatar(file):
    if isinstance(file, FieldFile):
        return

    max_mb = getattr(settings, "AVATAR_MAX_SIZE_MB", 2)
    if file.size > max_mb * 1024 * 1024:
        raise ValidationError(f"File too large. Maximum size is {max_mb} MB.")

    try:
        img = Image.open(file)
        img.load()
        file.seek(0)
    except DecompressionBombError:
        raise ValidationError("Image is too large to process safely.")
    except UnidentifiedImageError:
        raise ValidationError("Upload a valid image file (JPEG, PNG, or WebP).")
    except Exception:
        raise ValidationError("Upload a valid image file.")

    max_dim = getattr(settings, "AVATAR_MAX_DIMENSIONS", 2000)
    if img.width > max_dim or img.height > max_dim:
        raise ValidationError(
            f"Image too large. Maximum dimensions are {max_dim}×{max_dim} px."
        )

    allowed_formats = {"JPEG", "PNG", "WEBP"}
    if img.format not in allowed_formats:
        raise ValidationError(
            f"Unsupported format '{img.format}'. Upload a JPEG, PNG, or WebP."
        )
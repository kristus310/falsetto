import os
from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver
from .models import UserProfile

def _delete_file(field):
    if field and hasattr(field, "path"):
        try:
            os.remove(field.path)
        except FileNotFoundError:
            pass

@receiver(post_delete, sender=UserProfile)
def delete_avatar_on_profile_delete(sender, instance, **kwargs):
    _delete_file(instance.avatar)

@receiver(pre_save, sender=UserProfile)
def delete_old_avatar_on_update(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old = UserProfile.objects.get(pk=instance.pk)
    except UserProfile.DoesNotExist:
        return
    if old.avatar and old.avatar != instance.avatar:
        _delete_file(old.avatar)
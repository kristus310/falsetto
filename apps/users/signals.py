import os
from django.db.models.signals import pre_save, post_delete, post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import UserProfile


User = get_user_model()

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


@receiver(post_save, sender=User)
def sync_user_email_to_allauth(sender, instance, created, **kwargs):
    if created:
        return
    from allauth.account.models import EmailAddress
    email = instance.email
    if email:
        email_address, created_ea = EmailAddress.objects.get_or_create(
            user=instance,
            email__iexact=email,
            defaults={"email": email, "primary": False, "verified": False}
        )
        if not email_address.primary:
            EmailAddress.objects.filter(user=instance).exclude(pk=email_address.pk).update(primary=False)
            EmailAddress.objects.filter(pk=email_address.pk).update(primary=True)
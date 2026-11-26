"""Domain policies for status visibility, shared by HTTP and service layers."""

from django.utils import timezone

from apps.accounts.models import Contact
from .choices import StatusVisibility


def can_view_status(status_obj, user, contact_ids, saved_me_ids=None, chat_partner_ids=None, allow_expired=False):
    """Return whether ``user`` may view a status under its privacy rules.

    Callers supply the viewer's known contacts and may provide a precomputed
    set of status owners who saved the viewer to avoid repeated queries.
    ``chat_partner_ids`` remains in the signature for compatibility with the
    previous view method contract.
    """
    if status_obj.user_id == user.id:
        return False

    if status_obj.is_deleted or (not allow_expired and status_obj.expires_at <= timezone.now()):
        return False

    visibility = status_obj.visibility

    if saved_me_ids is not None:
        owner_has_saved_viewer = status_obj.user_id in saved_me_ids
    else:
        owner_has_saved_viewer = Contact.objects.filter(
            owner_id=status_obj.user_id,
            contact_user_id=user.id,
        ).exists()

    # EVERYONE includes saved/chat contacts and accepted social followers, never
    # an arbitrary stranger. Other visibility modes retain their stricter rules.
    if visibility == StatusVisibility.EVERYONE:
        return status_obj.user_id in contact_ids or owner_has_saved_viewer

    if status_obj.user_id not in contact_ids:
        return False

    if visibility == StatusVisibility.CONTACTS:
        return owner_has_saved_viewer

    listed = any(rule.user_id == user.id for rule in status_obj.privacy_rules.all())

    if visibility == StatusVisibility.CONTACTS_EXCEPT:
        return owner_has_saved_viewer and not listed

    if visibility == StatusVisibility.ONLY_SHARE_WITH:
        return listed

    # Unknown visibility values fail closed.
    return False

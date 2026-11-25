"""Helpers shared by the status views."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.accounts.models import Contact
from apps.chat.choices import RoomType
from apps.chat.models import Participant
from apps.social.models import SocialFollow


def status_contact_ids(user):
    """
    People ``user`` treats as contacts for status purposes: saved contacts
    plus everyone they already have a private conversation with.
    """
    ids = set(
        Contact.objects.filter(owner=user).values_list("contact_user_id", flat=True)
    )
    ids.update(
        Participant.objects.filter(
            room__room_type=RoomType.PRIVATE,
            room__is_active=True,
            room__participants__user=user,
        )
        .exclude(user=user)
        .values_list("user_id", flat=True)
    )
    ids.discard(user.pk)
    return ids - _blocked(user.pk)


def status_viewer_ids(user):
    """Relationships allowed to see EVERYONE statuses, including accepted follows.

    Keep this separate from ``status_contact_ids``: contact selectors and privacy
    rules still use actual contacts, while accepted followers only widen the
    explicitly public-to-followers (EVERYONE) audience.
    """
    ids = status_contact_ids(user)
    ids.update(SocialFollow.objects.filter(
        follower=user, status=SocialFollow.ACCEPTED,
    ).values_list("following_id", flat=True))
    return ids - _blocked(user.pk)


def _blocked(user_id):
    from apps.chat.utils import blocked_user_ids

    return blocked_user_ids(user_id)


def status_audience_ids(owner):
    """
    Users whose status feed may change when ``owner`` posts or deletes.
    Visibility is still enforced by the feed endpoint; this only decides
    who gets a "refresh your status list" nudge.
    """
    ids = status_contact_ids(owner)
    ids.update(
        Contact.objects.filter(contact_user=owner).values_list("owner_id", flat=True)
    )
    ids.discard(owner.pk)
    return ids - _blocked(owner.pk)


def _send(user_id, payload):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(f"chat_inbox_{user_id}", payload)


def notify_status_feed_changed(owner, action="posted", everyone=False):
    """Nudge the owner's audience (and the owner's own tabs) to refresh statuses."""
    recipients = status_audience_ids(owner)
    if everyone:
        recipients.update(SocialFollow.objects.filter(
            following=owner, status=SocialFollow.ACCEPTED,
        ).values_list("follower_id", flat=True))
    recipients.add(owner.pk)
    payload = {"type": "inbox.status_changed", "user_id": owner.pk, "action": action}
    for user_id in recipients:
        _send(user_id, payload)


def notify_status_viewed(status_obj, viewer):
    """Tell the status owner a new view was recorded (live viewer count)."""
    _send(
        status_obj.user_id,
        {
            "type": "inbox.status_changed",
            "user_id": status_obj.user_id,
            "action": "viewed",
            "status_id": status_obj.pk,
            "viewer_id": viewer.pk,
            "views_count": status_obj.views.count(),
        },
    )


def notify_status_mentioned(status_obj, user_ids):
    """Notify only explicitly mentioned viewers; audience checks happen before save."""
    recipients = {int(user_id) for user_id in user_ids if int(user_id) != status_obj.user_id}
    for user_id in recipients:
        try:
            _send(
                user_id,
                {
                    "type": "inbox.status_mentioned",
                    "user_id": user_id,
                    "author_id": status_obj.user_id,
                    "status_id": status_obj.pk,
                },
            )
        except Exception:
            # A realtime transport outage must never roll back a published status.
            pass
    if recipients:
        try:
            from apps.notifications.push import notify_status_mention

            notify_status_mention(status_obj.pk, status_obj.user_id, recipients)
        except Exception:
            pass

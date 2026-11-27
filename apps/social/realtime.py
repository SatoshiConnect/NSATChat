"""Social invalidations use the existing authenticated inbox channel layer."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


def social_post_group(post_id):
    return f"social_post_{post_id}"


def visible_social_post_ids(user, post_ids):
    # Import lazily: Social policies share chat model helpers.
    from .policies import visible_posts_for

    return set(visible_posts_for(user).filter(pk__in=post_ids).values_list("id", flat=True))


def notify_social_interaction(post_id):
    def publish():
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(
                social_post_group(post_id),
                {"type": "social.interaction_changed", "post_id": post_id},
            )

    # A failed notification must not convert a successful write into a failed HTTP response.
    transaction.on_commit(publish, robust=True)

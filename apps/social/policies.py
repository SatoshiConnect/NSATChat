from django.db.models import Q
from apps.accounts.models import Contact
from apps.chat.utils import blocked_user_ids
from .models import Post
from .models import SocialFollow, SocialMute


def visible_posts_for(user):
    """Return posts allowed by audience, accepted follows, privacy, blocks and moderation."""
    contact_authors = Contact.objects.filter(owner_id__isnull=False, contact_user=user).values("owner_id")
    followed_authors = SocialFollow.objects.filter(follower=user, status=SocialFollow.ACCEPTED).values("following_id")
    muted_authors = SocialMute.objects.filter(muter=user).values("muted_id")
    blocked = blocked_user_ids(user.id)
    return (
        Post.objects.filter(
            deleted_at__isnull=True,
            moderation_status__in=(Post.MODERATION_ACTIVE, Post.MODERATION_REVIEW),
            author__is_active=True,
            author__is_deleted=False,
        )
        .filter(
            Q(author=user)
            | Q(visibility=Post.EVERYONE)
            | Q(visibility=Post.CONTACTS, author_id__in=contact_authors)
            | Q(visibility=Post.FOLLOWERS, author_id__in=followed_authors)
        )
        .filter(Q(author=user) | Q(author__profile__social_private=False) | Q(author_id__in=followed_authors))
        .exclude(author_id__in=blocked)
        .exclude(author_id__in=muted_authors)
    )


def can_view_post(post, user):
    return visible_posts_for(user).filter(pk=post.pk).exists()

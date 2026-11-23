from django.db.models import Q
from apps.accounts.models import Contact
from apps.chat.utils import blocked_user_ids
from .models import Post


def visible_posts_for(user):
    """Public posts plus contact posts from authors who saved this user."""
    contact_authors = Contact.objects.filter(owner_id__isnull=False, contact_user=user).values("owner_id")
    blocked = blocked_user_ids(user.id)
    return (
        Post.objects.filter(deleted_at__isnull=True, author__is_active=True, author__is_deleted=False)
        .filter(Q(author=user) | Q(visibility=Post.EVERYONE) | Q(visibility=Post.CONTACTS, author_id__in=contact_authors))
        .exclude(author_id__in=blocked)
    )


def can_view_post(post, user):
    return visible_posts_for(user).filter(pk=post.pk).exists()

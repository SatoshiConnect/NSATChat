from django.conf import settings
from django.db import models


class Post(models.Model):
    CONTACTS = "CONTACTS"
    EVERYONE = "EVERYONE"
    VISIBILITY_CHOICES = ((CONTACTS, "Contacts"), (EVERYONE, "Everyone"))

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_posts")
    text = models.CharField(max_length=2000, blank=True)
    image = models.ImageField(upload_to="social/posts/%Y/%m/", blank=True, null=True)
    visibility = models.CharField(max_length=12, choices=VISIBILITY_CHOICES, default=CONTACTS, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "social_posts"
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("visibility", "created_at"))]

    def __str__(self):
        return f"Post {self.pk} by {self.author_id}"


class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_post_likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "social_post_likes"
        constraints = [models.UniqueConstraint(fields=("post", "user"), name="unique_social_post_like")]


class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_post_comments")
    text = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "social_post_comments"
        ordering = ("created_at", "id")

from django.conf import settings
from django.db import models


class Post(models.Model):
    CONTACTS = "CONTACTS"
    EVERYONE = "EVERYONE"
    VISIBILITY_CHOICES = ((CONTACTS, "Contacts"), (EVERYONE, "Everyone"))
    MODERATION_ACTIVE = "ACTIVE"
    MODERATION_REVIEW = "UNDER_REVIEW"
    MODERATION_HIDDEN = "HIDDEN"
    MODERATION_CHOICES = (
        (MODERATION_ACTIVE, "Active"),
        (MODERATION_REVIEW, "Under review"),
        (MODERATION_HIDDEN, "Hidden by moderation"),
    )

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_posts")
    text = models.CharField(max_length=2000, blank=True)
    image = models.ImageField(upload_to="social/posts/%Y/%m/", blank=True, null=True)
    visibility = models.CharField(max_length=12, choices=VISIBILITY_CHOICES, default=CONTACTS, db_index=True)
    moderation_status = models.CharField(max_length=16, choices=MODERATION_CHOICES, default=MODERATION_ACTIVE, db_index=True)
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


class PostReport(models.Model):
    REASON_SPAM = "SPAM"
    REASON_HARASSMENT = "HARASSMENT"
    REASON_HATE = "HATE"
    REASON_SEXUAL = "SEXUAL"
    REASON_VIOLENCE = "VIOLENCE"
    REASON_SCAM = "SCAM"
    REASON_OTHER = "OTHER"
    REASON_CHOICES = (
        (REASON_SPAM, "Spam or misleading"),
        (REASON_HARASSMENT, "Harassment"),
        (REASON_HATE, "Hate or abusive content"),
        (REASON_SEXUAL, "Sexual content"),
        (REASON_VIOLENCE, "Violence or dangerous content"),
        (REASON_SCAM, "Scam or fraud"),
        (REASON_OTHER, "Other"),
    )
    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    ACTIONED = "ACTIONED"
    STATUS_CHOICES = ((OPEN, "Open"), (REVIEWED, "Reviewed"), (ACTIONED, "Action taken"))

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_post_reports")
    reason = models.CharField(max_length=16, choices=REASON_CHOICES)
    details = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_social_post_reports",
    )

    class Meta:
        db_table = "social_post_reports"
        ordering = ("status", "created_at")
        constraints = [models.UniqueConstraint(fields=("post", "reporter"), name="unique_social_post_reporter")]

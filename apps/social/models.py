from django.conf import settings
from django.db import models


class Post(models.Model):
    CONTACTS = "CONTACTS"
    EVERYONE = "EVERYONE"
    FOLLOWERS = "FOLLOWERS"
    VISIBILITY_CHOICES = ((CONTACTS, "Contacts"), (FOLLOWERS, "Followers"), (EVERYONE, "Everyone"))
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


class PostAttachment(models.Model):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    KIND_CHOICES = ((IMAGE, "Image"), (VIDEO, "Video"))

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="social/attachments/%Y/%m/")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "social_post_attachments"
        ordering = ("position", "id")
        indexes = [models.Index(fields=("post", "position"))]


class PostLike(models.Model):
    REACTION_CHOICES = (("LIKE", "Like"), ("LOVE", "Love"), ("HAHA", "Haha"), ("WOW", "Wow"), ("SAD", "Sad"), ("CARE", "Care"))
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_post_likes")
    reaction = models.CharField(max_length=8, choices=REACTION_CHOICES, default="LIKE")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "social_post_likes"
        constraints = [models.UniqueConstraint(fields=("post", "user"), name="unique_social_post_like")]


class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_post_comments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    text = models.CharField(max_length=1000, blank=True)
    sticker_asset = models.ForeignKey(
        "marketplace.DigitalItemAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="social_comments",
    )
    sticker_code = models.CharField(max_length=24, blank=True, default="")
    is_reward = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "social_post_comments"
        ordering = ("created_at", "id")


class PostSave(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="saves")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_post_saves")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "social_post_saves"
        constraints = [models.UniqueConstraint(fields=("post", "user"), name="unique_social_post_save")]


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


class SocialFollow(models.Model):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    STATUS_CHOICES = ((PENDING, "Pending"), (ACCEPTED, "Accepted"))

    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_following")
    following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_followers")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACCEPTED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "social_follows"
        constraints = [
            models.UniqueConstraint(fields=("follower", "following"), name="unique_social_follow_edge"),
            models.CheckConstraint(condition=~models.Q(follower=models.F("following")), name="social_no_self_follow"),
        ]
        indexes = [models.Index(fields=("following", "status", "created_at")), models.Index(fields=("follower", "status", "created_at"))]


class SocialMute(models.Model):
    muter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_mutes")
    muted = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="muted_by_social")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "social_mutes"
        constraints = [
            models.UniqueConstraint(fields=("muter", "muted"), name="unique_social_mute_edge"),
            models.CheckConstraint(condition=~models.Q(muter=models.F("muted")), name="social_no_self_mute"),
        ]
        indexes = [models.Index(fields=("muter", "created_at"))]


class LiveStream(models.Model):
    LIVE = "LIVE"
    ENDED = "ENDED"
    STATUS_CHOICES = ((LIVE, "Live"), (ENDED, "Ended"))

    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_live_streams")
    title = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=LIVE, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat = models.DateTimeField(auto_now_add=True, db_index=True)
    viewer_limit = models.PositiveSmallIntegerField(default=1000)

    class Meta:
        db_table = "social_live_streams"
        ordering = ("-started_at", "-id")
        indexes = [models.Index(fields=("status", "started_at"), name="social_live_status_started_idx")]


class LiveStreamEvent(models.Model):
    COMMENT = "COMMENT"
    REACTION = "REACTION"
    STICKER = "STICKER"
    KIND_CHOICES = ((COMMENT, "Comment"), (REACTION, "Reaction"), (STICKER, "Sticker"))

    stream = models.ForeignKey(LiveStream, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_live_events")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, db_index=True)
    text = models.CharField(max_length=240, blank=True)
    sticker_code = models.CharField(max_length=24, blank=True)
    sticker_asset = models.ForeignKey(
        "marketplace.DigitalItemAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="live_stream_events",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "social_live_events"
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("stream", "created_at"), name="social_live_event_time_idx")]


class LiveStreamViewer(models.Model):
    stream = models.ForeignKey(LiveStream, on_delete=models.CASCADE, related_name="viewers")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_live_viewing")
    connected_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "social_live_viewers"
        constraints = [models.UniqueConstraint(fields=("stream", "user"), name="unique_social_live_viewer")]
        indexes = [models.Index(fields=("stream", "last_seen"), name="social_live_viewer_seen_idx")]

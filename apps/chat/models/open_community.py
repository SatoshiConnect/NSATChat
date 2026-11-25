from django.conf import settings
from django.db import models
from django.utils import timezone

from .chat_room import ChatRoom


class OpenCommunity(models.Model):
    """A deliberately published community backed by an existing group room."""

    class State(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        PUBLISHED = "PUBLISHED", "Published"
        SUSPENDED = "SUSPENDED", "Suspended"

    class JoinMode(models.TextChoices):
        OPEN = "OPEN", "Open"
        CODE = "CODE", "Join code"
        APPROVAL = "APPROVAL", "Admin approval"

    CATEGORY_CHOICES = (
        ("GENERAL", "General"),
        ("EDUCATION", "Education"),
        ("GAMING", "Gaming"),
        ("LOCAL", "Local and lifestyle"),
        ("TECH", "Technology"),
        ("BUSINESS", "Business"),
        ("ENTERTAINMENT", "Entertainment"),
        ("OTHER", "Other"),
    )

    room = models.OneToOneField(ChatRoom, on_delete=models.CASCADE, related_name="open_community")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_open_communities")
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING, db_index=True)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default="OTHER", db_index=True)
    join_mode = models.CharField(max_length=10, choices=JoinMode.choices, default=JoinMode.OPEN)
    searchable = models.BooleanField(default=True, db_index=True)
    preview_enabled = models.BooleanField(default=True)
    guidelines = models.TextField(blank=True, max_length=3000)
    tags = models.JSONField(default=list, blank=True)
    join_code_hash = models.CharField(max_length=128, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-published_at", "-id")
        indexes = [models.Index(fields=("state", "searchable", "category"), name="opencomm_discover_idx")]

    def publish(self):
        self.state = self.State.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=("state", "published_at", "updated_at"))


class CommunityJoinRequest(models.Model):
    class State(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    community = models.ForeignKey(OpenCommunity, on_delete=models.CASCADE, related_name="join_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="open_community_requests")
    display_name = models.CharField(max_length=50)
    answer = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_community_requests")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("community", "user"), name="opencomm_request_unique")]
        indexes = [models.Index(fields=("community", "state", "created_at"), name="opencomm_request_queue_idx")]


class OpenCommunityReport(models.Model):
    class Reason(models.TextChoices):
        SPAM = "SPAM", "Spam"
        ABUSE = "ABUSE", "Abuse or harassment"
        ILLEGAL = "ILLEGAL", "Illegal content"
        OTHER = "OTHER", "Other"

    class State(models.TextChoices):
        OPEN = "OPEN", "Open"
        REVIEWED = "REVIEWED", "Reviewed"
        ACTIONED = "ACTIONED", "Actioned"
        DISMISSED = "DISMISSED", "Dismissed"

    community = models.ForeignKey(OpenCommunity, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="open_community_reports")
    reason = models.CharField(max_length=10, choices=Reason.choices)
    details = models.CharField(max_length=1000, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_open_community_reports")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("community", "reporter"), name="opencomm_report_unique")]

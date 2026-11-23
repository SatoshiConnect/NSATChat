from django.conf import settings
from django.db import models


class AssistantControl(models.Model):
    """Admin-managed limits for the SatoshiCore AI service."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    image_generation_enabled = models.BooleanField(default=True)
    image_daily_quota = models.PositiveSmallIntegerField(default=1)
    monthly_budget_usd = models.DecimalField(max_digits=9, decimal_places=2, default="5.00")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI budget and limits"
        verbose_name_plural = "AI budget and limits"

    def __str__(self):
        return "SatoshiCore AI limits"


class AssistantUsage(models.Model):
    TASKS = [
        ("CHAT", "Chat"),
        ("ANALYZE", "Image analysis"),
        ("TRANSLATE", "Translation"),
        ("SUMMARIZE", "Summary"),
        ("IMAGE", "Image generation"),
    ]
    STATUSES = [("PENDING", "Pending"), ("OK", "Succeeded"), ("ERROR", "Failed")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    task = models.CharField(max_length=12, choices=TASKS)
    model_id = models.CharField(max_length=100)
    status = models.CharField(max_length=8, choices=STATUSES, default="PENDING")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    image_count = models.PositiveSmallIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default="0")
    ip_hash = models.CharField(max_length=64, blank=True)
    request_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "request_id"], name="assistant_usage_user_request_uniq"),
        ]
        indexes = [
            models.Index(fields=["created_at", "status"], name="chat_assist_created_50630a_idx"),
            models.Index(fields=["user", "created_at"], name="chat_assist_user_id_c87081_idx"),
        ]

    def __str__(self):
        return f"{self.get_task_display()} · {self.status} · {self.created_at:%Y-%m-%d %H:%M}"

from django.conf import settings
from django.db import models


class StatusReport(models.Model):
    SPAM = "SPAM"
    HARASSMENT = "HARASSMENT"
    HATE = "HATE"
    SEXUAL = "SEXUAL"
    VIOLENCE = "VIOLENCE"
    SCAM = "SCAM"
    OTHER = "OTHER"
    REASON_CHOICES = (
        (SPAM, "Spam or misleading"),
        (HARASSMENT, "Harassment"),
        (HATE, "Hate or abusive content"),
        (SEXUAL, "Sexual content"),
        (VIOLENCE, "Violence or dangerous content"),
        (SCAM, "Scam or fraud"),
        (OTHER, "Other"),
    )
    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    ACTIONED = "ACTIONED"
    STATUS_CHOICES = ((OPEN, "Open"), (REVIEWED, "Reviewed"), (ACTIONED, "Action taken"))

    status = models.ForeignKey("status.Status", on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="status_reports")
    reason = models.CharField(max_length=16, choices=REASON_CHOICES)
    details = models.CharField(max_length=1000, blank=True)
    state = models.CharField(max_length=12, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_status_reports",
    )

    class Meta:
        db_table = "status_reports"
        ordering = ("state", "created_at")
        constraints = [models.UniqueConstraint(fields=("status", "reporter"), name="unique_status_reporter")]

    def __str__(self):
        return f"Report #{self.pk} for status {self.status_id} ({self.state})"

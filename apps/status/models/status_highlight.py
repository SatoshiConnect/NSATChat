from django.conf import settings
from django.db import models


class StatusHighlight(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="status_highlights")
    title = models.CharField(max_length=40)
    cover_status = models.ForeignKey("status.Status", null=True, blank=True, on_delete=models.SET_NULL, related_name="highlight_covers")
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("position", "created_at", "id")
        indexes = [models.Index(fields=("owner", "position"))]

    def __str__(self):
        return f"{self.owner_id}: {self.title}"


class StatusHighlightItem(models.Model):
    highlight = models.ForeignKey(StatusHighlight, on_delete=models.CASCADE, related_name="items")
    status = models.ForeignKey("status.Status", on_delete=models.CASCADE, related_name="highlight_items")
    position = models.PositiveSmallIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "added_at", "id")
        constraints = [models.UniqueConstraint(fields=("highlight", "status"), name="uniq_status_per_highlight")]
        indexes = [models.Index(fields=("highlight", "position"))]

from django.conf import settings
from django.db import models


class StatusMention(models.Model):
    """A contact explicitly mentioned in a status update."""

    status = models.ForeignKey("status.Status", on_delete=models.CASCADE, related_name="mentions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="status_mentions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "status_mentions"
        constraints = [models.UniqueConstraint(fields=("status", "user"), name="unique_status_mention")]
        indexes = [models.Index(fields=("user", "created_at"))]

    def __str__(self):
        return f"{self.user_id} mentioned in status {self.status_id}"

from django.core import signing


def status_media_url(status_obj, viewer_id):
    """Create a five-minute capability URL; the endpoint rechecks audience rules."""
    token = signing.dumps({"status": status_obj.pk, "viewer": int(viewer_id)}, salt="status.media.v1")
    return f"/api/status/{status_obj.pk}/media/?token={token}"

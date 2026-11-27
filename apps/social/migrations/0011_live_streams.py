from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("social", "0010_postcomment_sticker_code"),
    ]

    operations = [
        migrations.CreateModel(
            name="LiveStream",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, max_length=100)),
                ("status", models.CharField(choices=[("LIVE", "Live"), ("ENDED", "Ended")], db_index=True, default="LIVE", max_length=8)),
                ("started_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("last_heartbeat", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("viewer_limit", models.PositiveSmallIntegerField(default=6)),
                ("host", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_live_streams", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "social_live_streams", "ordering": ("-started_at", "-id")},
        ),
        migrations.AddIndex(
            model_name="livestream",
            index=models.Index(fields=["status", "started_at"], name="social_live_status_started_idx"),
        ),
        migrations.CreateModel(
            name="LiveStreamEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("COMMENT", "Comment"), ("REACTION", "Reaction"), ("STICKER", "Sticker")], db_index=True, max_length=8)),
                ("text", models.CharField(blank=True, max_length=240)),
                ("sticker_code", models.CharField(blank=True, max_length=24)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_live_events", to=settings.AUTH_USER_MODEL)),
                ("stream", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="social.livestream")),
            ],
            options={"db_table": "social_live_events", "ordering": ("created_at", "id")},
        ),
        migrations.AddIndex(
            model_name="livestreamevent",
            index=models.Index(fields=["stream", "created_at"], name="social_live_event_time_idx"),
        ),
        migrations.CreateModel(
            name="LiveStreamViewer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("connected_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen", models.DateTimeField(auto_now=True)),
                ("stream", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="viewers", to="social.livestream")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_live_viewing", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "social_live_viewers"},
        ),
        migrations.AddConstraint(
            model_name="livestreamviewer",
            constraint=models.UniqueConstraint(fields=("stream", "user"), name="unique_social_live_viewer"),
        ),
        migrations.AddIndex(
            model_name="livestreamviewer",
            index=models.Index(fields=["stream", "last_seen"], name="social_live_viewer_seen_idx"),
        ),
    ]

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("chat", "0026_legacy_import_keys"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantControl",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("image_generation_enabled", models.BooleanField(default=True)),
                ("image_daily_quota", models.PositiveSmallIntegerField(default=1)),
                ("monthly_budget_usd", models.DecimalField(decimal_places=2, default="5.00", max_digits=9)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "AI budget and limits", "verbose_name_plural": "AI budget and limits"},
        ),
        migrations.CreateModel(
            name="AssistantUsage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task", models.CharField(choices=[("CHAT", "Chat"), ("ANALYZE", "Image analysis"), ("TRANSLATE", "Translation"), ("SUMMARIZE", "Summary"), ("IMAGE", "Image generation")], max_length=12)),
                ("model_id", models.CharField(max_length=100)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("OK", "Succeeded"), ("ERROR", "Failed")], default="PENDING", max_length=8)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("image_count", models.PositiveSmallIntegerField(default=0)),
                ("estimated_cost_usd", models.DecimalField(decimal_places=6, default="0", max_digits=10)),
                ("ip_hash", models.CharField(blank=True, max_length=64)),
                ("request_id", models.UUIDField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="assistantusage",
            constraint=models.UniqueConstraint(fields=("user", "request_id"), name="assistant_usage_user_request_uniq"),
        ),
        migrations.AddIndex(model_name="assistantusage", index=models.Index(fields=["created_at", "status"], name="chat_assist_created_50630a_idx")),
        migrations.AddIndex(model_name="assistantusage", index=models.Index(fields=["user", "created_at"], name="chat_assist_user_id_c87081_idx")),
    ]

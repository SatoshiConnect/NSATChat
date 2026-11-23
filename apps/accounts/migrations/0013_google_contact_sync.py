import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_satoshicore_default_about")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="allow_contact_discovery",
            field=models.BooleanField(
                default=False,
                help_text="Let verified accounts find this user through Google Contacts sync.",
            ),
        ),
        migrations.CreateModel(
            name="GoogleContactSyncState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("encrypted_sync_token", models.TextField(blank=True, default="")),
                ("consented_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("current_full_sync_id", models.UUIDField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="google_contact_sync",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "google_contact_sync_states"},
        ),
        migrations.CreateModel(
            name="GoogleContactMatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("resource_name", models.CharField(max_length=512)),
                ("last_seen_full_sync_id", models.UUIDField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "matched_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="google_contact_matchers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="google_contact_matches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "google_contact_matches"},
        ),
        migrations.AddConstraint(
            model_name="googlecontactmatch",
            constraint=models.UniqueConstraint(fields=("owner", "resource_name"), name="unique_google_contact_match"),
        ),
        migrations.AddConstraint(
            model_name="googlecontactmatch",
            constraint=models.CheckConstraint(condition=~models.Q(owner=models.F("matched_user")), name="google_contact_not_self"),
        ),
        migrations.AddIndex(
            model_name="googlecontactmatch",
            index=models.Index(fields=["owner", "matched_user"], name="google_match_owner_user_idx"),
        ),
    ]

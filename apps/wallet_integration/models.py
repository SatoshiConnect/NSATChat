from django.conf import settings
from django.db import models


class WalletLink(models.Model):
    """A public NSAT address whose ownership was proven by a wallet signature."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="nsat_wallet_link",
    )
    address = models.CharField(max_length=56, unique=True)
    verified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wallet_links"


class WalletLinkChallenge(models.Model):
    """Short-lived, one-use proof challenge. The raw token is never stored."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_digest = models.CharField(max_length=64, unique=True)
    account = models.CharField(max_length=64)
    issued_at = models.PositiveBigIntegerField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wallet_link_challenges"
        indexes = [models.Index(fields=["user", "expires_at"], name="wallet_link_user_exp_idx")]

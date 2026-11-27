from django.urls import path

from .views import (
    WalletLinkConfirmAPIView,
    WalletLinkMeAPIView,
    WalletLinkStartAPIView,
    WalletChatRecipientAPIView,
    WalletSocialRecipientAPIView,
    WalletReadAPIView,
    WalletPreflightAPIView,
    WalletSelfOpenPreflightAPIView,
    WalletSubmitAPIView,
    WalletConfirmationAPIView,
)


app_name = "wallet_integration"

urlpatterns = [
    path("read/", WalletReadAPIView.as_view(), name="read"),
    path("preflight/", WalletPreflightAPIView.as_view(), name="preflight"),
    path("self-open/preflight/", WalletSelfOpenPreflightAPIView.as_view(), name="self-open-preflight"),
    path("submit/", WalletSubmitAPIView.as_view(), name="submit"),
    path("confirmation/<str:tx_hash>/", WalletConfirmationAPIView.as_view(), name="confirmation"),
    path("link/start/", WalletLinkStartAPIView.as_view(), name="link-start"),
    path("link/confirm/", WalletLinkConfirmAPIView.as_view(), name="link-confirm"),
    path("link/me/", WalletLinkMeAPIView.as_view(), name="link-me"),
    path("chat/recipient/", WalletChatRecipientAPIView.as_view(), name="chat-recipient"),
    path("social/recipient/", WalletSocialRecipientAPIView.as_view(), name="social-recipient"),
]

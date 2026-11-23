from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    RegisterAPIView,
    LoginAPIView,
    LogoutAPIView,
    MeAPIView,
    UpdateProfileAPIView,
    ContactListCreateAPIView,
    ContactDetailAPIView,
    UserLookupAPIView,
    UserCommonGroupsAPIView,
    PrivacySettingsAPIView,
    DeleteAccountAPIView,
    GoogleLoginAPIView,
    google_login_config,
    PublicIDAPIView,
    ContactSuggestionsAPIView,
    ContactSyncAPIView,
    AddGroupMemberContactAPIView,
    AddChatParticipantContactAPIView,
)
from .google_contacts import GoogleContactSyncAPIView
from .wallet_read import WalletReadAPIView

app_name = "accounts"


urlpatterns = [
    path("register/", RegisterAPIView.as_view(), name="register"),
    path("login/", LoginAPIView.as_view(), name="login"),
    path("google/config/", google_login_config, name="google-login-config"),
    path("google/login/", GoogleLoginAPIView.as_view(), name="google-login"),
    path("logout/", LogoutAPIView.as_view(), name="logout"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", MeAPIView.as_view(), name="me"),
    path("profile/update/", UpdateProfileAPIView.as_view(), name="update-profile"),
    path("profile/public-id/", PublicIDAPIView.as_view(), name="public-id"),
    path("contacts/", ContactListCreateAPIView.as_view(), name="contact-list-create"),
    path("contacts/suggestions/", ContactSuggestionsAPIView.as_view(), name="contact-suggestions"),
    path("contacts/sync/", ContactSyncAPIView.as_view(), name="contact-sync"),
    path("contacts/google/", GoogleContactSyncAPIView.as_view(), name="google-contact-sync"),
    path("users/<int:pk>/add-contact-from-group/", AddGroupMemberContactAPIView.as_view(), name="add-group-member-contact"),
    path("users/<int:pk>/add-contact-from-chat/", AddChatParticipantContactAPIView.as_view(), name="add-chat-participant-contact"),
    path("contacts/<int:pk>/", ContactDetailAPIView.as_view(), name="contact-detail"),
    path("users/lookup/", UserLookupAPIView.as_view(), name="user-lookup"),
    path("privacy/", PrivacySettingsAPIView.as_view(), name="privacy-settings"),
    path("wallet/read/", WalletReadAPIView.as_view(), name="wallet-read"),
    path("delete/", DeleteAccountAPIView.as_view(), name="delete-account"),
    path("users/<int:pk>/common-groups/", UserCommonGroupsAPIView.as_view(), name="user-common-groups"),
]

from django.urls import path

from .views import CatalogAPIView, CreatorDashboardAPIView, CreatorDirectoryAPIView, GiftAPIView, InventoryAPIView, OwnedStickerPacksAPIView, PurchaseDisputeAPIView, PurchaseHistoryAPIView, PurchaseSimulationAPIView, ReportItemAPIView, SubmitItemAPIView

app_name = "marketplace"
urlpatterns = [
    path("items/", CatalogAPIView.as_view(), name="catalog"),
    path("items/submit/", SubmitItemAPIView.as_view(), name="submit"),
    path("items/<int:pk>/report/", ReportItemAPIView.as_view(), name="report"),
    path("items/<int:pk>/purchase-simulation/", PurchaseSimulationAPIView.as_view(), name="purchase-simulation"),
    path("inventory/", InventoryAPIView.as_view(), name="inventory"),
    path("stickers/mine/", OwnedStickerPacksAPIView.as_view(), name="owned-stickers"),
    path("purchases/", PurchaseHistoryAPIView.as_view(), name="purchases"),
    path("gifts/", GiftAPIView.as_view(), name="gifts"),
    path("creator/dashboard/", CreatorDashboardAPIView.as_view(), name="creator-dashboard"),
    path("creator/profile/", CreatorDashboardAPIView.as_view(), name="creator-profile"),
    path("creators/", CreatorDirectoryAPIView.as_view(), name="creators"),
    path("purchases/<uuid:purchase_id>/dispute/", PurchaseDisputeAPIView.as_view(), name="purchase-dispute"),
]

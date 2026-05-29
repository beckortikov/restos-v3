from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    IngredientViewSet,
    SemiFinishedTypeViewSet,
    StockMovementViewSet,
)
from .views_8a import (
    InventoryCheckViewSet,
    ReceiptsImportMixin,
    StockReceiptViewSet,
    StockWriteoffViewSet,
    SupplierViewSet,
    SupplyExpenseViewSet,
)


# Phase 8A — StockReceiptViewSet с импортом XLSX
class _StockReceiptVS(ReceiptsImportMixin, StockReceiptViewSet):
    pass


router = DefaultRouter()
router.register("ingredients", IngredientViewSet, basename="inventory-ingredient")
router.register("semi", SemiFinishedTypeViewSet, basename="inventory-semi")
router.register("stock-movements", StockMovementViewSet, basename="inventory-movement")
# Phase 8A
router.register("suppliers", SupplierViewSet, basename="inventory-supplier")
router.register("receipts", _StockReceiptVS, basename="inventory-receipt")
router.register("writeoffs", StockWriteoffViewSet, basename="inventory-writeoff")
router.register("supply-expenses", SupplyExpenseViewSet, basename="inventory-supply-expense")
router.register("checks", InventoryCheckViewSet, basename="inventory-check")

urlpatterns = [path("", include(router.urls))]

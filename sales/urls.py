# sales/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TransactionViewSet, TransactionHistoryListView, CashierSalesSummaryView

router = DefaultRouter()
router.register(r'transactions', TransactionViewSet, basename='transaction')
router.register(r'transaction-history', TransactionHistoryListView, basename='transaction-history')

urlpatterns = [
    path('', include(router.urls)),
    path('cashier-summary/', CashierSalesSummaryView.as_view(), name='cashier-summary'),
]

# Примеры использования (все через GET):
#
# GET /api/sales/cashier-summary/
# - Общая сводка всех кассиров магазина
#
# GET /api/sales/cashier-summary/?cashier_id=11
# - Сводка конкретного кассира
#
# GET /api/sales/cashier-summary/?start_date=2025-09-01&end_date=2025-09-09
# - Сводка за период
#
# GET /api/sales/cashier-summary/?cashier_id=11&detailed=true
# - Детальная статистика кассира с разбивкой по дням и топ товарами
#
# GET /api/sales/cashier-summary/?status=completed
# - Только завершенные транзакции (по умолчанию)
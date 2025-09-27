from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .models import SalesSummary, ProductAnalytics, CustomerAnalytics, SupplierAnalytics, CashRegister, CategoryAnalytics
from .serializers import (SalesSummarySerializer, ProductAnalyticsSerializer, CustomerAnalyticsSerializer, 
                          SupplierAnalyticsSerializer, CategoryAnalyticsSerializer,
                          CashRegisterSerializer, CashHistorySerializer, CashRegisterCloseSerializer,
                          WarehouseProductSerializer, BatchDetailSerializer)
from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, Count, F, Avg, Q
from datetime import datetime, timedelta
from rest_framework.views import APIView
from decimal import Decimal
from rest_framework.exceptions import PermissionDenied
from django_filters import rest_framework as filters
import pandas as pd
from io import BytesIO
import xlsxwriter


from sales.serializers import FilteredTransactionHistorySerializer
from sales.models import Transaction, TransactionHistory
from .funcs import get_date_range
from .pagination import OptionalPagination

from inventory.models import ProductBatch, Product
from stores.mixins import StoreViewSetMixin  # ← ДОБАВЛЯЕМ МИКСИН
import logging

logger = logging.getLogger(__name__)


class AnalyticsPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.groups.filter(name__in=['admin', 'manager', 'owner']).exists()


class CashRegisterViewSet(StoreViewSetMixin, viewsets.ModelViewSet):
    """
    ✅ VIEWSET КАССЫ — просмотр баланса и снятие
    """
    queryset = CashRegister.objects.filter(is_open=True)  # Только открытые смены
    serializer_class = CashRegisterSerializer
    permission_classes = [AnalyticsPermission]
    
    def get_queryset(self):
        store = self.get_current_store()
        return super().get_queryset().filter(store=store)

    def retrieve(self, request, *args, **kwargs):
        """GET: текущий баланс кассы"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'current_balance': serializer.data['current_balance'],
            'formatted': serializer.data['balance_formatted'],
            'is_open': instance.is_open,
            'message': f"На кассе {serializer.data['balance_formatted']}. Смена открыта."
        })

    @action(detail=True, methods=['post'])
    def withdraw(self, request, pk=None):
        """POST: кнопка 'забери' — снимаем сумму"""
        instance = self.get_object()
        amount = request.data.get('amount')
        notes = request.data.get('notes', 'Выдача наличных')
        
        if not amount:
            return Response({'error': 'Укажите сумму'}, status=400)
        
        try:
            withdrawn = instance.withdraw(amount, request.user, notes)
            return Response({
                'success': True,
                'withdrawn': float(withdrawn),
                'new_balance': float(instance.current_balance),
                'message': f"Снято {withdrawn:,.0f} сум. Остаток: {instance.current_balance:,.0f} сум."
            })
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

    @action(detail=False, methods=['post'])
    def open_shift(self, request):
        """POST: открыть новую смену (если нужно)"""
        store = self.get_current_store()
        # Создаём, если нет открытой
        if CashRegister.objects.filter(store=store, is_open=True).exists():
            return Response({'error': 'Смена уже открыта'}, status=400)
        
        target = request.data.get('target_balance', Decimal('0.00'))
        instance = CashRegister.objects.create(store=store, target_balance=target)
        return Response({'id': instance.id, 'message': 'Смена открыта. Баланс: 0 сум'})
    
    @action(detail=True, methods=['post'])
    def close_shift(self, request, pk=None):
        """POST: закрыть смену — ритуал конца дня"""
        instance = self.get_object()

        serializer = CashRegisterCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        actual_balance = serializer.validated_data['actual_balance']
        notes = serializer.validated_data.get('notes', "")

        try:
            result = instance.close_shift(actual_balance, request.user, notes)
            updated_serializer = self.get_serializer(instance)
            return Response({
                "success": True,
                "status": result["status"],
                "discrepancy": float(result["discrepancy"]),
                "message": result["message"],
                "final_balance": float(instance.closed_balance),
                "closed_at": instance.closed_at.isoformat() if instance.closed_at else None,
                "cash_register": updated_serializer.data,
                "financial_summary_id": result["summary_id"],
            })
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """GET: история операций по кассе"""
        instance = self.get_object()
        history = instance.history.select_related('user').order_by('-timestamp')[:50]  # Последние 50
        serializer = CashHistorySerializer(history, many=True)
        return Response({
            'cash_register': instance.id,
            'total_operations': history.count(),
            'history': serializer.data
        })

class SupplierAnalyticsViewSet(StoreViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet для аналитики поставщиков — чей товар улетает, а чей пылится.
    """
    queryset = SupplierAnalytics.objects.all()  # Если persistent; иначе переопредели get_queryset для агрегации
    serializer_class = SupplierAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated, AnalyticsPermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['supplier', 'date']
    ordering_fields = ['date', 'total_revenue', 'total_margin']
    ordering = ['-date']

    def get_queryset(self):
        current_store = self.get_current_store()
        if not current_store:
            raise PermissionDenied("Магазин не определен")
        return super().get_queryset().filter(store=current_store)

    @swagger_auto_schema(
        operation_description="Получить топ поставщиков по выручке/марже",
        manual_parameters=[
            openapi.Parameter('limit', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, default=10),
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='date'),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='date'),
            openapi.Parameter('metric', openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=['revenue', 'margin', 'turnover'], default='revenue')
        ]
    )
    @action(detail=False, methods=['get'])
    def top_suppliers(self, request):
        current_store = self.get_current_store()
        if not current_store:
            return Response({'error': 'Магазин не определен'}, status=400)

        limit = int(request.query_params.get('limit', 10))
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date', timezone.now().date())
        metric = request.query_params.get('metric', 'revenue')  # Сортировка по revenue/margin/turnover

        # Если модель не persistent, агрегируем из StockHistory
        from inventory.models import StockHistory  # Импорт здесь, чтобы избежать цикла
        sales_qs = StockHistory.objects.filter(
            store=current_store,
            operation_type='SALE',
            batch__isnull=False
        )
        if start_date:
            sales_qs = sales_qs.filter(date_only__gte=start_date)
        if end_date:
            sales_qs = sales_qs.filter(date_only__lte=end_date)

        supplier_data = sales_qs.values('batch__supplier').annotate(
            total_sold=Sum(F('quantity_change') * -1),
            total_revenue=Sum(F('quantity_change') * -1 * F('sale_price_at_time')),
            total_cost=Sum(F('quantity_change') * -1 * F('purchase_price_at_time')),
            total_margin=Sum(
                (F('quantity_change') * -1 * F('sale_price_at_time')) -
                (F('quantity_change') * -1 * F('purchase_price_at_time'))
            ),
            unique_products=Count('product', distinct=True),
            transactions_count=Count('id'),
            avg_margin_pct=Avg(
                ((F('sale_price_at_time') - F('purchase_price_at_time')) / F('sale_price_at_time')) * 100,
                filter=Q(sale_price_at_time__gt=0)
            ),
            turnover_rate=Sum(F('quantity_change') * -1) / Avg('product__stock__quantity')  # Адаптируй
        ).order_by(f'-total_{metric}')[:limit]  # Динамическая сортировка

        # Инсайты
        insights = self._get_supplier_insights(supplier_data)

        return Response({
            'store': {'id': str(current_store.id), 'name': current_store.name},
            'top_suppliers': list(supplier_data),
            'insights': insights,
            'period': {'start_date': start_date, 'end_date': end_date},
            'metric': metric,
            'limit': limit
        })

    def _get_supplier_insights(self, data):
        # Аналогично моему предыдущему совету: генерируем рекомендации
        if not data:
            return [{'type': 'no_data', 'title': 'Нет данных', 'description': 'Проверьте продажи и партии.'}]
        
        insights = []
        top = data[0]
        insights.append({
            'type': 'top_supplier',
            'title': f'Лучший: {top["batch__supplier"]}',
            'description': f'Выручка {top["total_revenue"]:,}, маржа {top["total_margin"]:,}.',
            'action': 'Увеличьте объёмы.'
        })
        
        low_margin = [s for s in data if s['avg_margin_pct'] < 20]
        if low_margin:
            insights.append({
                'type': 'low_margin',
                'title': 'Проблемные по марже',
                'description': f'{len(low_margin)} с маржей <20%.',
                'action': 'Переговоры или замена.'
            })
        
        return insights

class SalesAnalyticsViewSet(StoreViewSetMixin, viewsets.ReadOnlyModelViewSet):  # ← ДОБАВЛЯЕМ МИКСИН
    """
    Простой ViewSet для аналитики продаж и закупок
    """
    queryset = SalesSummary.objects.all()  # ← ДОБАВЛЯЕМ БАЗОВЫЙ QUERYSET
    serializer_class = SalesSummarySerializer
    permission_classes = [permissions.IsAuthenticated, AnalyticsPermission]
    pagination_class = OptionalPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['date', 'payment_method', 'cashier']
    ordering_fields = ['date', 'total_amount']
    ordering = ['-date']

    @swagger_auto_schema(
        operation_description="Получить финансовую сводку: продажи, закупки, прибыль за период",
        manual_parameters=[
            openapi.Parameter(
                'start_date',
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                format='date',
                description="Дата начала периода (YYYY-MM-DD)"
            ),
            openapi.Parameter(
                'end_date',
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                format='date',
                description="Дата окончания периода (YYYY-MM-DD, по умолчанию сегодня)"
            ),
            openapi.Parameter(
                'cashier',
                openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description="Фильтр по ID кассира"
            )
        ]
    )
    @action(detail=False, methods=['get'])
    def financial_summary(self, request):
        """
        Простая финансовая сводка: сколько потратили на закупки и сколько заработали
        """
        # ✅ ПОЛУЧАЕМ ТЕКУЩИЙ МАГАЗИН
        current_store = self.get_current_store()
        if not current_store:
            return Response({
                'error': 'Магазин не определен. Переавторизуйтесь или выберите магазин.',
                'debug_info': {
                    'user': request.user.username,
                    'has_current_store': hasattr(request.user, 'current_store'),
                    'current_store_value': getattr(request.user, 'current_store', None)
                }
            }, status=400)

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date', timezone.now().date())
        cashier_id = request.query_params.get('cashier')

        # Парсинг дат
        if isinstance(end_date, str):
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                end_date = timezone.now().date()

        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                start_date = None

        # Валидация кассира
        if cashier_id:
            try:
                cashier_id = int(cashier_id)
            except ValueError:
                cashier_id = None

        # === ПРОДАЖИ (ТОЛЬКО ТЕКУЩИЙ МАГАЗИН) ===
        sales_qs = SalesSummary.objects.filter(store=current_store)  # ← ФИЛЬТР ПО МАГАЗИНУ

        if start_date:
            sales_qs = sales_qs.filter(date__gte=start_date)
        if end_date:
            sales_qs = sales_qs.filter(date__lte=end_date)
        if cashier_id:
            sales_qs = sales_qs.filter(cashier_id=cashier_id)

        # Группировка по методу оплаты
        payment_summary = list(
            sales_qs.values('payment_method')
            .annotate(
                total_amount=Sum('total_amount'),
                total_transactions=Sum('total_transactions'),
                total_items_sold=Sum('total_items_sold')
            )
            .order_by('payment_method')
        )

        # Общие суммы по продажам
        sales_totals = sales_qs.aggregate(
            total_amount=Sum('total_amount'),
            total_transactions=Sum('total_transactions'),
            total_items_sold=Sum('total_items_sold')
        )

        sales_revenue = sales_totals['total_amount'] or Decimal('0.00')

        # === ЗАКУПКИ (ТОЛЬКО ТЕКУЩИЙ МАГАЗИН) ===
        purchase_qs = ProductBatch.objects.filter(
            store=current_store,  # ← ФИЛЬТР ПО МАГАЗИНУ
            purchase_price__isnull=False
        )

        if start_date:
            purchase_qs = purchase_qs.filter(created_at__date__gte=start_date)
        if end_date:
            purchase_qs = purchase_qs.filter(created_at__date__lte=end_date)

        # Правильный расчет суммы закупок
        total_purchase_cost = Decimal('0.00')
        total_purchase_quantity = 0

        for batch in purchase_qs:
            if batch.purchase_price and batch.quantity:
                batch_cost = batch.purchase_price * batch.quantity
                total_purchase_cost += batch_cost
                total_purchase_quantity += batch.quantity

        # === РАСЧЕТ ПРИБЫЛИ ===
        simple_profit = sales_revenue - total_purchase_cost

        # Рентабельность
        if sales_revenue > 0:
            profit_margin = (simple_profit / sales_revenue * 100)
        else:
            profit_margin = Decimal('0.00')

        response_data = {
            # Информация о магазине
            'store': {
                'id': str(current_store.id),
                'name': current_store.name
            },

            # Продажи
            'sales': {
                'total_revenue': sales_revenue,
                'total_transactions': sales_totals['total_transactions'] or 0,
                'total_items_sold': sales_totals['total_items_sold'] or 0,
                'payment_summary': payment_summary,
            },

            # Закупки
            'purchases': {
                'total_spent': total_purchase_cost,
                'total_quantity': total_purchase_quantity,
                'total_batches': purchase_qs.count(),
                'average_unit_cost': (total_purchase_cost / total_purchase_quantity) if total_purchase_quantity > 0 else Decimal('0.00')
            },

            # Итог
            'summary': {
                'revenue': sales_revenue,
                'costs': total_purchase_cost,
                'profit': simple_profit,
                'profit_margin': round(profit_margin, 2)
            },

            # Период
            'period': {
                'start_date': start_date,
                'end_date': end_date,
                'cashier_id': cashier_id
            }
        }

        logger.info(f"Financial summary for store {current_store.name}: revenue={sales_revenue}, costs={total_purchase_cost}, profit={simple_profit}")
        return Response(response_data)

    @action(detail=False, methods=['get'])
    def purchases_detail(self, request):
        """
        Детализация по закупкам (только текущий магазин)
        """
        # ✅ ПОЛУЧАЕМ ТЕКУЩИЙ МАГАЗИН
        current_store = self.get_current_store()
        if not current_store:
            return Response({'error': 'Магазин не определен'}, status=400)

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date', timezone.now().date())
        product_id = request.query_params.get('product_id')

        # Парсинг дат
        if isinstance(end_date, str):
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                end_date = timezone.now().date()

        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                start_date = None

        # Базовый queryset С ФИЛЬТРОМ ПО МАГАЗИНУ
        batches_qs = ProductBatch.objects.select_related('product').filter(
            store=current_store,  # ← ФИЛЬТР ПО МАГАЗИНУ
            purchase_price__isnull=False
        )

        # Остальные фильтры
        if start_date:
            batches_qs = batches_qs.filter(created_at__date__gte=start_date)
        if end_date:
            batches_qs = batches_qs.filter(created_at__date__lte=end_date)
        if product_id:
            try:
                batches_qs = batches_qs.filter(product_id=int(product_id))
            except ValueError:
                pass

        # Собираем данные по закупкам
        purchases_data = []
        total_cost = Decimal('0.00')
        total_quantity = 0

        for batch in batches_qs.order_by('-created_at'):
            batch_total = batch.purchase_price * batch.quantity
            total_cost += batch_total
            total_quantity += batch.quantity

            purchases_data.append({
                'id': batch.id,
                'product_id': batch.product.id,
                'product_name': batch.product.name,
                'quantity': batch.quantity,
                'unit_price': batch.purchase_price,
                'total_cost': batch_total,
                'supplier': batch.supplier,
                'date': batch.created_at.date(),
                'expiration_date': batch.expiration_date,
            })

        return Response({
            'store': {
                'id': str(current_store.id),
                'name': current_store.name
            },
            'purchases': purchases_data,
            'summary': {
                'total_batches': len(purchases_data),
                'total_quantity': total_quantity,
                'total_cost': total_cost,
                'average_unit_cost': (total_cost / total_quantity) if total_quantity > 0 else Decimal('0.00')
            },
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'product_id': product_id
            }
        })

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Оригинальный метод summary (для обратной совместимости)
        """
        # ✅ ПОЛУЧАЕМ ТЕКУЩИЙ МАГАЗИН
        current_store = self.get_current_store()
        if not current_store:
            return Response({'error': 'Магазин не определен'}, status=400)

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date', timezone.now().date())
        cashier_id = request.query_params.get('cashier')

        # ФИЛЬТРУЕМ ПО МАГАЗИНУ
        queryset = SalesSummary.objects.filter(store=current_store)

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        if cashier_id:
            try:
                cashier_id = int(cashier_id)
                queryset = queryset.filter(cashier_id=cashier_id)
            except ValueError:
                pass

        # Группировка по методу оплаты
        payment_summary = list(
            queryset.values('payment_method')
            .annotate(
                total_amount=Sum('total_amount'),
                total_transactions=Sum('total_transactions'),
                total_items_sold=Sum('total_items_sold')
            )
            .order_by('payment_method')
        )

        # Общие суммы
        totals = queryset.aggregate(
            total_amount=Sum('total_amount'),
            total_transactions=Sum('total_transactions'),
            total_items_sold=Sum('total_items_sold')
        )

        return Response({
            'store': {
                'id': str(current_store.id),
                'name': current_store.name
            },
            'payment_summary': payment_summary,
            'total_amount': totals['total_amount'] or 0,
            'total_transactions': totals['total_transactions'] or 0,
            'total_items_sold': totals['total_items_sold'] or 0
        })


class ProductAnalyticsViewSet(StoreViewSetMixin, viewsets.ReadOnlyModelViewSet):  # ← ДОБАВЛЯЕМ МИКСИН
    """
    ViewSet для аналитики товаров.
    """
    queryset = ProductAnalytics.objects.select_related('product').all()  # ← ДОБАВЛЯЕМ БАЗОВЫЙ QUERYSET
    serializer_class = ProductAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated, AnalyticsPermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['product', 'date']
    ordering_fields = ['date', 'quantity_sold', 'revenue']
    ordering = ['-date']

    @swagger_auto_schema(
        operation_description="Получить топ продаваемых товаров",
        manual_parameters=[
            openapi.Parameter('limit', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, default=10),
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='date'),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='date')
        ]
    )
    @action(detail=False, methods=['get'])
    def top_products(self, request):
        # ✅ ПОЛУЧАЕМ ТЕКУЩИЙ МАГАЗИН
        current_store = self.get_current_store()
        if not current_store:
            return Response({'error': 'Магазин не определен'}, status=400)

        limit = int(request.query_params.get('limit', 10))
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date', datetime.today().date())

        # ФИЛЬТРУЕМ ПО ТОВАРАМ ТЕКУЩЕГО МАГАЗИНА
        queryset = ProductAnalytics.objects.filter(
            product__store=current_store  # ← ФИЛЬТР ПО МАГАЗИНУ
        )

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        top_products = queryset.values('product__name').annotate(
            total_quantity=Sum('quantity_sold'),
            total_revenue=Sum('revenue')
        ).order_by('-total_quantity')[:limit]

        return Response({
            'store': {
                'id': str(current_store.id),
                'name': current_store.name
            },
            'top_products': top_products,
            'limit': limit
        })


class CustomerAnalyticsViewSet(StoreViewSetMixin, viewsets.ReadOnlyModelViewSet):  # ← ДОБАВЛЯЕМ МИКСИН
    """
    ViewSet для аналитики клиентов.
    """
    queryset = CustomerAnalytics.objects.select_related('customer').all()  # ← ДОБАВЛЯЕМ БАЗОВЫЙ QUERYSET
    serializer_class = CustomerAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated, AnalyticsPermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['customer', 'date']
    ordering_fields = ['date', 'total_purchases', 'transaction_count', 'debt_added']
    ordering = ['-date']

    @swagger_auto_schema(
        operation_description="Получить топ клиентов по покупкам",
        manual_parameters=[
            openapi.Parameter('limit', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, default=10),
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='date'),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='date')
        ]
    )
    @action(detail=False, methods=['get'])
    def top_customers(self, request):
        # ✅ ПОЛУЧАЕМ ТЕКУЩИЙ МАГАЗИН
        current_store = self.get_current_store()
        if not current_store:
            return Response({'error': 'Магазин не определен'}, status=400)

        limit = int(request.query_params.get('limit', 10))
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date', datetime.today().date())

        # ФИЛЬТРУЕМ ПО КЛИЕНТАМ ТЕКУЩЕГО МАГАЗИНА
        queryset = CustomerAnalytics.objects.filter(
            customer__store=current_store  # ← ФИЛЬТР ПО МАГАЗИНУ
        )

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        top_customers = queryset.values('customer__full_name', 'customer__phone').annotate(
            total_purchases=Sum('total_purchases'),
            total_transactions=Sum('transaction_count'),
            total_debt=Sum('debt_added')
        ).order_by('-total_purchases')[:limit]

        return Response({
            'store': {
                'id': str(current_store.id),
                'name': current_store.name
            },
            'top_customers': top_customers,
            'limit': limit
        })


class TransactionsHistoryByDayView(StoreViewSetMixin, APIView):  # ← ДОБАВЛЯЕМ МИКСИН


    def get(self, request):
        # ✅ ПОЛУЧАЕМ ТЕКУЩИЙ МАГАЗИН
        current_store = self.get_current_store()
        if not current_store:
            return Response({"error": "Магазин не определен"}, status=400)

        date_from = request.GET.get("date_from")
        date_to = request.GET.get("date_to")

        if not date_from or not date_to:
            return Response({"error": "Uncorrect datas"})

        try:
            dates = get_date_range(date_from, date_to)
            transactions_list = []

            for date in dates:
                # ФИЛЬТРУЕМ ПО МАГАЗИНУ
                transactions = TransactionHistory.objects.filter(
                    store=current_store,  # ← ФИЛЬТР ПО МАГАЗИНУ
                    created_at__date=date
                ).all()

                transactions = FilteredTransactionHistorySerializer(transactions, many=True).data

                if transactions:
                    amounts = 0
                    for transaction in transactions:
                        try:
                            amount = float(transaction["parsed_details"]["total_amount"])
                        except:
                            amount = 0
                        amounts += amount
                    transactions_list.append({date: amounts})

            return Response({
                'store': {
                    'id': str(current_store.id),
                    'name': current_store.name
                },
                'transactions_by_day': transactions_list
            })
        except Exception as e:
            return Response({"error": str(e)})
        



class CategoryAnalyticsViewSet(StoreViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = CategoryAnalyticsSerializer

    def get_queryset(self):
        store = self.get_current_store()
        if not store:
            return CategoryAnalytics.objects.none()

        qs = CategoryAnalytics.objects.filter(store=store)

        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from and date_to:
            start = parse_date(date_from)
            end = parse_date(date_to)
            if start and end:
                qs = qs.filter(date__range=[start, end])

        # Агрегируем по категории
        qs = qs.values('category', 'category__name').annotate(
            total_quantity_sold=Sum('total_quantity_sold'),
            total_revenue=Sum('total_revenue'),
            products_count=Sum('products_count'),
            transactions_count=Sum('transactions_count'),
            unique_products_sold=Sum('unique_products_sold'),
            average_transaction_amount=Avg('average_transaction_amount')
        ).order_by('-total_revenue')

        return qs

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()[:5]  # топ-5 категорий по выручке
        return Response(list(qs))

class WarehouseAnalyticsFilter(filters.FilterSet):
    """Фильтры для складской аналитики"""
    
    # Основные фильтры
    category = filters.NumberFilter(field_name='category__id')
    has_stock = filters.BooleanFilter(method='filter_has_stock')
    low_stock = filters.BooleanFilter(method='filter_low_stock')
    
    # Фильтры по поставщикам
    supplier = filters.CharFilter(method='filter_supplier')
    supplier_country = filters.CharFilter(method='filter_supplier_country')
    
    # Фильтры по датам
    batch_date_from = filters.DateFilter(method='filter_batch_date_from')
    batch_date_to = filters.DateFilter(method='filter_batch_date_to')
    expiration_soon = filters.BooleanFilter(method='filter_expiration_soon')
    
    # Фильтры по ценам
    price_min = filters.NumberFilter(field_name='sale_price', lookup_expr='gte')
    price_max = filters.NumberFilter(field_name='sale_price', lookup_expr='lte')
    
    # Фильтры по размерам
    size = filters.NumberFilter(method='filter_by_size')
    has_sizes = filters.BooleanFilter(field_name='has_sizes')
    
    # Поиск
    search = filters.CharFilter(method='filter_search')
    barcode = filters.CharFilter(field_name='barcode', lookup_expr='icontains')
    
    class Meta:
        model = Product
        fields = []
    
    def filter_has_stock(self, queryset, name, value):
        if value:
            return queryset.filter(stock__quantity__gt=0)
        return queryset.filter(Q(stock__quantity=0) | Q(stock__isnull=True))
    
    def filter_low_stock(self, queryset, name, value):
        if value:
            # Считаем низким остаток < 10 единиц
            return queryset.filter(stock__quantity__lt=10, stock__quantity__gt=0)
        return queryset
    
    def filter_supplier(self, queryset, name, value):
        return queryset.filter(batches__supplier__icontains=value).distinct()
    
    def filter_supplier_country(self, queryset, name, value):
        return queryset.filter(batches__supplier_country__icontains=value).distinct()
    
    def filter_batch_date_from(self, queryset, name, value):
        return queryset.filter(batches__created_at__date__gte=value).distinct()
    
    def filter_batch_date_to(self, queryset, name, value):
        return queryset.filter(batches__created_at__date__lte=value).distinct()
    
    def filter_expiration_soon(self, queryset, name, value):
        if value:
            soon_date = timezone.now().date() + timedelta(days=30)
            return queryset.filter(
                batches__expiration_date__lte=soon_date,
                batches__quantity__gt=0
            ).distinct()
        return queryset
    
    def filter_by_size(self, queryset, name, value):
        return queryset.filter(
            batches__size__id=value,
            batches__quantity__gt=0
        ).distinct()
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value) |
            Q(barcode__icontains=value) |
            Q(category__name__icontains=value)
        )

from users.models import Employee

class WarehouseAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet для полной складской аналитики
    """
    serializer_class = WarehouseProductSerializer
    permission_classes = [AnalyticsPermission]
    filterset_class = WarehouseAnalyticsFilter
    filter_backends = [filters.DjangoFilterBackend]
    
    def get_queryset(self):
        try:
            employee = self.request.user.employee  # если OneToOneField
            store = employee.store
        except Employee.DoesNotExist:
            store = None

        if store:
            return Product.objects.filter(
                store=store,
                is_deleted=False
            ).select_related(
                'category', 'stock', 'custom_unit'
            ).prefetch_related(
                'batches', 'available_sizes', 'attributes'
            )
        else:
            # Если сотрудник не привязан к магазину, можно вернуть пустой queryset
            return Product.objects.none()
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Общая сводка по складу"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Подсчет общей стоимости с учетом фильтров
        total_value_uzs = Decimal('0')
        total_value_usd = Decimal('0')
        total_items = 0
        low_stock_items = 0
        expiring_items = 0
        
        for product in queryset:
            batches = product.batches.filter(quantity__gt=0)
            
            for batch in batches:
                total_items += 1
                
                if batch.purchase_price:
                    total_value_uzs += batch.purchase_price * batch.quantity
                
                if batch.purchase_price_usd:
                    total_value_usd += batch.purchase_price_usd * batch.quantity
                elif batch.purchase_price and batch.purchase_rate and batch.purchase_rate > 0:
                    total_value_usd += (batch.purchase_price / batch.purchase_rate) * batch.quantity
                
                if batch.expiration_date:
                    days_until = (batch.expiration_date - timezone.now().date()).days
                    if days_until <= 30:
                        expiring_items += 1
            
            if hasattr(product, 'stock') and product.stock.quantity < 10:
                low_stock_items += 1
        
        # Текущий курс
        from inventory.models import ExchangeRate
        latest_rate = ExchangeRate.objects.order_by('-date').first()
        current_rate = latest_rate.usd_rate if latest_rate else Decimal('12500')
        
        # Группировка по категориям
        category_breakdown = queryset.values(
            'category__name'
        ).annotate(
            count=Count('id'),
            total_stock=Sum('stock__quantity')
        )
        
        # Группировка по поставщикам
        supplier_breakdown = ProductBatch.objects.filter(
            product__in=queryset,
            quantity__gt=0
        ).values('supplier', 'supplier_country').annotate(
            total_products=Count('product', distinct=True),
            total_value=Sum(F('quantity') * F('purchase_price'))
        )[:10]  # Топ-10 поставщиков
        
        return Response({
            'total_products': queryset.count(),
            'total_batches': total_items,
            'low_stock_items': low_stock_items,
            'expiring_soon': expiring_items,
            'warehouse_value': {
                'uzs': float(total_value_uzs),
                'usd': float(total_value_usd),
                'current_rate': float(current_rate),
                'uzs_at_current_rate': float(total_value_usd * current_rate)
            },
            'category_breakdown': list(category_breakdown),
            'top_suppliers': [{
                'supplier': item['supplier'] or 'Не указан',
                'country': item['supplier_country'] or 'Не указана',
                'products': item['total_products'],
                'value_uzs': float(item['total_value']) if item['total_value'] else 0
            } for item in supplier_breakdown]
        })
    
    @action(detail=False, methods=['get'])
    def export_excel(self, request):
        """Экспорт аналитики в Excel"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Создаем Excel файл в памяти
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        
        # Форматы
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4CAF50',
            'font_color': 'white',
            'border': 1
        })
        
        money_format = workbook.add_format({
            'num_format': '#,##0.00',
            'border': 1
        })
        
        qty_format = workbook.add_format({
            'num_format': '#,##0.000',
            'border': 1
        })
        
        # Лист 1: Общая информация
        ws_summary = workbook.add_worksheet('Сводка')
        
        # Заголовки
        headers = [
            'Артикул', 'Наименование', 'Категория', 'Ед.изм',
            'Остаток', 'Цена продажи', 'Стоимость склада (UZS)',
            'Стоимость склада (USD)', 'Кол-во партий'
        ]
        
        for col, header in enumerate(headers):
            ws_summary.write(0, col, header, header_format)
        
        row = 1
        total_uzs = Decimal('0')
        total_usd = Decimal('0')
        
        for product in queryset:
            stock_qty = product.stock.quantity if hasattr(product, 'stock') else 0
            batches = product.batches.filter(quantity__gt=0)
            
            value_uzs = sum(b.purchase_price * b.quantity for b in batches if b.purchase_price)
            value_usd = sum(
                b.purchase_price_usd * b.quantity if b.purchase_price_usd 
                else (b.purchase_price / b.purchase_rate * b.quantity if b.purchase_rate else 0)
                for b in batches
            )
            
            ws_summary.write(row, 0, product.barcode or '')
            ws_summary.write(row, 1, product.name)
            ws_summary.write(row, 2, product.category.name)
            ws_summary.write(row, 3, product.unit_display)
            ws_summary.write(row, 4, float(stock_qty), qty_format)
            ws_summary.write(row, 5, float(product.sale_price), money_format)
            ws_summary.write(row, 6, float(value_uzs), money_format)
            ws_summary.write(row, 7, float(value_usd), money_format)
            ws_summary.write(row, 8, batches.count())
            
            total_uzs += value_uzs
            total_usd += value_usd
            row += 1
        
        # Итоги
        ws_summary.write(row + 1, 5, 'ИТОГО:', header_format)
        ws_summary.write(row + 1, 6, float(total_uzs), money_format)
        ws_summary.write(row + 1, 7, float(total_usd), money_format)
        
        # Лист 2: Детализация по партиям
        ws_batches = workbook.add_worksheet('Партии')
        
        batch_headers = [
            'Товар', 'Количество', 'Цена закупки', 'Поставщик',
            'Страна', 'Накладная', 'Дата поступления', 'Срок годности'
        ]
        
        for col, header in enumerate(batch_headers):
            ws_batches.write(0, col, header, header_format)
        
        row = 1
        for product in queryset:
            for batch in product.batches.filter(quantity__gt=0):
                ws_batches.write(row, 0, product.name)
                ws_batches.write(row, 1, float(batch.quantity), qty_format)
                ws_batches.write(row, 2, float(batch.purchase_price) if batch.purchase_price else 0, money_format)
                ws_batches.write(row, 3, batch.supplier or '')
                ws_batches.write(row, 4, batch.supplier_country or '')
                ws_batches.write(row, 5, batch.invoice_number or '')
                ws_batches.write(row, 6, batch.created_at.strftime('%d.%m.%Y'))
                ws_batches.write(row, 7, batch.expiration_date.strftime('%d.%m.%Y') if batch.expiration_date else '')
                row += 1
        
        workbook.close()
        output.seek(0)
        
        # Возвращаем файл
        from django.http import HttpResponse
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename=warehouse_analytics_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        
        return response
    
    @action(detail=True, methods=['get'])
    def batch_history(self, request, pk=None):
        """История партий конкретного товара"""
        product = self.get_object()
        
        batches = product.batches.all().order_by('-created_at')
        serializer = BatchDetailSerializer(batches, many=True)
        
        return Response({
            'product': product.name,
            'total_batches': batches.count(),
            'active_batches': batches.filter(quantity__gt=0).count(),
            'sold_out_batches': batches.filter(quantity=0).count(),
            'batches': serializer.data
        })
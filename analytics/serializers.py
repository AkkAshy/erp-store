# analytics/serializers.py
from rest_framework import serializers
from .models import SalesSummary, ProductAnalytics, CustomerAnalytics, SupplierAnalytics, CashRegister, CashHistory, CategoryAnalytics
from inventory.serializers import ProductSerializer
from customers.models import Customer
from django.utils.translation import gettext_lazy as _
from inventory.models import (
    Product, ProductBatch, Stock, StockHistory, 
    SizeInfo, ProductCategory, AttributeValue
)
from sales.models import Transaction, TransactionHistory
from stores.mixins import StoreSerializerMixin
from django.db.models import Sum, Avg, F, Q, Count
from decimal import Decimal
from rest_framework.response import Response

class CashRegisterSerializer(StoreSerializerMixin, serializers.ModelSerializer):
    """
    ✅ СЕРИАЛИЗАТОР КАССЫ — баланс и снятие
    """
    # Для withdraw: amount и notes
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)
    
    # Читаемые поля
    store_name = serializers.CharField(source='store.name', read_only=True)
    balance_formatted = serializers.SerializerMethodField()
    
    class Meta:
        model = CashRegister
        fields = [
            'id', 'store', 'store_name', 'date_opened', 'current_balance', 'target_balance',
            'last_updated', 'is_open', 'financial_summary',
            'amount', 'notes', 'balance_formatted'
        ]
        read_only_fields = ['id', 'store', 'date_opened', 'current_balance', 'target_balance',
                            'last_updated', 'is_open', 'financial_summary', 'balance_formatted']

    def get_balance_formatted(self, obj):
        """Форматированный баланс для фронта"""
        return f"{obj.current_balance:,.0f} сум"

    def create(self, validated_data):
        # При создании — открываем новую смену
        store = self.context['request'].user.current_store
        validated_data['store'] = store
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Для POST withdraw: используем метод withdraw
        amount = validated_data.pop('amount', None)
        notes = validated_data.pop('notes', '')
        user = self.context['request'].user
        
        if amount is not None:
            withdrawn = instance.withdraw(amount, user, notes)
            return Response({'withdrawn': withdrawn, 'new_balance': instance.current_balance})
        
        return super().update(instance, validated_data)

class SupplierAnalyticsSerializer(serializers.ModelSerializer):
    supplier_display = serializers.CharField(source='supplier', read_only=True)  # Для удобства

    class Meta:

        model = SupplierAnalytics
        fields = [
            'date', 'supplier', 'supplier_display',
            'total_quantity_sold', 'total_revenue', 'total_cost', 'total_margin',
            'products_count', 'transactions_count', 'unique_products_sold',
            'average_margin_percentage', 'turnover_rate'
        ]


class SalesSummarySerializer(serializers.ModelSerializer):
    payment_method_display = serializers.CharField(
        source='get_payment_method_display', read_only=True
    )

    class Meta:
        model = SalesSummary
        fields = ['date', 'total_amount', 'total_transactions', 'total_items_sold',
                  'payment_method', 'payment_method_display']

class ProductAnalyticsSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)

    class Meta:
        model = ProductAnalytics
        fields = ['product', 'date', 'quantity_sold', 'revenue']

class CustomerAnalyticsSerializer(serializers.ModelSerializer):
    customer = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = CustomerAnalytics
        fields = ['customer', 'date', 'total_purchases', 'transaction_count', 'debt_added']


class TransactionsHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionHistory
        fields = ['customer', 'cashier', 'date', 'total_purchases', 'transaction_count', 'debt_added']


class Transaction(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ['customer', 'cashier', 'date', 'total_purchases', 'transaction_count', 'debt_added']


class CashHistorySerializer(serializers.ModelSerializer):
    operation_display = serializers.CharField(source='get_operation_type_display', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    timestamp_formatted = serializers.DateTimeField(
        source='timestamp', format='%Y-%m-%d %H:%M:%S', read_only=True
    )

    class Meta:
        model = CashHistory
        fields = [
            'id', 'operation_type', 'operation_display', 'amount', 'user', 'user_name',
            'timestamp', 'timestamp_formatted', 'notes', 'balance_before', 'balance_after'
        ]

class CashRegisterCloseSerializer(serializers.Serializer):
    """Для закрытия смены"""
    actual_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="Закрытие смены")


class CategoryAnalyticsSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = CategoryAnalytics
        fields = [
            'id',
            'store',
            'date',
            'category',
            'category_name',  # удобно для фронта
            'total_quantity_sold',
            'total_revenue',
            'products_count',
            'transactions_count',
            'unique_products_sold',
            'average_transaction_amount'
        ]
        read_only_fields = [
            'store',
            'total_quantity_sold',
            'total_revenue',
            'products_count',
            'transactions_count',
            'unique_products_sold',
            'average_transaction_amount',
            'category_name'
        ]



class BatchDetailSerializer(serializers.ModelSerializer):
    """Детальная информация о партии"""
    size_display = serializers.CharField(source='size.size', read_only=True)
    size_details = serializers.SerializerMethodField()
    age_days = serializers.SerializerMethodField()
    total_value_uzs = serializers.DecimalField(
        source='total_cost', 
        max_digits=12, 
        decimal_places=2, 
        read_only=True
    )
    total_value_usd = serializers.SerializerMethodField()
    min_sale_price = serializers.DecimalField(
        source='min_sale_price_per_unit',
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    
    class Meta:
        model = ProductBatch
        fields = [
            'id', 'quantity', 'purchase_price', 'purchase_price_usd',
            'purchase_rate', 'supplier', 'supplier_country', 
            'invoice_number', 'expiration_date', 'created_at',
            'size_display', 'size_details', 'age_days',
            'total_value_uzs', 'total_value_usd', 'min_sale_price'
        ]
    
    def get_size_details(self, obj):
        if not obj.size:
            return None
        return {
            'id': obj.size.id,
            'size': obj.size.size,
            'dimension1': obj.size.dimension1,
            'dimension1_label': obj.size.dimension1_label,
            'dimension2': obj.size.dimension2,
            'dimension2_label': obj.size.dimension2_label,
            'dimension3': obj.size.dimension3,
            'dimension3_label': obj.size.dimension3_label,
            'full_description': obj.size.full_description
        }
    
    def get_age_days(self, obj):
        from django.utils import timezone
        return (timezone.now() - obj.created_at).days
    
    def get_total_value_usd(self, obj):
        if obj.purchase_price_usd and obj.quantity:
            return float(obj.purchase_price_usd * obj.quantity)
        elif obj.purchase_price and obj.purchase_rate and obj.purchase_rate > 0:
            return float((obj.purchase_price / obj.purchase_rate) * obj.quantity)
        return 0


class WarehouseProductSerializer(serializers.ModelSerializer):
    """Полная аналитика товара на складе"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    unit_display = serializers.CharField(read_only=True)
    
    # Остатки и партии
    total_quantity = serializers.SerializerMethodField()
    batches = BatchDetailSerializer(many=True, read_only=True)
    batches_count = serializers.SerializerMethodField()
    
    # Финансовая аналитика
    stock_value = serializers.SerializerMethodField()
    price_analytics = serializers.SerializerMethodField()
    margin_info = serializers.SerializerMethodField()
    
    # Аналитика по размерам
    size_breakdown = serializers.SerializerMethodField()
    
    # Аналитика по поставщикам
    supplier_breakdown = serializers.SerializerMethodField()
    
    # История движения
    movement_summary = serializers.SerializerMethodField()
    
    # Атрибуты
    attributes_info = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'barcode', 'category_name', 'unit_display',
            'sale_price', 'has_sizes', 'total_quantity', 'batches',
            'batches_count', 'stock_value', 'price_analytics',
            'margin_info', 'size_breakdown', 'supplier_breakdown',
            'movement_summary', 'attributes_info', 'created_at'
        ]
    
    def get_total_quantity(self, obj):
        return float(obj.stock.quantity) if hasattr(obj, 'stock') else 0
    
    def get_batches_count(self, obj):
        return obj.batches.filter(quantity__gt=0).count()
    
    def get_stock_value(self, obj):
        """Полная стоимость товара на складе"""
        batches = obj.batches.filter(quantity__gt=0)
        
        total_uzs = Decimal('0')
        total_usd = Decimal('0')
        
        for batch in batches:
            if batch.purchase_price:
                total_uzs += batch.purchase_price * batch.quantity
            if batch.purchase_price_usd:
                total_usd += batch.purchase_price_usd * batch.quantity
            elif batch.purchase_price and batch.purchase_rate and batch.purchase_rate > 0:
                total_usd += (batch.purchase_price / batch.purchase_rate) * batch.quantity
        
        # Получаем текущий курс
        from inventory.models import ExchangeRate
        from django.utils import timezone
        latest_rate = ExchangeRate.objects.order_by('-date').first()
        current_rate = latest_rate.usd_rate if latest_rate else Decimal('12500')
        
        return {
            'total_uzs': float(total_uzs),
            'total_usd': float(total_usd),
            'current_rate': float(current_rate),
            'total_uzs_at_current_rate': float(total_usd * current_rate) if total_usd else 0
        }
    
    def get_price_analytics(self, obj):
        """Детальная аналитика цен"""
        batches = obj.batches.filter(quantity__gt=0, purchase_price__isnull=False)
        
        if not batches.exists():
            return None
        
        prices = [b.purchase_price for b in batches]
        quantities = [b.quantity for b in batches]
        
        # Средневзвешенная цена
        total_cost = sum(p * q for p, q in zip(prices, quantities))
        total_qty = sum(quantities)
        weighted_avg = total_cost / total_qty if total_qty else 0
        
        return {
            'min_purchase': float(min(prices)),
            'max_purchase': float(max(prices)),
            'avg_purchase': float(sum(prices) / len(prices)),
            'weighted_avg_purchase': float(weighted_avg),
            'last_purchase': float(obj.last_purchase_price) if obj.last_purchase_price else None,
            'recommended_sale': float(obj.sale_price),
            'min_allowed_sale': float(obj.min_sale_price)
        }
    
    def get_margin_info(self, obj):
        """Информация о марже"""
        avg_purchase = obj.average_purchase_price
        if not avg_purchase:
            return None
        
        margin_amount = obj.sale_price - avg_purchase
        margin_percent = (margin_amount / avg_purchase * 100) if avg_purchase else 0
        
        # Минимальная наценка магазина
        store_min_markup = obj.store.min_markup_percent if hasattr(obj.store, 'min_markup_percent') else 0
        
        return {
            'current_margin_uzs': float(margin_amount),
            'current_margin_percent': float(margin_percent),
            'store_min_markup_percent': float(store_min_markup),
            'margin_status': 'OK' if margin_percent >= store_min_markup else 'LOW'
        }
    
    def get_size_breakdown(self, obj):
        """Разбивка по размерам"""
        if not obj.has_sizes:
            return None
        
        size_data = obj.batches.filter(
            quantity__gt=0, 
            size__isnull=False
        ).values('size__size').annotate(
            total_qty=Sum('quantity'),
            total_value=Sum(F('quantity') * F('purchase_price')),
            batch_count=Count('id')
        )
        
        return [{
            'size': item['size__size'],
            'quantity': float(item['total_qty']),
            'value_uzs': float(item['total_value']) if item['total_value'] else 0,
            'batches': item['batch_count']
        } for item in size_data]
    
    def get_supplier_breakdown(self, obj):
        """Разбивка по поставщикам"""
        supplier_data = obj.batches.filter(
            quantity__gt=0
        ).values('supplier', 'supplier_country').annotate(
            total_qty=Sum('quantity'),
            total_value=Sum(F('quantity') * F('purchase_price')),
            batch_count=Count('id'),
            avg_price=Avg('purchase_price')
        )
        
        return [{
            'supplier': item['supplier'] or 'Не указан',
            'country': item['supplier_country'] or 'Не указана',
            'quantity': float(item['total_qty']),
            'value_uzs': float(item['total_value']) if item['total_value'] else 0,
            'batches': item['batch_count'],
            'avg_price': float(item['avg_price']) if item['avg_price'] else 0
        } for item in supplier_data]
    
    def get_movement_summary(self, obj):
        """Сводка движения за последние 30 дней"""
        from datetime import timedelta
        from django.utils import timezone
        
        date_from = timezone.now() - timedelta(days=30)
        
        history = StockHistory.objects.filter(
            product=obj,
            timestamp__gte=date_from
        )
        
        incoming = history.filter(operation_type='INCOMING').aggregate(
            total=Sum('quantity_change')
        )['total'] or 0
        
        sales = history.filter(operation_type='SALE').aggregate(
            total=Sum('quantity_change')
        )['total'] or 0
        
        returns = history.filter(operation_type='RETURN').aggregate(
            total=Sum('quantity_change')
        )['total'] or 0
        
        return {
            'period_days': 30,
            'incoming': float(incoming),
            'sales': float(abs(sales)),
            'returns': float(returns),
            'net_change': float(incoming + sales + returns),
            'turnover_rate': float(abs(sales) / (obj.stock.quantity or 1)) if hasattr(obj, 'stock') else 0
        }
    
    def get_attributes_info(self, obj):
        """Информация об атрибутах"""
        return list(obj.attributes.values(
            'attribute_type__name',
            'value',
            'slug'
        ))

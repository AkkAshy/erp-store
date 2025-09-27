from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
import logging
from .models import ProductCategory, Product, Stock, ProductBatch
from sales.models import TransactionItem  # Для inline транзакций
from rangefilter.filters import NumericRangeFilter

logger = logging.getLogger('inventory')

# Inline для Stock в Product
class StockInline(admin.TabularInline):
    model = Stock
    extra = 1
    fields = ['quantity', 'updated_at']
    readonly_fields = ['updated_at']
    can_delete = True

# Inline для ProductBatch в Product
class ProductBatchInline(admin.TabularInline):
    model = ProductBatch
    extra = 1
    fields = ['quantity', 'expiration_date', 'created_at', 'is_expired']
    readonly_fields = ['created_at', 'is_expired']
    list_filter = ['expiration_date']

    def is_expired(self, obj):
        return obj.expiration_date and obj.expiration_date < timezone.now().date()
    is_expired.boolean = True
    is_expired.short_description = 'Истёк'

# Inline для TransactionItem из sales (связь с транзакциями)
class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0
    fields = ['transaction', 'quantity', 'price', 'subtotal', 'unit_display']
    readonly_fields = ['transaction', 'quantity', 'price', 'subtotal', 'unit_display']
    can_delete = False

    def subtotal(self, obj):
        return obj.quantity * obj.price
    subtotal.short_description = 'Подытог'

# Admin для ProductCategory
@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at', 'product_count']
    list_filter = ['created_at']
    search_fields = ['name']
    date_hierarchy = 'created_at'
    list_per_page = 50

    def product_count(self, obj):
        return obj.product_set.count()
    product_count.short_description = 'Продуктов'

    def save_model(self, request, obj, form, change):
        logger.info(f"[SomPOS] Admin {request.user} {'updated' if change else 'created'} category {obj.name}")
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        logger.info(f"[SomPOS] Admin {request.user} deleted category {obj.name}")
        super().delete_model(request, obj)

# Admin для Product
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'barcode', 'category', 'sale_price', 'stock_quantity', 'low_stock_warning']
    list_filter = ['category', 'sale_price', ('stock__quantity', NumericRangeFilter)]
    search_fields = ['name', 'barcode']
    date_hierarchy = 'created_at'
    inlines = [StockInline, ProductBatchInline, TransactionItemInline]
    readonly_fields = ['created_at']
    actions = ['archive_zero_stock']
    list_per_page = 50
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'barcode', 'category', 'sale_price', 'created_at')
        }),
        ('Дополнительно', {
            'fields': ('unit_type', 'min_quantity'),
            'classes': ('collapse',)
        }),
    )

    def stock_quantity(self, obj):
        stock = obj.stock if hasattr(obj, 'stock') else None
        return stock.quantity if stock else 0
    stock_quantity.short_description = 'Запас'

    def low_stock_warning(self, obj):
        stock = obj.stock if hasattr(obj, 'stock') else None
        quantity = stock.quantity if stock else 0
        return format_html('<span style="color: {}">{}</span>', 'red' if quantity < 10 else 'green', 'Низкий' if quantity < 10 else 'Ок')
    low_stock_warning.short_description = 'Статус запаса'

    def archive_zero_stock(self, request, queryset):
        updated = queryset.filter(stock__quantity=0).update(is_active=False)
        self.message_user(request, f'Архивировано {updated} продуктов с нулевым запасом.')
    archive_zero_stock.short_description = 'Архивировать продукты с нулевым запасом'

    def save_model(self, request, obj, form, change):
        logger.info(f"[SomPOS] Admin {request.user} {'updated' if change else 'created'} product {obj.name}, store={getattr(request.user, 'current_store', None)}")
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        logger.info(f"[SomPOS] Admin {request.user} deleted product {obj.name}, store={getattr(request.user, 'current_store', None)}")
        super().delete_model(request, obj)

# Admin для Stock
@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['product', 'quantity', 'updated_at', 'store']
    list_filter = [('quantity', NumericRangeFilter), 'updated_at', 'store']
    search_fields = ['product__name', 'product__barcode']
    readonly_fields = ['updated_at']
    list_per_page = 50
    raw_id_fields = ['product']

    def save_model(self, request, obj, form, change):
        logger.info(f"[SomPOS] Admin {request.user} {'updated' if change else 'created'} stock for {obj.product.name}, quantity={obj.quantity}")
        super().save_model(request, obj, form, change)

# Admin для ProductBatch
@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    list_display = ['product', 'quantity', 'expiration_date', 'is_expired', 'created_at']
    list_filter = ['expiration_date', ('quantity', NumericRangeFilter)]
    search_fields = ['product__name', 'product__barcode']
    readonly_fields = ['created_at']
    actions = ['delete_expired_batches']
    list_per_page = 50
    raw_id_fields = ['product']

    def is_expired(self, obj):
        return obj.expiration_date and obj.expiration_date < timezone.now().date()
    is_expired.boolean = True
    is_expired.short_description = 'Истёк'

    def delete_expired_batches(self, request, queryset):
        expired = queryset.filter(expiration_date__lt=timezone.now().date())
        count = expired.count()
        expired.delete()
        self.message_user(request, f'Удалено {count} истёкших партий.')
    delete_expired_batches.short_description = 'Удалить истёкшие партии'

    def save_model(self, request, obj, form, change):
        logger.info(f"[SomPOS] Admin {request.user} {'updated' if change else 'created'} batch for {obj.product.name}, quantity={obj.quantity}")
        super().save_model(request, obj, form, change)
from django.contrib import admin
from .models import (
    Transaction, TransactionItem, TransactionHistory, 
    TransactionRefund, TransactionRefundItem
)


class TransactionItemInline(admin.TabularInline):
    """
    Inline для элементов транзакции: компактный вид в форме Transaction.
    """
    model = TransactionItem
    extra = 0  # Не добавляем пустые строки по умолчанию
    fields = ['product', 'quantity', 'price', 'unit_display', 'subtotal']
    readonly_fields = ['subtotal']  # Подытог – рассчитывается автоматически
    autocomplete_fields = ['product']  # Поиск по товарам (если включишь grappelli или подобное)

    def subtotal(self, obj):
        return f"{obj.quantity * obj.price} руб." if obj else '-'
    subtotal.short_description = 'Подытог'
    
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """
    Админка для транзакций: основной список продаж с inline'ами для товаров.
    """
    list_display = [
        'id', 'cashier_display', 'customer_display', 'total_amount', 
        'payment_method', 'status', 'created_at', 'store'
    ]
    list_filter = ['status', 'payment_method', 'created_at', 'store']
    search_fields = ['id', 'cashier__username', 'customer__full_name', 'customer__phone']
    raw_id_fields = ['cashier', 'customer', 'store']  # Для больших списков – popup вместо dropdown
    inlines = [TransactionItemInline]
    readonly_fields = ['created_at', 'total_amount']  # Не даем менять сумму/дату
    ordering = ['-created_at']  # Новые сверху
    actions = ['mark_as_completed', 'export_to_csv']  # Примеры actions

    def cashier_display(self, obj):
        return obj.cashier.username if obj.cashier else 'Не назначен'
    cashier_display.short_description = 'Кассир'

    def customer_display(self, obj):
        return obj.customer.full_name if obj.customer else 'Аноним'
    customer_display.short_description = 'Клиент'

    def mark_as_completed(self, request, queryset):
        updated = queryset.update(status='completed')
        self.message_user(request, f'Обновлено {updated} транзакций на "завершено".')
    mark_as_completed.short_description = 'Отметить как завершенные'

    def export_to_csv(self, request, queryset):
        # Здесь можно добавить логику экспорта (используй django-import-export или custom)
        self.message_user(request, 'Экспорт CSV готов (реализуй метод).')
    export_to_csv.short_description = 'Экспорт в CSV'



@admin.register(TransactionItem)
class TransactionItemAdmin(admin.ModelAdmin):
    """
    Отдельная админка для элементов: если нужно редактировать по отдельности.
    """
    list_display = ['transaction', 'product', 'quantity', 'price', 'subtotal', 'unit_display', 'unit_type']
    list_filter = ['transaction__status', 'unit_type', 'transaction__store']
    search_fields = ['product__name', 'transaction__id']
    readonly_fields = ['subtotal', 'size_snapshot']  # Снимок – не трогаем
    ordering = ['-transaction__created_at']

    def subtotal(self, obj):
        return obj.quantity * obj.price
    subtotal.short_description = 'Подытог'

@admin.register(TransactionHistory)
class TransactionHistoryAdmin(admin.ModelAdmin):
    """
    История транзакций: только просмотр, для аудита.
    """
    list_display = ['transaction', 'action', 'created_at', 'store']
    list_filter = ['action', 'created_at', 'store']
    search_fields = ['transaction__id', 'details']  # Поиск по JSON details
    readonly_fields = ['details']  # Не даем менять историю
    ordering = ['-created_at']
    fieldsets = (
        ('Основное', {
            'fields': ('transaction', 'action', 'details')
        }),
        ('Метаданные', {
            'fields': ('created_at', 'store'),
            'classes': ('collapse',)  # Сворачиваем
        }),
    )



class TransactionRefundItemInline(admin.TabularInline):
    """
    Inline для элементов возврата.
    """
    model = TransactionRefundItem
    extra = 0
    fields = ['original_item', 'refunded_quantity', 'refunded_amount', 'can_refund_quantity']
    readonly_fields = ['can_refund_quantity']  # Показываем остаток для возврата

    def can_refund_quantity(self, obj):
        return obj.can_refund_quantity
    can_refund_quantity.short_description = 'Можно вернуть еще'

@admin.register(TransactionRefundItem)
class TransactionRefundItemAdmin(admin.ModelAdmin):
    """
    Отдельная для элементов возвратов.
    """
    list_display = ['refund', 'original_item', 'refunded_quantity', 'refunded_amount', 'can_refund_quantity']
    list_filter = ['refund__refund_type']
    search_fields = ['original_item__product__name', 'refund__id']
    readonly_fields = ['can_refund_quantity']


@admin.register(TransactionRefund)
class TransactionRefundAdmin(admin.ModelAdmin):
    """
    Админка для возвратов: с inline'ами для элементов.
    """
    list_display = [
        'id', 'original_transaction', 'refunded_amount', 
        'refund_type', 'reason', 'processed_by', 'created_at', 'store'
    ]
    list_filter = ['refund_type', 'created_at', 'store']
    search_fields = ['original_transaction__id', 'reason', 'processed_by__username']
    raw_id_fields = ['original_transaction', 'processed_by', 'store']
    inlines = [TransactionRefundItemInline]
    readonly_fields = ['created_at', 'refunded_amount']  # Сумма – рассчитывается
    ordering = ['-created_at']
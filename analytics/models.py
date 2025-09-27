# analytics/models.py - ОБНОВЛЕННАЯ ВЕРСИЯ
from django.db import models
from django.utils.translation import gettext_lazy as _
from inventory.models import Product, ProductCategory
from sales.models import Transaction
from customers.models import Customer
import logging
from django.contrib.auth.models import User
from stores.mixins import StoreOwnedModel, StoreOwnedManager
from django.db import transaction  # Для атомарных операций
from django.utils import timezone
from decimal import Decimal
from inventory.models import FinancialSummary


logger = logging.getLogger('analytics')

class SalesSummaryManager(StoreOwnedManager):
    def update_from_transaction(self, transaction):
        summary, created = self.get_or_create(
            store=transaction.store,
            date=transaction.created_at.date(),
            payment_method=transaction.payment_method,
            defaults={
                "cashier": transaction.cashier,
                "total_amount": transaction.total_amount,
                "total_transactions": 1,
                "total_items_sold": transaction.items_count,
            }
        )
        if not created:
            summary.total_amount += transaction.total_amount
            summary.total_transactions += 1
            summary.total_items_sold += transaction.items_count
            summary.save()
        return summary


class SalesSummary(StoreOwnedModel):
    date = models.DateField(verbose_name=_("Дата"))
    cashier = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Кассир",
        related_name="sales_summaries"
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_transactions = models.PositiveIntegerField(default=0)
    total_items_sold = models.PositiveIntegerField(default=0)
    payment_method = models.CharField(
        max_length=20, choices=Transaction.PAYMENT_METHODS
    )

    objects = SalesSummaryManager()

    class Meta:
        verbose_name = _("Сводка по продажам")
        verbose_name_plural = _("Сводки по продажам")
        unique_together = ('store', 'date', 'payment_method')
        ordering = ['-date']

    def __str__(self):
        return f"{self.date} - {self.get_payment_method_display()} ({self.total_amount})"


class ProductAnalytics(models.Model):
    """
    ОБНОВЛЕННАЯ статистика по товарам с учетом новой структуры товаров
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='analytics',
        verbose_name=_("Товар")
    )
    cashier = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="product_analytics"
    )
    date = models.DateField(verbose_name=_("Дата"))
    quantity_sold = models.DecimalField(
        max_digits=15,  # Увеличено для поддержки дробных единиц
        decimal_places=3,  # Поддержка до тысячных
        default=0,
        verbose_name=_("Продано единиц")
    )
    revenue = models.DecimalField(
        max_digits=12, decimal_places=2, default=0.00,
        verbose_name=_("Выручка")
    )
    
    # Новые поля для анализа единиц измерения
    unit_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Тип единицы измерения"
    )
    unit_display = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="Отображение единицы"
    )
    
    # Информация о размере (если применимо)
    size_info = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Информация о размере",
        help_text="JSON с данными о размере товара на момент продажи"
    )
    
    # Средняя цена за единицу
    average_unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Средняя цена за единицу"
    )

    class Meta:
        verbose_name = _("Аналитика товара")
        verbose_name_plural = _("Аналитика товаров")
        unique_together = ('product', 'date')
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date', 'product']),
            models.Index(fields=['unit_type', 'date']),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.date} ({self.quantity_sold} {self.unit_display})"

    def save(self, *args, **kwargs):
        """Автоматически заполняем информацию о единицах при сохранении"""
        if self.product:
            self.unit_type = self.product.unit_type or 'custom'
            self.unit_display = self.product.unit_display
            
            # Сохраняем информацию о размере
            if self.product.has_sizes and self.product.default_size:
                self.size_info = {
                    'size': self.product.default_size.size,
                    'dimension1': float(self.product.default_size.dimension1) if self.product.default_size.dimension1 else None,
                    'dimension2': float(self.product.default_size.dimension2) if self.product.default_size.dimension2 else None,
                    'dimension3': float(self.product.default_size.dimension3) if self.product.default_size.dimension3 else None,
                    'dimension1_label': self.product.default_size.dimension1_label,
                    'dimension2_label': self.product.default_size.dimension2_label,
                    'dimension3_label': self.product.default_size.dimension3_label,
                }
            
            # Рассчитываем среднюю цену за единицу
            if self.quantity_sold and self.quantity_sold > 0:
                self.average_unit_price = self.revenue / self.quantity_sold
        
        super().save(*args, **kwargs)


class CustomerAnalytics(models.Model):
    """
    Статистика по клиентам
    """
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='analytics',
        verbose_name=_("Клиент")
    )
    cashier = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="customer_analytics"
    )
    date = models.DateField(verbose_name=_("Дата"))
    total_purchases = models.DecimalField(
        max_digits=12, decimal_places=2, default=0.00,
        verbose_name=_("Сумма покупок")
    )
    transaction_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Количество транзакций")
    )
    debt_added = models.DecimalField(
        max_digits=12, decimal_places=2, default=0.00,
        verbose_name=_("Добавлено долга")
    )

    class Meta:
        verbose_name = _("Аналитика клиента")
        verbose_name_plural = _("Аналитика клиентов")
        unique_together = ('customer', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.customer.full_name} - {self.date} ({self.total_purchases})"


def default_product_ids():
    """Возвращает пустой список для поля product_ids"""
    return []
from django.contrib.postgres.fields import ArrayField
class UnitAnalytics(StoreOwnedModel):
    """
    НОВАЯ модель: Аналитика по единицам измерения
    """
    date = models.DateField(verbose_name=_("Дата"))
    unit_type = models.CharField(
        max_length=50,
        verbose_name="Тип единицы измерения"
    )
    unit_display = models.CharField(
        max_length=20,
        verbose_name="Отображение единицы"
    )
    is_custom = models.BooleanField(
        default=False,
        verbose_name="Пользовательская единица"
    )
    
    # Статистика продаж
    total_quantity_sold = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        default=0,
        verbose_name="Общее количество проданного"
    )
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Общая выручка"
    )
    product_ids = models.JSONField(
        default=default_product_ids,  # Функция вместо list
        verbose_name="ID товаров"
    )


    products_count = models.PositiveIntegerField(default=0, verbose_name="Количество уникальных товаров")

    transactions_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество транзакций"
    )
    
    # Средние показатели
    average_unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Средняя цена за единицу"
    )

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = _("Аналитика единиц измерения")
        verbose_name_plural = _("Аналитика единиц измерения")
        unique_together = ('store', 'date', 'unit_type', 'unit_display')
        ordering = ['-date', 'unit_display']

    def __str__(self):
        return f"{self.unit_display} - {self.date} ({self.total_quantity_sold})"

    def calculate_metrics(self):
        """Рассчитывает производные метрики"""
        if self.total_quantity_sold and self.total_quantity_sold > 0:
            self.average_unit_price = self.total_revenue / self.total_quantity_sold


class CashRegister(StoreOwnedModel):
    """
    ✅ МОДЕЛЬ КАССЫ — сколько денег в ящике прямо сейчас
    Баланс обновляется при продажах (cash payments) и снятиях.
    Связь с FinancialSummary для дневных итогов.
    """
    date_opened = models.DateTimeField(default=timezone.now, verbose_name="Открытие смены")
    current_balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        verbose_name="Текущий баланс"
    )
    target_balance = models.DecimalField(  # Целевой баланс на конец смены
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        verbose_name="Целевой баланс"
    )
    last_updated = models.DateTimeField(auto_now=True, verbose_name="Последнее обновление")
    is_open = models.BooleanField(default=True, verbose_name="Смена открыта")
    
    # Связь с дневным summary (опционально, для агрегации)
    financial_summary = models.ForeignKey(
        FinancialSummary, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cash_registers', verbose_name="Дневная сводка"
    )

    closed_balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        verbose_name="Баланс при закрытии",
        help_text="Фактический баланс при закрытии смены"
    )
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="Время закрытия")
    discrepancy = models.DecimalField(  # Расхождение: actual - target
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        verbose_name="Расхождение"
    )
    
    # Связь с историей операций кассы (создадим ниже)
    cash_history = models.ManyToManyField(
        'CashHistory', related_name='cash_registers', blank=True
    )

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = "Касса"
        verbose_name_plural = "Кассы"
        unique_together = ('store', 'date_opened')  # Одна касса на смену в магазине
        ordering = ['-date_opened']

    def __str__(self):
        return f"Касса {self.store.name} ({self.date_opened.date()}) — {self.current_balance:,} сум"

    def add_cash(self, amount, user=None, notes=""):
        """✅ ИСПРАВЛЕННОЕ добавление денег"""
        from decimal import Decimal
        from django.db import transaction as db_transaction
        
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError("Сумма должна быть положительной")
        
        with db_transaction.atomic():
            # Сохраняем старый баланс
            balance_before = self.current_balance
            
            # ОБНОВЛЯЕМ БАЛАНС
            self.current_balance = self.current_balance + amount
            self.save(update_fields=['current_balance', 'last_updated'])
            
            # Перечитываем из БД для уверенности
            self.refresh_from_db()
            
            # Создаем запись в истории
            from analytics.models import CashHistory
            CashHistory.objects.create(
                cash_register=self,
                operation_type='ADD_CASH',
                amount=amount,
                user=user,
                store=self.store,
                notes=notes or f"Добавление в кассу",
                balance_before=balance_before,
                balance_after=self.current_balance
            )
            
            logger.info(f"✅ Добавлено {amount} в кассу {self.id}. Баланс: {balance_before} → {self.current_balance}")
            
            # Обновляем финансовую сводку если связана
            if self.financial_summary:
                self.financial_summary.cash_total = self.financial_summary.cash_total + amount
                self.financial_summary.save()
        
        return self.current_balance

    def withdraw(self, amount, user, notes="Выдача наличных"):
        """✅ ИСПРАВЛЕННОЕ снятие денег"""
        from decimal import Decimal
        from django.db import transaction as db_transaction
        
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError("Сумма должна быть положительной")
        if amount > self.current_balance:
            raise ValueError(f"Недостаточно средств. Доступно: {self.current_balance}")
        if not self.is_open:
            raise ValueError("Смена закрыта — нельзя снимать")

        with db_transaction.atomic():
            # Сохраняем старый баланс
            balance_before = self.current_balance
            
            # ОБНОВЛЯЕМ БАЛАНС
            self.current_balance = self.current_balance - amount
            self.save(update_fields=['current_balance', 'last_updated'])
            
            # Перечитываем из БД
            self.refresh_from_db()
            
            # Создаем запись в истории
            from analytics.models import CashHistory
            CashHistory.objects.create(
                cash_register=self,
                operation_type='WITHDRAW',
                amount=amount,
                user=user,
                store=self.store,
                notes=notes,
                balance_before=balance_before,
                balance_after=self.current_balance
            )
            
            logger.info(f"✅ Снято {amount} из кассы {self.id}. Баланс: {balance_before} → {self.current_balance}")
            
            # Обновляем финансовую сводку
            if self.financial_summary:
                self.financial_summary.cash_total = self.financial_summary.cash_total - amount
                self.financial_summary.save()
        
        return amount

    def close_shift(self, actual_balance, user, notes=""):
        from django.utils.timezone import now
        from decimal import Decimal
        from inventory.models import FinancialSummary

        today = now().date()

        if not self.is_open:
            raise ValueError("Смена уже закрыта")

        # считаем расхождение
        discrepancy = Decimal(actual_balance) - self.target_balance

        # создаём или обновляем дневную сводку
        summary, created = FinancialSummary.objects.get_or_create(
            date=today,
            store=self.store,
            defaults={
                "cash_opened": self.current_balance,
                "cash_closed": actual_balance, 
                "discrepancy": discrepancy,
                "closed_by": user,
                "grand_total": actual_balance,
                "notes": notes,
            }
        )

        if not created:
            summary.cash_closed = actual_balance
            summary.discrepancy = discrepancy
            summary.closed_by = user
            summary.notes = notes
            summary.save()

        # обновляем кассу
        self.closed_balance = actual_balance
        self.closed_at = now()
        self.discrepancy = discrepancy
        self.is_open = False
        self.financial_summary = summary
        self.save()

        return {
            "status": "closed",
            "discrepancy": discrepancy,
            "message": f"Смена закрыта. Итог: {actual_balance:,.2f} сум",
            "summary_id": summary.id,   # ← вот этот ключ обязателен
        }

class CashHistory(StoreOwnedModel):
    """
    ✅ ИСТОРИЯ ОПЕРАЦИЙ КАССЫ — аудит наличных
    """
    CASH_OPERATIONS = [
        ('OPEN_SHIFT', 'Открытие смены'),
        ('ADD_CASH', 'Добавление наличных'),
        ('WITHDRAW', 'Снятие наличных'),
        ('CLOSE_SHIFT', 'Закрытие смены'),
        ('CORRECTION', 'Корректировка'),
    ]
    
    cash_register = models.ForeignKey(
        CashRegister, on_delete=models.CASCADE, related_name='history'
    )
    operation_type = models.CharField(max_length=20, choices=CASH_OPERATIONS)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    user = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cash_operations'
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    notes = models.TextField(blank=True)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, null=True)

    class Meta:
        verbose_name = "Операция кассы"
        verbose_name_plural = "История кассы"
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['cash_register', 'timestamp'])]

    def __str__(self):
        return f"{self.get_operation_type_display()} | {self.amount:,.0f} | {self.timestamp.strftime('%H:%M')}"

    def save(self, *args, **kwargs):
        """Автоматически фиксируем баланс до/после"""
        if self.pk is None:  # Новый объект
            self.balance_before = self.cash_register.current_balance
        super().save(*args, **kwargs)
        self.balance_after = self.cash_register.current_balance
        super().save(update_fields=['balance_after'])

class SizeAnalytics(StoreOwnedModel):
    """
    НОВАЯ модель: Аналитика по размерам товаров
    """
    date = models.DateField(verbose_name=_("Дата"))
    size_name = models.CharField(
        max_length=50,
        verbose_name="Название размера"
    )
    
    # Параметры размера на момент анализа
    dimension1 = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Параметр 1"
    )
    dimension2 = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Параметр 2"  
    )
    dimension3 = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Параметр 3"
    )
    
    # Метки параметров
    dimension1_label = models.CharField(max_length=50, null=True, blank=True)
    dimension2_label = models.CharField(max_length=50, null=True, blank=True)
    dimension3_label = models.CharField(max_length=50, null=True, blank=True)
    
    # Статистика продаж
    total_quantity_sold = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        default=0,
        verbose_name="Общее количество проданного"
    )
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Общая выручка"
    )
    products_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество товаров этого размера"
    )
    transactions_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество транзакций"
    )

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = _("Аналитика размеров")
        verbose_name_plural = _("Аналитика размеров")
        unique_together = ('store', 'date', 'size_name')
        ordering = ['-date', 'size_name']

    def __str__(self):
        return f"{self.size_name} - {self.date} ({self.total_quantity_sold})"

    @property
    def full_description(self):
        """Полное описание размера с параметрами"""
        parts = [self.size_name]
        
        if self.dimension1 and self.dimension1_label:
            parts.append(f"{self.dimension1_label}: {self.dimension1}")
        if self.dimension2 and self.dimension2_label:
            parts.append(f"{self.dimension2_label}: {self.dimension2}")
        if self.dimension3 and self.dimension3_label:
            parts.append(f"{self.dimension3_label}: {self.dimension3}")
            
        return " | ".join(parts)


class CategoryAnalytics(StoreOwnedModel):
    """
    НОВАЯ модель: Аналитика по категориям товаров
    """
    date = models.DateField(verbose_name=_("Дата"))
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        related_name='analytics',
        verbose_name=_("Категория")
    )
    
    # Статистика продаж
    total_quantity_sold = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        default=0,
        verbose_name="Общее количество проданного"
    )
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Общая выручка"
    )
    products_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество товаров в категории"
    )
    transactions_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество транзакций"
    )
    unique_products_sold = models.PositiveIntegerField(
        default=0,
        verbose_name="Уникальных товаров продано"
    )
    
    # Средние показатели
    average_transaction_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Средняя сумма транзакции"
    )

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = _("Аналитика категорий")
        verbose_name_plural = _("Аналитика категорий")
        unique_together = ('store', 'date', 'category')
        ordering = ['-date', 'category__name']

    def __str__(self):
        return f"{self.category.name} - {self.date} ({self.total_revenue})"

    def calculate_metrics(self):
        """Рассчитывает производные метрики"""
        if self.transactions_count > 0:
            self.average_transaction_amount = self.total_revenue / self.transactions_count



class SupplierAnalytics(StoreOwnedModel):
    """
    Аналитика по поставщикам — кто приносит прибыль, а кто убытки
    """
    date = models.DateField(verbose_name=_("Дата"))
    supplier = models.CharField(
        max_length=255,  # Как в ProductBatch
        verbose_name=_("Поставщик"),
        db_index=True  # Для быстрых поисков
    )
    
    # Статистика продаж (из StockHistory/Transactions)
    total_quantity_sold = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        default=0,
        verbose_name="Общее количество проданного"
    )
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Общая выручка"
    )
    total_cost = models.DecimalField(  # Себестоимость проданного
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Общая себестоимость"
    )
    total_margin = models.DecimalField(  # Маржа = revenue - cost
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Общая маржа"
    )
    products_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество товаров от поставщика"
    )
    transactions_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество транзакций"
    )
    unique_products_sold = models.PositiveIntegerField(
        default=0,
        verbose_name="Уникальных товаров продано"
    )
    
    # Средние показатели
    average_margin_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Средняя маржа (%)"
    )
    turnover_rate = models.DecimalField(  # Оборачиваемость: sold / average_stock
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Коэффициент оборачиваемости"
    )

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = _("Аналитика поставщиков")
        verbose_name_plural = _("Аналитика поставщиков")
        unique_together = ('store', 'date', 'supplier')
        ordering = ['-date', 'supplier']
        indexes = [
            models.Index(fields=['supplier', 'date']),
        ]

    def __str__(self):
        return f"{self.supplier} - {self.date} (Выручка: {self.total_revenue}, Маржа: {self.total_margin})"

    def calculate_metrics(self):
        """Рассчитывает производные метрики перед сохранением"""
        if self.total_revenue > 0:
            self.average_margin_percentage = (self.total_margin / self.total_revenue * 100)
        if self.products_count > 0:  # Примерный turnover; адаптируй под реальный average_stock из Stock
            average_stock = self.products_count  # Замени на реальный расчёт, если есть данные
            self.turnover_rate = self.total_quantity_sold / average_stock if average_stock else 0
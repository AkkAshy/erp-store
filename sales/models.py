# sales/models.py - ОБНОВЛЕННАЯ ВЕРСИЯ
from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
import logging
from stores.mixins import StoreOwnedModel, StoreOwnedManager
from decimal import Decimal
from django.utils import timezone
from rest_framework.serializers import ValidationError




logger = logging.getLogger('sales')

class Transaction(StoreOwnedModel):
    PAYMENT_METHODS = [
        ('cash', 'Наличные'),
        ('transfer', 'Перевод'),
        ('card', 'Карта'),
        ('debt', 'В долг'),
        ('hybrid', 'Гибридная оплата'),  # ← НОВЫЙ МЕТОД
    ]

    cashier = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sales_transactions'
    )
    cash_register = models.ForeignKey(
        'analytics.CashRegister',  # ← Строка вместо импорта!
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        verbose_name="Касса (смена)",
        help_text="Касса, через которую прошла продажа (если наличные)"
    )
    
    cash_register_time = models.DateTimeField(null=True, blank=True, verbose_name="Время операции на кассе")

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchases'
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS,
        default='cash'
    )
    
    # ← НОВЫЕ ПОЛЯ для гибридной оплаты
    cash_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Сумма наличными (для гибридной оплаты)"
    )
    transfer_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Сумма переводом (для гибридной оплаты)"
    )
    card_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Сумма картой (для гибридной оплаты)"
    )
    
    status = models.CharField(
    max_length=20,
    choices=[
        ('completed', 'Completed'),
        ('pending', 'Pending'),
        ('refunded', 'Refunded'),
        ('failed', 'Failed'),  # ← новый
    ],
    default='pending'
)
    created_at = models.DateTimeField(auto_now_add=True)
    

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = "Продажа"
        verbose_name_plural = "Продажи"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['store', 'created_at']),
        ]

    def __str__(self):
        return f"Транзакция #{self.id} | {self.total_amount} сум | Касса: {self.cash_register.id if self.cash_register else 'N/A'}"

    @property
    def items_count(self):
        """Общее количество товаров в транзакции (с учетом дробных единиц)"""
        return self.items.aggregate(
            total=models.Sum('quantity')
        )['total'] or Decimal('0')

    @property
    def payment_details(self):
        """Возвращает детали оплаты"""
        if self.payment_method != 'hybrid':
            return {
                'method': self.get_payment_method_display(),
                'amount': self.total_amount,
                'is_hybrid': False
            }
        
        details = {
            'is_hybrid': True,
            'total': self.total_amount,
            'methods': []
        }
        
        if self.cash_amount > 0:
            details['methods'].append({
                'method': 'cash',
                'method_display': 'Наличные',
                'amount': self.cash_amount
            })
            
        if self.transfer_amount > 0:
            details['methods'].append({
                'method': 'transfer',
                'method_display': 'Перевод',
                'amount': self.transfer_amount
            })
            
        if self.card_amount > 0:
            details['methods'].append({
                'method': 'card',
                'method_display': 'Карта',
                'amount': self.card_amount
            })
            
        return details

    def clean(self):
        super().clean()
        
        if self.payment_method == 'hybrid':
            hybrid_total = self.cash_amount + self.transfer_amount + self.card_amount
            if abs(hybrid_total - self.total_amount) > Decimal('0.01'):
                raise ValidationError(
                    f"Сумма гибридной оплаты ({hybrid_total}) не равна общей сумме ({self.total_amount})"
                )
            if hybrid_total == 0:
                raise ValidationError("Для гибридной оплаты должен быть указан хотя бы один способ")

        elif self.payment_method == 'cash':
            self.cash_amount = self.total_amount
            self.transfer_amount = Decimal('0')
            self.card_amount = Decimal('0')

        elif self.payment_method == 'card':
            self.cash_amount = Decimal('0')
            self.transfer_amount = Decimal('0')
            self.card_amount = self.total_amount

        elif self.payment_method == 'transfer':
            self.cash_amount = Decimal('0')
            self.transfer_amount = self.total_amount
            self.card_amount = Decimal('0')

        elif self.payment_method == 'debt':
            self.cash_amount = Decimal('0')
            self.transfer_amount = Decimal('0')
            self.card_amount = Decimal('0')


    def save(self, *args, **kwargs):
        self.full_clean()  # Вызываем валидацию
        super().save(*args, **kwargs)

    def process_sale(self):
        """
        ОБНОВЛЕННАЯ обработка продажи с поддержкой гибридной оплаты
        """
        if self.status != 'pending':
            raise ValueError("Продажа уже обработана или отменена")

        # Списываем товары со склада
        for item in self.items.all():
            stock = item.product.stock
            
            # Проверяем минимальное количество для продажи
            min_quantity = item.product.min_sale_quantity
            if item.quantity < min_quantity:
                raise ValueError(
                    f"Количество {item.quantity} {item.product.unit_display} "
                    f"меньше минимального для продажи: {min_quantity} {item.product.unit_display}"
                )
            
            # Проверяем шаг изменения количества
            quantity_step = item.product.quantity_step
            if not item.product.allow_decimal and item.quantity % 1 != 0:
                raise ValueError(
                    f"Товар {item.product.name} не поддерживает дробные количества"
                )
            
            # Проверяем соответствие шагу
            if quantity_step and quantity_step > 0:
                remainder = (item.quantity % quantity_step)
                if remainder > Decimal('0.001'):  # Допуск на погрешность
                    raise ValueError(
                        f"Количество {item.quantity} не соответствует шагу {quantity_step} "
                        f"для товара {item.product.name}"
                    )
            
            # Списываем со склада
            stock.sell(float(item.quantity))

        # Обрабатываем долг только если есть долг в оплате
        if self.payment_method == 'debt':
            if not self.customer:
                raise ValueError("Для продажи в долг нужен покупатель")
            self.customer.add_debt(self.total_amount)

        # Обновляем total_spent и loyalty_points
        if self.customer:
            self.customer.total_spent += self.total_amount
            self.customer.loyalty_points += int(self.total_amount // 10)  # 1 балл за 10 рублей
            self.customer.save(update_fields=['total_spent', 'loyalty_points'])

        self.status = 'completed'
        self.save(update_fields=['status'])
        
        payment_info = "гибридная" if self.payment_method == 'hybrid' else self.get_payment_method_display()
        logger.info(f"Продажа #{self.id} завершена: {self.total_amount} ({payment_info})")

    def get_total_items_with_units(self):
        """
        Возвращает детальную информацию о товарах с единицами измерения
        """
        items_info = []
        
        for item in self.items.all():
            items_info.append({
                'product_name': item.product.name,
                'quantity': float(item.quantity),
                'unit_display': item.product.unit_display,
                'unit_type': item.product.unit_type,
                'is_custom_unit': item.product.custom_unit is not None,
                'price': float(item.price),
                'subtotal': float(item.quantity * item.price),
                'size_info': self._get_item_size_info(item)
            })
        
        return items_info

    def _get_item_size_info(self, item):
        """Получает информацию о размере товара"""
        if item.product.has_sizes and item.product.default_size:
            size = item.product.default_size
            return {
                'size': size.size,
                'dimension1': float(size.dimension1) if size.dimension1 else None,
                'dimension2': float(size.dimension2) if size.dimension2 else None,
                'dimension3': float(size.dimension3) if size.dimension3 else None,
                'dimension1_label': size.dimension1_label,
                'dimension2_label': size.dimension2_label,
                'dimension3_label': size.dimension3_label,
                'full_description': size.full_description
            }
        return None
    
    def update_cash_register(self):
        from analytics.models import CashRegister, CashHistory
        """
        ✅ РУЧНОЕ обновление кассы (если сигнал не сработал)
        """
        if self.status != 'completed' or self.cash_amount <= 0:
            logger.warning(f"Транзакция {self.id} не подходит для обновления кассы")
            return False
        
        from django.utils import timezone
        
        today = timezone.now().date()
        cash_register = CashRegister.objects.filter(
            store=self.store,
            date_opened__date=today,
            is_open=True
        ).first()
        
        # Создаём кассу если нет
        if not cash_register:
            cash_register = CashRegister.objects.create(
                store=self.store,
                current_balance=Decimal('0.00'),
                target_balance=Decimal('0.00'),
                is_open=True,
                date_opened=timezone.now()
            )
            logger.info(f"Создана новая касса для транзакции {self.id}")
        
        try:
            # Проверяем, не было ли уже обновления
            existing_history = CashHistory.objects.filter(
                cash_register=cash_register,
                operation_type='ADD_CASH',
                notes__contains=f"#{self.id}"
            ).exists()
            
            if existing_history:
                logger.warning(f"Транзакция {self.id} уже обновила кассу")
                return False
            
            # Добавляем в кассу
            cash_register.add_cash(
                amount=self.cash_amount,
                user=self.cashier,
                notes=f"Ручное добавление по транзакции #{self.id}"
            )
            
            # Создаём запись в истории
            CashHistory.objects.create(
                cash_register=cash_register,
                operation_type='ADD_CASH',
                amount=self.cash_amount,
                user=self.cashier,
                store=self.store,
                notes=f"Ручное добавление #{self.id}",
                balance_before=cash_register.current_balance - self.cash_amount,
                balance_after=cash_register.current_balance
            )
            
            logger.info(f"✅ Касса обновлена вручную: +{self.cash_amount}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка ручного обновления кассы: {e}")
            return False

    def reverse_cash_register(self):
        from analytics.models import CashRegister, CashHistory
        """
        ✅ ОТМЕНА операции в кассе (при возврате)
        """
        if self.cash_amount <= 0:
            logger.warning(f"Транзакция {self.id} без наличных для отмены")
            return False
        
        from django.utils import timezone
        
        today = timezone.now().date()
        cash_register = CashRegister.objects.filter(
            store=self.store,
            date_opened__date=today,
            is_open=True
        ).first()
        
        if not cash_register:
            logger.error(f"Нет открытой кассы для отмены транзакции {self.id}")
            return False
        
        try:
            # Снимаем из кассы
            cash_register.withdraw(
                amount=self.cash_amount,
                user=self.cashier,
                notes=f"Отмена транзакции #{self.id}"
            )
            
            # Запись в историю
            CashHistory.objects.create(
                cash_register=cash_register,
                operation_type='WITHDRAW',
                amount=self.cash_amount,
                user=self.cashier,
                store=self.store,
                notes=f"Отмена транзакции #{self.id}",
                balance_before=cash_register.current_balance + self.cash_amount,
                balance_after=cash_register.current_balance
            )
            
            logger.info(f"✅ Отмена в кассе: -{self.cash_amount}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка отмены в кассе: {e}")
            return False

    @property
    def cash_register_status(self):
        from analytics.models import CashHistory
        """
        ✅ ПРОВЕРКА статуса в кассе
        """
        from django.utils import timezone
        
        if self.cash_amount <= 0:
            return {'status': 'no_cash', 'message': 'Транзакция без наличных'}
        
        today = timezone.now().date()
        
        # Ищем запись в истории кассы
        cash_history = CashHistory.objects.filter(
            store=self.store,
            notes__contains=f"#{self.id}",
            operation_type='ADD_CASH'
        ).first()
        
        if cash_history:
            return {
                'status': 'processed',
                'message': f'Добавлено в кассу {cash_history.amount} сум',
                'cash_register_id': cash_history.cash_register.id,
                'processed_at': cash_history.timestamp
            }
        else:
            return {
                'status': 'not_processed',
                'message': 'Не добавлено в кассу',
                'action': 'Вызовите update_cash_register()'
            }

class TransactionItem(StoreOwnedModel):
    """
    ОБНОВЛЕННАЯ модель элемента транзакции с поддержкой дробных количеств
    """
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'inventory.Product',  # ← Строка! Без импорта
        on_delete=models.PROTECT,
        related_name='sale_items'
    )
    quantity = models.DecimalField(
        max_digits=15,  # Поддержка больших количеств
        decimal_places=3,  # Поддержка до тысячных
        validators=[MinValueValidator(Decimal('0.001'))],  # Минимум 0.001
        help_text="Количество товара (поддерживает дробные значения)"
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    
    # Дополнительные поля для аналитики
    unit_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Тип единицы измерения на момент продажи"
    )
    unit_display = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Отображение единицы измерения"
    )
    size_snapshot = models.JSONField(
        null=True,
        blank=True,
        help_text="Снимок размерной информации на момент продажи"
    )

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = "Элемент продажи"
        verbose_name_plural = "Элементы продаж"
        indexes = [
            models.Index(fields=['product', 'transaction']),
            models.Index(fields=['unit_type']),
        ]

    def __str__(self):
        return f"{self.product.name} × {self.quantity} {self.unit_display} в продаже #{self.transaction.id}"

    @property
    def subtotal(self):
        """Подсчет подытога"""
        return self.quantity * self.price

    @property
    def unit_price(self):
        """Цена за единицу"""
        return self.price

    def save(self, *args, **kwargs):
        """
        Автоматически сохраняем информацию о единицах измерения и размерах
        """
        if self.product:
            # Сохраняем информацию о единицах измерения
            self.unit_type = self.product.unit_type or 'custom'
            self.unit_display = self.product.unit_display
            
            # Сохраняем снимок размерной информации
            if self.product.has_sizes and self.product.default_size:
                size = self.product.default_size
                self.size_snapshot = {
                    'size': size.size,
                    'dimension1': float(size.dimension1) if size.dimension1 else None,
                    'dimension2': float(size.dimension2) if size.dimension2 else None,
                    'dimension3': float(size.dimension3) if size.dimension3 else None,
                    'dimension1_label': size.dimension1_label,
                    'dimension2_label': size.dimension2_label,
                    'dimension3_label': size.dimension3_label,
                    'description': size.description,
                    'saved_at': str(timezone.now())
                }

        super().save(*args, **kwargs)

    def validate_quantity(self):
        """
        Валидация количества в соответствии с настройками товара
        """
        if not self.product:
            return

        # Проверяем минимальное количество
        min_quantity = self.product.min_sale_quantity
        if self.quantity < min_quantity:
            raise ValueError(
                f"Количество {self.quantity} меньше минимального: {min_quantity}"
            )

        # Проверяем поддержку дробных значений
        if not self.product.allow_decimal and self.quantity % 1 != 0:
            raise ValueError(
                f"Товар не поддерживает дробные количества: {self.quantity}"
            )

        # Проверяем соответствие шагу
        step = self.product.quantity_step
        if step and step > 0:
            remainder = (self.quantity % step)
            if remainder > Decimal('0.001'):
                raise ValueError(
                    f"Количество {self.quantity} не соответствует шагу {step}"
                )

    def clean(self):
        """Django валидация"""
        super().clean()
        if self.product:
            self.validate_quantity()


class TransactionHistory(StoreOwnedModel):
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='history'
    )
    action = models.CharField(
        max_length=50,
        choices=[('created', 'Создана'), ('completed', 'Завершена'), ('refunded', 'Возвращена')]
    )
    details = models.TextField()  # JSON или текст с информацией
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = "История продажи"
        verbose_name_plural = "История продаж"
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        # если магазин не указан → берём из транзакции
        if not self.store_id and self.transaction_id:
            self.store = self.transaction.store
        else:
            # защита: если кто-то попробует подменить
            if self.store_id != self.transaction.store_id:
                raise ValueError("Магазин истории должен совпадать с магазином транзакции")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.action} для продажи #{self.transaction.id} от {self.created_at}"


# НОВАЯ модель для отслеживания возвратов с дробными единицами
class TransactionRefund(StoreOwnedModel):
    """
    Модель для отслеживания возвратов товаров
    """
    original_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='refunds'
    )
    refund_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='refund_for',
        null=True,
        blank=True
    )
    
    refunded_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Сумма возврата"
    )
    
    refund_type = models.CharField(
        max_length=20,
        choices=[
            ('full', 'Полный возврат'),
            ('partial', 'Частичный возврат'),
            ('exchange', 'Обмен')
        ],
        default='full'
    )
    
    reason = models.TextField(
        blank=True,
        help_text="Причина возврата"
    )
    
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='processed_refunds'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = "Возврат"
        verbose_name_plural = "Возвраты"
        ordering = ['-created_at']

    def __str__(self):
        return f"Возврат #{self.id} для транзакции #{self.original_transaction.id}"


class TransactionRefundItem(StoreOwnedModel):
    """
    Элементы возврата с поддержкой дробных количеств
    """
    refund = models.ForeignKey(
        TransactionRefund,
        on_delete=models.CASCADE,
        related_name='items'
    )
    original_item = models.ForeignKey(
        TransactionItem,
        on_delete=models.CASCADE,
        related_name='refunds'
    )
    
    refunded_quantity = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        help_text="Возвращенное количество"
    )
    
    refunded_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Возвращенная сумма"
    )

    objects = StoreOwnedManager()

    class Meta:
        verbose_name = "Элемент возврата"
        verbose_name_plural = "Элементы возвратов"

    def __str__(self):
        return f"Возврат {self.refunded_quantity} × {self.original_item.product.name}"

    @property
    def can_refund_quantity(self):
        """Максимальное количество, которое можно вернуть"""
        already_refunded = TransactionRefundItem.objects.filter(
            original_item=self.original_item
        ).aggregate(
            total=models.Sum('refunded_quantity')
        )['total'] or Decimal('0')
        
        return self.original_item.quantity - already_refunded
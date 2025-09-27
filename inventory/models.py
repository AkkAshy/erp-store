# inventory/models.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
import logging
from django.db import models
from django.core.validators import MinValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum, F, Min, Avg
from django.conf import settings
from django.utils.text import format_lazy
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
import barcode
from io import BytesIO
from barcode.writer import ImageWriter
from PIL import Image as PILImage
from io import BytesIO
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from stores.mixins import StoreOwnedModel, StoreOwnedManager
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from django.contrib.postgres.fields import ArrayField  # Для PostgreSQL (опционально)
import uuid
from users.models import Employee  # Импортируем модель Employee


pdfmetrics.registerFont(
    TTFont("DejaVuSans", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf")
)
addMapping('DejaVuSans', 0, 0, 'DejaVuSans')
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('inventory')

class SoftDeleteManager(models.Manager):
    """Менеджер для работы только с активными (не удаленными) объектами"""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

    def with_deleted(self):
        """Получить все объекты, включая удаленные"""
        return super().get_queryset()

    def deleted_only(self):
        """Получить только удаленные объекты"""
        return super().get_queryset().filter(deleted_at__isnull=False)


class StoreOwnedSoftDeleteManager(SoftDeleteManager):
    """Комбинированный менеджер для Store-owned моделей с soft delete"""

    def for_store(self, store):
        return self.get_queryset().filter(store=store)

    def with_deleted_for_store(self, store):
        return self.with_deleted().filter(store=store)


class StockHistory(models.Model):
    """
    История изменений стока — пульс склада.
    Записывается автоматически через signals при:
    - Создании/обновлении ProductBatch (поступление)
    - Продажах (Sales/Orders)
    - Возвратах/корректировках
    """
    
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False
    )
    
    # Связи — кто, где, когда
    product = models.ForeignKey(
        'Product', 
        on_delete=models.CASCADE, 
        related_name='stock_history'
    )
    store = models.ForeignKey(
        'stores.Store', 
        on_delete=models.CASCADE,
        related_name='stock_history'
    )
    batch = models.ForeignKey(
        'ProductBatch', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='stock_history_entries'
    )  # Если изменение связано с конкретной партией
    
    # Временные метки — основа аналитики
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    date_only = models.DateField(auto_now_add=True, db_index=True)  # Для группировки по дням
    
    # Количества — до и после
    quantity_before = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    quantity_after = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    quantity_change = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    
    # Тип операции — что произошло
    operation_type = models.CharField(
        max_length=50,
        choices=[
            ('INCOMING', 'Поступление'),      # Новый батч
            ('SALE', 'Продажа'),              # Отгрузка
            ('RETURN', 'Возврат'),            # Поступление обратно
            ('CORRECTION', 'Корректировка'),  # Ручное изменение
            ('EXPIRATION', 'Списание'),       # Просрочка
            ('TRANSFER', 'Перемещение'),      # Между магазинами
            ('REVALUATION', 'Переоценка'),    # Изменение цены
        ],
        db_index=True
    )
    
    # Детали операции — контекст для анализа
    reference_id = models.CharField(max_length=100, blank=True, null=True)  # ID заказа/документа
    user = models.ForeignKey(
        'auth.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='stock_changes'
    )  # Кто сделал изменение
    
    # Размер и атрибуты — для детального анализа
    size = models.ForeignKey(
        'SizeInfo', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    attributes_snapshot = ArrayField(  # PostgreSQL: моментальный снимок атрибутов
        models.JSONField(),
        size=10,
        blank=True,
        null=True
    )  # [{'attribute_value_id': 1, 'quantity': 5}, ...]
    
    # Финансовые метки — для маржинального анализа
    purchase_price_at_time = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    sale_price_at_time = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Статус и примечания
    notes = models.TextField(blank=True, null=True)
    is_automatic = models.BooleanField(default=True)  # Сигнал или вручную?
    
    # Индексы для скорости аналитики
    class Meta:
        db_table = 'inventory_stock_history'
        indexes = [
            models.Index(fields=['product', 'date_only']),  # Тренды по продукту
            models.Index(fields=['store', 'date_only']),    # Тренды по магазину
            models.Index(fields=['timestamp']),             # Временные ряды
            models.Index(fields=['operation_type', 'date_only']),  # Анализ операций
        ]
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.product.name} | {self.operation_type} | {self.quantity_change} | {self.timestamp.strftime('%Y-%m-%d')}"
    
    def save(self, *args, **kwargs):
        """Автоматические расчёты при сохранении"""
        if self.pk is None:  # Новый объект
            self.quantity_change = self.quantity_after - self.quantity_before
        super().save(*args, **kwargs)
        if self.notes:
            self.notes = self.notes.replace(":", "-")
        super().save(*args, **kwargs)


    
    @classmethod
    def get_daily_summary(cls, product, date):
        """Ежедневная сводка для аналитики"""
        entries = cls.objects.filter(product=product, date_only=date)
        return {
            'date': date,
            'total_incoming': entries.filter(operation_type='INCOMING').aggregate(
                sum=models.Sum('quantity_change')
            )['sum'] or 0,
            'total_sales': abs(entries.filter(operation_type='SALE').aggregate(
                sum=models.Sum('quantity_change')
            )['sum'] or 0),
            'net_change': entries.aggregate(sum=models.Sum('quantity_change'))['sum'] or 0,
            'end_of_day_stock': entries.last().quantity_after if entries.exists() else 0
        }


class CustomUnit(StoreOwnedModel):
    """Пользовательские единицы измерения для магазина"""
    name = models.CharField(
        max_length=50, 
        verbose_name="Полное название",
        help_text="Например: Дюйм, Галлон, Коробка"
    )
    short_name = models.CharField(
        max_length=10, 
        verbose_name="Сокращение",
        help_text="Например: дюйм, гал, кор"
    )
    allow_decimal = models.BooleanField(
        default=False,
        verbose_name="Разрешить дробные",
        help_text="Можно ли продавать 1.5 единицы"
    )
    min_quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=3,
        default=1,
        verbose_name="Минимум для продажи"
    )
    step = models.DecimalField(
        max_digits=10,
        decimal_places=3, 
        default=1,
        verbose_name="Шаг изменения",
        help_text="Например: 0.1, 0.5, 1"
    )
    
    objects = StoreOwnedManager()
    
    class Meta:
        verbose_name = "Единица измерения"
        verbose_name_plural = "Единицы измерения"
        unique_together = ['store', 'short_name']
    
    def __str__(self):
        return f"{self.name} ({self.short_name})"



class SizeInfo(StoreOwnedModel):
    """
    Универсальная модель для размерных характеристик
    Для сантехники: диаметры труб (1/2", 3/4"), размеры фитингов и т.д.
    """
    # Убираем SIZE_CHOICES - делаем свободный ввод
    size = models.CharField(
        max_length=50, 
        verbose_name="Размер/Вариант",
        help_text="Например: 1/2\", 3/4\", 20мм, DN15"
    )
    
    # Переименовываем поля для универсальности
    dimension1 = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Параметр 1",
        help_text="Например: внутренний диаметр (мм)"
    )
    dimension2 = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Параметр 2", 
        help_text="Например: внешний диаметр (мм)"
    )
    dimension3 = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Параметр 3",
        help_text="Например: толщина стенки (мм)"
    )
    
    # Метки для параметров
    dimension1_label = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        default="Внутр. диаметр",
        verbose_name="Название параметра 1"
    )
    dimension2_label = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        default="Внешн. диаметр",
        verbose_name="Название параметра 2"
    )
    dimension3_label = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        default="Толщина стенки",
        verbose_name="Название параметра 3"
    )
    
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="Описание"
    )
    
    sort_order = models.IntegerField(
        default=0,
        verbose_name="Порядок сортировки"
    )

    objects = StoreOwnedManager()
    all_objects = models.Manager()  # Для доступа ко всем, включая удаленные
    
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата удаления")

    class Meta:
        verbose_name = "Размер/Вариант"
        verbose_name_plural = "Размеры/Варианты"
        ordering = ['sort_order', 'size']
        constraints = [
            # ✅ КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Уникальность только для активных записей
            models.UniqueConstraint(
                fields=['store', 'size'],
                name='unique_active_size_per_store',
                condition=models.Q(deleted_at__isnull=True)  # Только для не удаленных
            )
        ]

    def __str__(self):
        return f"{self.size} ({self.store.name if self.store else 'Без магазина'})"

    @property
    def full_description(self):
        """Полное описание с параметрами"""
        parts = [self.size]
        
        if self.dimension1 and self.dimension1_label:
            parts.append(f"{self.dimension1_label}: {self.dimension1}")
        if self.dimension2 and self.dimension2_label:
            parts.append(f"{self.dimension2_label}: {self.dimension2}")
        if self.dimension3 and self.dimension3_label:
            parts.append(f"{self.dimension3_label}: {self.dimension3}")
            
        return " | ".join(parts)


    def __str__(self):
        status = " (удален)" if self.deleted_at else ""
        return f"{self.size} ({self.store.name if self.store else 'Без магазина'}){status}"

    def delete(self, using=None, keep_parents=False):
        """Soft delete - помечаем как удаленный"""
        self.deleted_at = timezone.now()
        self.save(using=using)

    def hard_delete(self, using=None, keep_parents=False):
        """Реальное удаление из БД"""
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        """Восстановление удаленного размера"""
        self.deleted_at = None
        self.save()

    @property
    def is_deleted(self):
        """Проверка, удален ли размер"""
        return self.deleted_at is not None


# class ProductCategory(StoreOwnedModel):
#     name = models.CharField(max_length=255, verbose_name="Название")
#     created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
#     objects = StoreOwnedManager()

#     class Meta:
#         verbose_name = "Категория товара"
#         verbose_name_plural = "Категории товаров"
#         ordering = ['name']
#         constraints = [
#             models.UniqueConstraint(fields=['store', 'name'], name='unique_category_per_store')
#         ]

#     def __str__(self):
#         return self.name




class ProductCategory(StoreOwnedModel):
    name = models.CharField(max_length=255, verbose_name="Название")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата удаления")

    # Менеджеры
    objects = StoreOwnedSoftDeleteManager()  # По умолчанию показывает только активные
    all_objects = models.Manager()  # Показывает все, включая удаленные

    class Meta:
        verbose_name = "Категория товара"
        verbose_name_plural = "Категории товаров"
        ordering = ['name']
        # ✅ КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Уникальность только для активных записей
        constraints = [
            models.UniqueConstraint(
                fields=['store', 'name'],
                name='unique_active_category_per_store',
                condition=models.Q(deleted_at__isnull=True)  # Только для не удаленных
            )
        ]

    def __str__(self):
        status = " (удалена)" if self.deleted_at else ""
        return f"{self.name}{status}"

    def delete(self, using=None, keep_parents=False):
        """Soft delete - помечаем как удаленную"""
        self.deleted_at = timezone.now()
        self.save(using=using)

    def hard_delete(self, using=None, keep_parents=False):
        """Реальное удаление из БД"""
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        """Восстановление удаленной категории"""
        self.deleted_at = None
        self.save()

    @property
    def is_deleted(self):
        """Проверка, удалена ли категория"""
        return self.deleted_at is not None


class AttributeType(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название")
    slug = models.SlugField(max_length=100, unique=True, verbose_name="Слаг")
    is_filterable = models.BooleanField(default=False, verbose_name="Фильтруемый ли?")

    class Meta:
        verbose_name = "Тип атрибута"
        verbose_name_plural = "Типы атрибутов"
        ordering = ['name']

    def __str__(self):
        return self.name


class AttributeValue(models.Model):
    attribute_type = models.ForeignKey(
        AttributeType,
        on_delete=models.CASCADE,
        related_name='values',
        verbose_name="Тип атрибута"

    )
    value = models.CharField(max_length=225, verbose_name="Значение")
    slug = models.SlugField(max_length=225, unique=True, verbose_name="Слаг")
    ordering = models.PositiveIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Значение атрибута"
        verbose_name_plural = "Значения атрибутов"
        ordering = ['ordering', 'value']
        unique_together = ('attribute_type', 'slug')

    def __str__(self):
        return f"{self.attribute_type.name}: {self.value} ({self.slug})"


class Product(StoreOwnedModel):
    # Системные единицы измерения
    SYSTEM_UNITS = [
        ('piece', 'Штука'),
        ('meter', 'Метр'),
        ('m2', 'Кв.метр'),
        ('kg', 'Килограмм'),
        ('liter', 'Литр'),
        ('pack', 'Упаковка'),
        ('set', 'Комплект'),
    ]
    
    # Настройки для системных единиц
    UNIT_SETTINGS = {
        'piece': {'decimal': False, 'min': 1, 'step': 1},
        'meter': {'decimal': True, 'min': 0.1, 'step': 0.01},
        'm2': {'decimal': True, 'min': 0.01, 'step': 0.01},
        'kg': {'decimal': True, 'min': 0.01, 'step': 0.001},
        'liter': {'decimal': True, 'min': 0.1, 'step': 0.01},
        'pack': {'decimal': False, 'min': 1, 'step': 1},
        'set': {'decimal': False, 'min': 1, 'step': 1},
    }
    
    name = models.CharField(max_length=255, verbose_name="Название")
    barcode = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Штрих-код"
    )
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name="Категория"
    )
    
    # Единица измерения - системная или пользовательская
    unit_type = models.CharField(
        max_length=20,
        choices=SYSTEM_UNITS,
        null=True,
        blank=True,
        verbose_name="Системная единица"
    )
    custom_unit = models.ForeignKey(
        CustomUnit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Пользовательская единица"
    )
    
    # Переопределение настроек единицы
    override_min_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Свой минимум продажи"
    )
    override_step = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Свой шаг"
    )
    
    sale_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Рекомендованная цена продажи"
    )
    
    # Размеры/варианты товара
    has_sizes = models.BooleanField(
        default=False,
        verbose_name="Имеет размеры/варианты",
        help_text="Например: трубы разных диаметров"
    )
    default_size = models.ForeignKey(
        SizeInfo, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='products_default',
        verbose_name="Основной размер"
    )
    available_sizes = models.ManyToManyField(
        SizeInfo,
        blank=True,
        related_name='products_available',
        verbose_name="Доступные размеры"
    )
    
    # Атрибуты товара (материал, производитель и т.д.)
    attributes = models.ManyToManyField(
        AttributeValue,
        blank=True,
        related_name='products',
        verbose_name="Атрибуты"
    )
    
    # Метаданные
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products_created',
        verbose_name="Создан пользователем"
    )
    
    image_label = models.ImageField(
        upload_to='product_labels/',
        null=True,
        blank=True,
        verbose_name="Изображение этикетки"
    )
    
    # Мягкое удаление
    is_deleted = models.BooleanField(
        default=False,
        verbose_name="Удален",
        help_text="Мягкое удаление - товар скрыт, но сохранен для истории"
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата удаления"
    )

    objects = StoreOwnedManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        indexes = [
            models.Index(fields=['name', 'barcode']),
            models.Index(fields=['store', 'name']),
            models.Index(fields=['store', 'barcode']),
            models.Index(fields=['is_deleted']),
        ]
        unique_together = ['store', 'barcode']

    def __str__(self):
        return f"{self.name} ({self.unit_display})"

    def clean(self):
        """Валидация - должна быть указана единица измерения"""
        if not self.unit_type and not self.custom_unit:
            raise ValidationError("Укажите единицу измерения")
        if self.unit_type and self.custom_unit:
            raise ValidationError("Выберите либо системную, либо пользовательскую единицу")
    
    # === СВОЙСТВА ДЛЯ ЕДИНИЦ ИЗМЕРЕНИЯ ===
    @property
    def unit_display(self):
        """Отображение единицы"""
        if self.custom_unit:
            return self.custom_unit.short_name
        return dict(self.SYSTEM_UNITS).get(self.unit_type, self.unit_type)
    
    @property
    def allow_decimal(self):
        """Можно ли продавать дробные"""
        if self.custom_unit:
            return self.custom_unit.allow_decimal
        return self.UNIT_SETTINGS.get(self.unit_type, {}).get('decimal', False)
    
    @property
    def min_sale_quantity(self):
        """Минимальное количество для продажи"""
        if self.override_min_quantity:
            return self.override_min_quantity
        if self.custom_unit:
            return self.custom_unit.min_quantity
        return Decimal(str(self.UNIT_SETTINGS.get(self.unit_type, {}).get('min', 1)))
    
    @property
    def quantity_step(self):
        """Шаг изменения количества"""
        if self.override_step:
            return self.override_step
        if self.custom_unit:
            return self.custom_unit.step
        return Decimal(str(self.UNIT_SETTINGS.get(self.unit_type, {}).get('step', 1)))
    
    # === СВОЙСТВА ДЛЯ ЦЕН И НАЦЕНОК ===
    @property
    def average_purchase_price(self):
        """Средневзвешенная закупочная цена"""
        batches = self.batches.filter(
            quantity__gt=0,
            purchase_price__isnull=False
        )
        if not batches.exists():
            return None
            
        total_cost = Decimal('0')
        total_quantity = Decimal('0')
        for batch in batches:
            total_cost += batch.purchase_price * batch.quantity
            total_quantity += batch.quantity
        
        return total_cost / total_quantity if total_quantity > 0 else None
    
    @property
    def last_purchase_price(self):
        """Последняя закупочная цена"""
        last_batch = self.batches.filter(
            purchase_price__isnull=False
        ).order_by('-created_at').first()
        
        return last_batch.purchase_price if last_batch else None
    
    @property
    def min_purchase_price(self):
        """Минимальная закупочная цена из активных партий"""
        min_price = self.batches.filter(
            quantity__gt=0,
            purchase_price__isnull=False
        ).aggregate(min_price=Min('purchase_price'))['min_price']
        
        return min_price
    
    @property
    def min_sale_price(self):
        """Минимальная цена продажи с учетом наценки магазина"""
        base_price = self.min_purchase_price
        if not base_price:
            base_price = self.last_purchase_price
        
        if not base_price:
            return Decimal('0')
        
        # Получаем минимальную наценку из магазина
        if hasattr(self.store, 'min_markup_percent'):
            multiplier = 1 + (self.store.min_markup_percent / 100)
            return base_price * Decimal(str(multiplier))
        
        return base_price
    
    @property
    def price_info(self):
        """Информация о ценах для API"""
        avg_purchase = self.average_purchase_price
        min_purchase = self.min_purchase_price
        last_purchase = self.last_purchase_price
        
        return {
            'sale_price': float(self.sale_price),
            'purchase_prices': {
                'average': float(avg_purchase) if avg_purchase else None,
                'minimum': float(min_purchase) if min_purchase else None,
                'last': float(last_purchase) if last_purchase else None,
            },
            'min_sale_price': float(self.min_sale_price),
            'min_markup_percent': float(self.store.min_markup_percent) if hasattr(self.store, 'min_markup_percent') else 0,
            'current_margin': self._calculate_margin(self.sale_price, avg_purchase),
            'batches_count': self.batches.filter(quantity__gt=0).count()
        }
    
    def complete_movement_history(self, days=30):
        """✅ Ленивый импорт TransactionItem — только внутри метода"""
        from_date = timezone.now() - timedelta(days=days)
        
        # ✅ ЛЕНИВЫЙ ИМПОРТ — только здесь!
        from sales.models import TransactionItem
        
        # Теперь filter работает без проблем
        sales_items = TransactionItem.objects.filter(
            product=self,
            transaction__created_at__gte=from_date,
            transaction__status='completed'
        ).values_list('quantity', 'price')
        
        # Подсчёт выручки (как мы обсуждали)
        sales_revenue = sum(
            Decimal(str(qty)) * Decimal(str(price))
            for qty, price in sales_items
        )
        
        # Остальная логика (StockHistory и т.д.)
        incoming = self.stock_history.filter(
            operation_type='INCOMING',
            timestamp__gte=from_date
        ).aggregate(total_in=Sum('quantity_change'))['total_in'] or Decimal('0.00')
        
        sales_history = self.stock_history.filter(
            operation_type='SALE',
            timestamp__gte=from_date
        ).aggregate(total_sold=Sum('quantity_change'))['total_sold'] or Decimal('0.00')
        
        current_stock = Decimal(str(self.stock.quantity)) if hasattr(self, 'stock') else Decimal('0.00')
        
        # Маржа
        avg_purchase = (self.price_info['purchase_prices']['average'] 
                       if self.price_info and 'purchase_prices' in self.price_info 
                       else 0)
        avg_purchase = Decimal(str(avg_purchase))
        cost_of_goods_sold = abs(sales_history) * avg_purchase
        margin = sales_revenue - cost_of_goods_sold
        
        return {
            'period_days': days,
            'incoming': float(incoming),
            'sold': float(abs(sales_history)),
            'current_stock': float(current_stock),
            'revenue': float(sales_revenue),
            'cost_of_goods': float(cost_of_goods_sold),
            'margin': float(margin),
            'margin_percentage': float((margin / sales_revenue * 100) if sales_revenue else 0),
            'inventory_turnover': float(abs(sales_history) / (current_stock or Decimal('1.00'))),
            'days_of_stock': float(current_stock / (abs(sales_history) / Decimal(str(days))) if sales_history else 999)
        }
    
    
    def inventory_turnover(self, period_days=30):
        """Коэффициент оборачиваемости запасов за заданный период (по умолчанию 30 дней)"""
        from_date = timezone.now() - timedelta(days=period_days)
        sales = self.sales.aggregate(total=Sum('quantity'))['total'] or 0  # Предполагаю модель Sales
        avg_stock = self.stock.aggregate(avg=Avg('quantity'))['avg'] or 1  # Избежать деления на 0
        return sales / avg_stock if avg_stock else 0
    
    def _calculate_margin(self, sale_price, purchase_price):
        """Расчет маржи в процентах"""
        if not purchase_price or purchase_price == 0:
            return None
        return float(((sale_price - purchase_price) / purchase_price) * 100)
    
    def validate_sale_price(self, proposed_price, user_role=None):
        """Валидация цены продажи с учетом минимальной наценки"""
        min_price = self.min_sale_price
        
        if proposed_price < min_price:
            # Проверяем права пользователя
            if user_role in ['owner', 'admin'] and self.store.allow_sale_below_markup:
                return {
                    'valid': True,
                    'warning': f'Цена ниже минимальной наценки ({min_price}), но разрешена для администраторов'
                }
            else:
                return {
                    'valid': False,
                    'error': f'Цена не может быть ниже {min_price} (минимальная наценка {self.store.min_markup_percent}%)',
                    'min_price': float(min_price),
                    'min_markup_percent': float(self.store.min_markup_percent)
                }
        
        return {'valid': True}
    
    # === МЕТОДЫ ДЛЯ РАЗМЕРОВ ===
    @property
    def sizes_info(self):
        """Информация о размерах товара"""
        if not self.has_sizes:
            return None
            
        sizes_in_stock = []
        for batch in self.batches.filter(quantity__gt=0, size__isnull=False):
            sizes_in_stock.append({
                'size_id': batch.size.id,
                'size': batch.size.size,
                'quantity': float(batch.quantity),
                'purchase_price': float(batch.purchase_price) if batch.purchase_price else None
            })
            
        return {
            'has_sizes': True,
            'default_size': self.default_size.size if self.default_size else None,
            'available_sizes': list(self.available_sizes.values_list('size', flat=True)),
            'sizes_in_stock': sizes_in_stock
        }
    
    # === ОСТАЛЬНЫЕ МЕТОДЫ ===
    def soft_delete(self):
        """Мягкое удаление товара"""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])
        
        if hasattr(self, 'stock'):
            self.stock.quantity = 0
            self.stock.save()

    def restore(self):
        """Восстановление товара"""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])

    @classmethod
    def generate_unique_barcode(cls):
        """Генерация уникального штрих-кода"""
        import uuid
        import random
        import time
        
        max_attempts = 100
        attempts = 0
        
        while attempts < max_attempts:
            timestamp = str(int(time.time()))[-6:]
            random_part = str(random.randint(100000, 999999))
            barcode_code = timestamp + random_part
            checksum = cls()._calculate_ean13_checksum(barcode_code)
            full_ean = barcode_code + checksum
            
            if not cls.objects.filter(barcode=full_ean).exists():
                return full_ean
            attempts += 1
        
        data12 = str(uuid.uuid4().int)[:12]
        return data12 + cls()._calculate_ean13_checksum(data12)
    
    def _calculate_ean13_checksum(self, digits):
        """Вычисляет контрольную цифру EAN-13"""
        weights = [1, 3] * 6
        total = sum(int(d) * w for d, w in zip(digits, weights))
        return str((10 - (total % 10)) % 10)

    def save(self, *args, **kwargs):
        """Сохранение с автогенерацией штрих-кода"""
        is_new = self._state.adding
        
        if is_new and not self.barcode:
            self.barcode = self.generate_unique_barcode()
        
        super().save(*args, **kwargs)




class ProductAttribute(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='product_attributes',
        verbose_name="Товар"
    )
    attribute_value = models.ForeignKey(
        AttributeValue,
        on_delete=models.CASCADE,
        related_name='product_attributes',
        verbose_name="Значение атрибута"
    )

    class Meta:
        verbose_name = "Атрибут товара"
        verbose_name_plural = "Атрибуты товаров"
        unique_together = ('product', 'attribute_value')

    def __str__(self):
        return f"{self.product.name} - {self.attribute_value.value}"


class SizeChart(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        verbose_name = "Таблица размеров"
        verbose_name_plural = "Таблицы размеров"
        ordering = ['name']

    def __str__(self):
        return self.name


class ProductBatch(StoreOwnedModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='batches'
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name="Количество"
    )
    purchase_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Цена закупки за единицу",
    )
    purchase_price_usd = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Цена закупки в USD"
    )
    purchase_rate = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Курс покупки USD"
    )
    size = models.ForeignKey(
        SizeInfo,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Размер/Вариант",
        help_text="Если товар имеет размерные вариации"
    )
    supplier = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,  
        verbose_name="Поставщик"
    )
    supplier_country = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Старана поставщика"
    )
    invoice_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Номер накладной"
    )
    expiration_date = models.DateField(
        null=True, 
        blank=True, 
        verbose_name="Срок годности",
        help_text="Для герметиков, клеев и т.д."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    objects = StoreOwnedManager()

    class Meta:
        verbose_name = "Партия товара"
        verbose_name_plural = "Партии товаров"
        ordering = ['expiration_date', 'created_at']

    def __str__(self):
        size_info = f" ({self.size.size})" if self.size else ""
        return f"{self.product.name}{size_info} × {self.quantity} {self.product.unit_display}"

    @property
    def total_cost(self):
        """Общая стоимость партии"""
        if self.purchase_price:
            return self.purchase_price * self.quantity
        return Decimal('0')
    
    @property
    def min_sale_price_per_unit(self):
        """Минимальная цена продажи единицы из этой партии"""
        if not self.purchase_price:
            return Decimal('0')
        
        if hasattr(self.product.store, 'min_markup_percent'):
            multiplier = 1 + (self.product.store.min_markup_percent / 100)
            return self.purchase_price * Decimal(str(multiplier))
        
        return self.purchase_price
    
    @property
    def total_cost(self):
        """Общая стоимость партии"""
        if self.purchase_price:
            return self.purchase_price * self.quantity
        elif self.purchase_price_usd and self.purchase_rate:
            return (self.purchase_price_usd * self.purchase_rate) * self.quantity
        return Decimal('0')
    
    def clean(self):
        """Валидация"""
        super().clean()
        
        if self.product and self.product.has_sizes and not self.size:
            raise ValidationError("Для этого товара необходимо указать размер")
        
        if self.product and not self.product.has_sizes and self.size:
            raise ValidationError("Этот товар не имеет размерных вариаций")
        
        if self.size and self.product:
            if not self.product.available_sizes.filter(id=self.size.id).exists():
                raise ValidationError(f"Размер {self.size} не доступен для товара {self.product.name}")

    def sell(self, quantity):
        """Продажа из партии"""
        quantity = Decimal(str(quantity))
        
        if quantity > self.quantity:
            raise ValueError(
                f"Недостаточно товара в партии. Доступно: {self.quantity}, запрошено: {quantity}"
            )
        
        self.quantity = F('quantity') - quantity
        self.save(update_fields=['quantity'])
        self.refresh_from_db()

        if self.quantity <= 0:
            self.delete()
            logger.info(f"Партия {self.id} удалена (товар {self.product.name})")

        return quantity

class Stock(StoreOwnedModel):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='stock',
        verbose_name="Товар"
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name="Количество"
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    objects = StoreOwnedManager()

    class Meta:
        verbose_name = "Остаток на складе"
        verbose_name_plural = "Остатки на складе"

    def __str__(self):
        return f"{self.product.name}: {self.quantity} {self.product.unit_display}"

    def update_quantity(self):
        """Обновляет общее количество товара на основе партий"""
        total = self.product.batches.aggregate(
            total=Sum('quantity')
        )['total'] or Decimal('0')
        self.quantity = total
        self.save(update_fields=['quantity', 'updated_at'])

    def sell(self, quantity):
        """Списывает товар по FIFO"""
        quantity = Decimal(str(quantity))
        
        if quantity <= 0:
            raise ValueError("Количество должно быть положительным")

        if self.quantity < quantity:
            raise ValueError(
                f"Недостаточно товара '{self.product.name}'. "
                f"Доступно: {self.quantity} {self.product.unit_display}, "
                f"запрошено: {quantity}"
            )

        remaining = quantity
        batches = self.product.batches.order_by('expiration_date', 'created_at')

        for batch in batches:
            if remaining <= 0:
                break

            sell_amount = min(remaining, batch.quantity)
            batch.sell(sell_amount)
            remaining -= sell_amount

        self.update_quantity()
        logger.info(f"Продано {quantity} {self.product.unit_display} {self.product.name}")

    def stockout_rate(self, period_days=30):
        from_date = timezone.now() - timedelta(days=period_days)
        out_days = StockHistory.objects.filter(  # Нужна история стока
            product=self.product, date__gte=from_date, quantity=0
        ).count()
        return (out_days / period_days) * 100 if period_days else 0


class ProductBatchAttribute(StoreOwnedModel):
    batch = models.ForeignKey(ProductBatch, on_delete=models.CASCADE, related_name='attributes')
    product_attribute = models.ForeignKey(ProductAttribute, on_delete=models.PROTECT)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))]
    )

    class Meta:
        verbose_name = "Атрибут партии"
        verbose_name_plural = "Атрибуты партии"


# ✅ ИСПРАВЛЕНИЕ: Исправляем сигналы
@receiver(post_save, sender=Product)
def create_product_stock(sender, instance, created, **kwargs):
    """
    Создаем Stock ТОЛЬКО после того как Product полностью сохранен со store
    """
    if created and not hasattr(instance, 'stock'):
        # ✅ ВАЖНО: Проверяем что у Product есть store
        if hasattr(instance, 'store') and instance.store:
            try:
                stock, stock_created = Stock.objects.get_or_create(
                    product=instance,
                    defaults={
                        'store': instance.store,  # ← Берем store из Product
                        'quantity': 0
                    }
                )
                if stock_created:
                    logger.info(f"✅ Stock created for product: {instance.name} in store: {instance.store.name}")
                else:
                    logger.info(f"ℹ️ Stock already exists for product: {instance.name}")
            except Exception as e:
                logger.error(f"❌ Error creating stock for product {instance.name}: {str(e)}")
        else:
            logger.warning(f"⚠️ Cannot create stock for product {instance.name}: no store assigned")


@receiver(post_save, sender=ProductBatch)
def update_stock_on_batch_change(sender, instance, **kwargs):
    """
    Обновляем остатки при изменении партии
    """
    try:
        # Получаем или создаем Stock для продукта
        stock, created = Stock.objects.get_or_create(
            product=instance.product,
            defaults={
                'store': instance.store,  # ← Берем store из ProductBatch
                'quantity': 0
            }
        )

        # Обновляем количество
        stock.update_quantity()

        if created:
            logger.info(f"✅ Stock created during batch update for: {instance.product.name}")
        else:
            logger.debug(f"✅ Stock updated for: {instance.product.name}")

    except Exception as e:
        logger.error(f"❌ Error updating stock for batch {instance.id}: {str(e)}")


class ExchangeRate(models.Model):
    date = models.DateField(unique=True, db_index=True)
    usd_rate = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.date} — {self.usd_rate} UZS"

class FinancialSummary(models.Model):
    """
    Дневная финансовая сводка по магазину
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='financial_summaries')
    
    # Оплата по методам
    cash_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transfer_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    card_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    debt_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Общие метрики
    total_transactions = models.IntegerField(default=0)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    avg_transaction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Аналитика по клиентам
    unique_customers = models.IntegerField(default=0)
    repeat_customers = models.IntegerField(default=0)
    customer_retention_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Маржинальность
    total_margin = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    margin_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Кассиры
    top_cashier_id = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True)
    top_cashier_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)


    # Проценты
    cash_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    card_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['date', 'store']
        indexes = [
            models.Index(fields=['date', 'store']),
            models.Index(fields=['store', 'date']),
        ]
        ordering = ['-date']
    
    def save(self, *args, **kwargs):
        if self.total_transactions > 0 and self.grand_total > 0:
            self.avg_transaction = self.grand_total / self.total_transactions
            self.cash_percentage = (self.cash_total / self.grand_total * 100)
            self.card_percentage = (self.card_total / self.grand_total * 100)
        super().save(*args, **kwargs)

    
    def get_cash_percentage(self):
        if self.grand_total == 0:
            return 0
        return float(self.cash_total) / float(self.grand_total) * 100
    
    def get_stock_usd(self, total_stock_value):
        usd_rate = getattr(self, 'usd_rate', None) or ExchangeRate.objects.filter(date__lte=self.date).order_by('-date').first()
        rate = usd_rate.usd_rate if usd_rate else Decimal('0')
        return float(total_stock_value / rate) if rate > 0 else 0.0

    def get_usd_summary(self):
        """
        Рассчитывает grand_total и total_margin в долларах на лету
        """
        from .models import ExchangeRate  # пример
        try:
            rate_obj = ExchangeRate.objects.get(date=self.date)
            usd_rate = rate_obj.usd_rate
        except ExchangeRate.DoesNotExist:
            # fallback: взять последний доступный курс
            rate_obj = ExchangeRate.objects.filter(date__lte=self.date).order_by('-date').first()
            usd_rate = rate_obj.usd_rate if rate_obj else Decimal('0')

        if usd_rate > 0:
            grand_total_usd = self.grand_total / usd_rate
            total_margin_usd = self.total_margin / usd_rate
        else:
            grand_total_usd = Decimal('0')
            total_margin_usd = Decimal('0')

        return {
            "usd_rate": usd_rate,
            "grand_total_usd": grand_total_usd,
            "total_margin_usd": total_margin_usd
        }

    def calculate_margins(self):
        """
        Рассчитывает маржу и сохраняет значения в UZS и USD.
        """
        from sales.models import Transaction
        from decimal import Decimal
        from django.db.models import Sum, F

        try:
            rate_obj = ExchangeRate.objects.get(date=self.date)
            self.usd_rate = rate_obj.usd_rate
        except ExchangeRate.DoesNotExist:
            # fallback: берём последний доступный курс
            rate_obj = ExchangeRate.objects.filter(date__lte=self.date).order_by('-date').first()
            self.usd_rate = rate_obj.usd_rate if rate_obj else Decimal('0')


        total_revenue = Decimal('0')
        total_cost = Decimal('0')
        transactions = Transaction.objects.filter(
            store=self.store,
            created_at__date=self.date,
            status='completed'
        ).prefetch_related('items__product__batches')

        total_revenue = Decimal('0')
        total_cost = Decimal('0')

        for trans in transactions:
            for item in trans.items.all():
                quantity = Decimal(item.quantity)
                revenue = quantity * item.price
                total_revenue += revenue

                # себестоимость — логика как у тебя выше
                product = item.product
                purchase_price = Decimal('0')
                batches = product.batches.all().order_by('-created_at')
                last_batch = next((b for b in batches if b.purchase_price is not None), None)

                if last_batch and last_batch.purchase_price:
                    purchase_price = last_batch.purchase_price
                else:
                    active_batches = [b for b in batches if b.quantity > 0 and b.purchase_price is not None]
                    if active_batches:
                        total_batch_cost = sum(b.purchase_price * b.quantity for b in active_batches)
                        total_batch_qty = sum(b.quantity for b in active_batches)
                        if total_batch_qty > 0:
                            purchase_price = total_batch_cost / total_batch_qty

                total_cost += quantity * purchase_price

        # --- USD ---
        if self.usd_rate > 0:
            self.grand_total_usd = self.grand_total / self.usd_rate
            self.total_margin_usd = self.total_margin / self.usd_rate

        self.save(update_fields=[
            'grand_total', 'total_margin', 'margin_percentage',
            'usd_rate', 'grand_total_usd', 'total_margin_usd'
        ])

        return {
            'revenue': total_revenue,
            'cost': total_cost,
            'margin': self.total_margin,
            'margin_percentage': self.margin_percentage,
            'grand_total_usd': self.grand_total_usd,
            'total_margin_usd': self.total_margin_usd,
            'usd_rate': self.usd_rate
        }

        
    def __str__(self):
        return f"{self.store.name} | {self.date} | {self.grand_total:,} сум"
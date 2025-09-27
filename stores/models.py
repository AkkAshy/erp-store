# stores/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
import uuid

class Store(models.Model):
    """
    Модель магазина - центральная сущность для мультитенантности
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Название магазина")
    )
    logo = models.ImageField(
        upload_to='store_logos/',
        null=True,
        blank=True,
        verbose_name=_("Логотип")
    )
    address = models.TextField(
        verbose_name=_("Адрес"),
        help_text=_("Полный адрес магазина")
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Телефон")
    )
    email = models.EmailField(
        blank=True,
        verbose_name=_("Email")
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Описание")
    )
    min_markup_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10.00,
        verbose_name="Минимальная наценка %",
        help_text="Минимальный процент наценки на закупочную цену (например: 10%)"
    )
    allow_sale_below_markup = models.BooleanField(
        default=False,
        verbose_name="Разрешить продажу ниже минимальной наценки",
        help_text="Только для админов/владельцев"
    )
    @property
    def min_markup_multiplier(self):
        """Коэффициент для расчета минимальной цены"""
        return 1 + (self.min_markup_percent / 100)

    # Владелец магазина (админ, который создал)
    owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='owned_stores',
        verbose_name=_("Владелец")
    )

    # Дополнительные настройки
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен")
    )
    currency = models.CharField(
        max_length=3,
        default='UZS',
        verbose_name=_("Валюта")
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        verbose_name=_("Налоговая ставка %")
    )

    # Настройки уведомлений
    low_stock_threshold = models.PositiveIntegerField(
        default=10,
        verbose_name=_("Порог низкого остатка")
    )

    # Метаданные
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Магазин")
        verbose_name_plural = _("Магазины")
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def get_total_products(self):
        """Получить количество товаров в магазине"""
        return self.products.count()

    def get_total_employees(self):
        """Получить количество сотрудников"""
        return self.store_employees.filter(is_active=True).count()

    def get_total_customers(self):
        """Получить количество клиентов"""
        return self.customers.count()

    def get_today_revenue(self):
        """Получить выручку за сегодня"""
        from django.utils import timezone
        from sales.models import Transaction
        from django.db.models import Sum

        today = timezone.now().date()
        revenue = Transaction.objects.filter(
            store=self,
            status='completed',
            created_at__date=today
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        return revenue


class StoreEmployee(models.Model):
    """
    Связь между магазином и сотрудниками
    """
    ROLE_CHOICES = [
        ('owner', _('Владелец')),
        ('admin', _('Администратор')),
        ('manager', _('Менеджер')),
        ('cashier', _('Кассир')),
        ('stockkeeper', _('Кладовщик')),
    ]

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='store_employees',
        verbose_name=_("Магазин")
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='store_memberships',
        verbose_name=_("Пользователь")
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        verbose_name=_("Роль в магазине")
    )

    # Дополнительная информация
    joined_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    # Разрешения для роли
    can_manage_products = models.BooleanField(
        default=False,
        verbose_name=_("Может управлять товарами")
    )
    can_manage_sales = models.BooleanField(
        default=False,
        verbose_name=_("Может проводить продажи")
    )
    can_view_analytics = models.BooleanField(
        default=False,
        verbose_name=_("Может просматривать аналитику")
    )
    can_manage_employees = models.BooleanField(
        default=False,
        verbose_name=_("Может управлять сотрудниками")
    )

    class Meta:
        verbose_name = _("Сотрудник магазина")
        verbose_name_plural = _("Сотрудники магазина")
        unique_together = ('store', 'user')
        ordering = ['-joined_at']

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.store.name} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        """Автоматически устанавливаем разрешения на основе роли"""
        if self.role == 'owner':
            self.can_manage_products = True
            self.can_manage_sales = True
            self.can_view_analytics = True
            self.can_manage_employees = True
        elif self.role == 'admin':
            self.can_manage_products = True
            self.can_manage_sales = True
            self.can_view_analytics = True
            self.can_manage_employees = True
        elif self.role == 'manager':
            self.can_manage_products = True
            self.can_manage_sales = True
            self.can_view_analytics = True
            self.can_manage_employees = False
        elif self.role == 'cashier':
            self.can_manage_products = False
            self.can_manage_sales = True
            self.can_view_analytics = False
            self.can_manage_employees = False
        elif self.role == 'stockkeeper':
            self.can_manage_products = True
            self.can_manage_sales = False
            self.can_view_analytics = False
            self.can_manage_employees = False

        super().save(*args, **kwargs)
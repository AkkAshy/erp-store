from django.db import models
from django.core.validators import MinValueValidator
from django.db.models import Max
from django.utils import timezone
from stores.mixins import StoreOwnedModel, StoreOwnedManager

class Customer(StoreOwnedModel):
    full_name = models.CharField(max_length=255, null=True, blank=True, verbose_name="Полное имя")
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True, verbose_name="Телефон")
    email = models.EmailField(null=True, blank=True, verbose_name="Электронная почта")
    total_spent = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Всего потрачено")
    debt = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)], verbose_name="Долг")
    loyalty_points = models.PositiveIntegerField(default=0, verbose_name="Бонусные баллы")
    created_at = models.DateTimeField(auto_now_add=True)
    last_purchase_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Дата последней покупки"
    )
    objects = StoreOwnedManager()
    class Meta:
        verbose_name = "Покупатель"
        verbose_name_plural = "Покупатели"
        unique_together = ['store', 'phone']

    def __str__(self):
        return self.full_name or self.phone or self.email or "Анонимный покупатель"

    def add_debt(self, amount):
        self.debt += amount
        self.save(update_fields=['debt'])

    # @property
    # def last_purchase_date(self):
    #     """Возвращает дату последней завершённой покупки"""
    #     last_transaction = self.purchases.filter(
    #         status='completed'
    #     ).aggregate(
    #         last_date=Max('created_at')
    #     )
    #     return last_transaction['last_date']

    @property
    def purchase_count(self):
        """Количество завершённых покупок"""
        return self.purchases.filter(status='completed').count()

    @property
    def avg_check(self):
        """Средний чек"""
        from django.db.models import Avg
        result = self.purchases.filter(status='completed').aggregate(Avg('total_amount'))
        return result['total_amount__avg'] or 0


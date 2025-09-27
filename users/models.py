# auth/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import Group

class Employee(models.Model):
    ROLE_CHOICES = (
        ('admin', _('Админ')),
        ('stockkeeper', _('Складчик')),
        ('manager', _('Менеджер')),
        ('cashier', _('Кассир')),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='cashier')
    phone = models.CharField(max_length=20, blank=True, null=True)
    photo = models.ImageField(upload_to='employee_photos/', blank=True, null=True)
    sex = models.CharField(max_length=10, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    plain_password = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        verbose_name="Пароль",
        help_text="Пароль в открытом виде (только для администраторов)"
    )

    # ✅ ПРАВИЛЬНАЯ СВЯЗЬ С UUID Store
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='employees',
        verbose_name=_('Магазин'),
        null=True,    # Временно разрешаем NULL для безопасной миграции
        blank=True,
        help_text=_('Магазин, к которому привязан сотрудник')
    )

    # ✅ Many-to-Many для доступа к нескольким магазинам
    accessible_stores = models.ManyToManyField(
        'stores.Store',
        related_name='accessible_employees',
        blank=True,
        null=True,
        verbose_name=_('Доступные магазины'),
        help_text=_('Магазины, к которым сотрудник имеет доступ')
    )

    class Meta:
        verbose_name = _('Сотрудник')
        verbose_name_plural = _('Сотрудники')

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.role}) - {self.store.name if self.store else 'Без магазина'}"

    def get_current_store(self):
        """Получить основной магазин сотрудника"""
        return self.store

    def has_access_to_store(self, store):
        """Проверить, имеет ли сотрудник доступ к магазину"""
        if self.role == 'admin':
            return True  # Админы имеют доступ ко всем магазинам
        return self.store == store or self.accessible_stores.filter(id=store.id).exists()

@receiver(post_save, sender=Employee)
def assign_group_to_user(sender, instance, created, **kwargs):
    # Получаем или создаём группу, соответствующую роли
    group, _ = Group.objects.get_or_create(name=instance.role)
    # Удаляем пользователя из всех других групп
    instance.user.groups.clear()
    # Добавляем пользователя в группу, соответствующую его роли
    instance.user.groups.add(group)
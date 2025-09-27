from django.db import models

class SMS_Template(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="Название шаблона")
    content = models.TextField(
        help_text="Содержимое SMS-шаблона. Доступные переменные: @ - имя покупателя, $ - сумма долга"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SMS Шаблон"
        verbose_name_plural = "SMS Шаблоны"
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def preview_for_customer(self, customer):
        """
        Показывает превью шаблона с подставленными данными конкретного клиента
        """
        content = self.content
        customer_name = customer.full_name or "Уважаемый покупатель"
        debt_amount = str(customer.debt)

        preview = content.replace("@", customer_name).replace("$", debt_amount)
        return preview
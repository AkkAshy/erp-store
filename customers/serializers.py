from rest_framework import serializers
from .models import Customer
from django.utils.translation import gettext_lazy as _
from drf_yasg.utils import swagger_serializer_method
from drf_yasg import openapi
from django.core.validators import MinValueValidator


class CustomerSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField(
        help_text="Полное имя клиента или 'Анонимный покупатель' если имя не указано"
    )
    last_purchase_date = serializers.SerializerMethodField()
    purchase_count = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ['id', 'full_name', 'phone', 'debt', 'created_at', 'last_purchase_date', 'total_spent',
            'purchase_count']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'phone': {
                'help_text': "Номер телефона в международном формате",
                'required': True
            },
            'debt': {
                'help_text': "Сумма задолженности клиента",
                'validators': [MinValueValidator(0)],
            }
        }
        swagger_schema_fields = {
            'type': 'object',
            'properties': {
                'id': {
                    'type': 'integer',
                    'readOnly': True,
                    'example': 1
                },
                'full_name': {
                    'type': 'string',
                    'example': 'Иван Иванов'
                },
                'phone': {
                    'type': 'string',
                    'example': '+71234567890'
                },
                'debt': {
                    'type': 'number',
                    'format': 'decimal',
                    'example': 150.50
                },
                'created_at': {
                    'type': 'string',
                    'format': 'date-time',
                    'readOnly': True,
                    'example': '2023-05-15T14:30:00Z'
                }
            },
            'required': ['phone']
        }

    @swagger_serializer_method(serializer_or_field=serializers.CharField(help_text="Форматированное полное имя клиента"))
    def get_full_name(self, obj):
        return obj.full_name or _("Анонимный покупатель")

    def validate_phone(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(_("Номер телефона не может быть пустым"))

        # Простая валидация формата номера
        if not value.startswith('+'):
            raise serializers.ValidationError(_("Номер должен начинаться с '+'"))

        if len(value) < 10:
            raise serializers.ValidationError(_("Слишком короткий номер телефона"))

        return value

    def validate_debt(self, value):
        if value < 0:
            raise serializers.ValidationError(_("Задолженность не может быть отрицательной"))
        return round(value, 2)

    def get_last_purchase_date(self, obj):
        date = getattr(obj, 'annotated_last_purchase_date', None)
        return date.isoformat() if date else None

    def get_purchase_count(self, obj):
        return obj.purchase_count
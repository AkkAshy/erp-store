from rest_framework import serializers
from .models import SMS_Template


class SmsSenderSerializer(serializers.ModelSerializer):
    available_variables = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = SMS_Template
        fields = [
            'id', 'name', 'content', 'created_at', 'updated_at', 'available_variables'
        ]
        read_only_fields = ['created_at', 'updated_at', 'available_variables']

    def get_available_variables(self, obj):
        return {
            "@": "Имя покупателя (или 'Уважаемый покупатель' если не указано)",
            "$": "Сумма долга покупателя"
        }

    def validate_content(self, value):
        """
        Проверяем, что контент не пустой и содержит осмысленный текст
        """
        if not value or not value.strip():
            raise serializers.ValidationError("Содержимое шаблона не может быть пустым")

        if len(value.strip()) < 5:
            raise serializers.ValidationError("Содержимое шаблона слишком короткое")

        return value.strip()




class SendSmsSerializer(serializers.Serializer):
    phone = serializers.CharField(
        required=False,
        help_text="Номер телефона получателя (если не указан, используется customer_ids или все клиенты)"
    )
    customer_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Список ID клиентов для отправки SMS",
        allow_empty=True
    )
    text = serializers.CharField(
        required=False,
        help_text="Текст сообщения (если не указан, используется шаблон)"
    )
    template_id = serializers.IntegerField(
        required=False,
        help_text="ID шаблона для использования"
    )

    def validate(self, data):
        if not data.get('text') and not data.get('template_id'):
            raise serializers.ValidationError(
                "Необходимо указать либо текст сообщения, либо ID шаблона"
            )
        if data.get('phone') and data.get('customer_ids'):
            raise serializers.ValidationError(
                "Нельзя указывать одновременно phone и customer_ids"
            )
        # УБИРАЕМ ЭТУ ПРОВЕРКУ для массовой рассылки:
        # if not data.get('phone') and not data.get('customer_ids'):
        #     raise serializers.ValidationError(
        #         "Необходимо указать либо phone, либо customer_ids"
        #     )
        return data
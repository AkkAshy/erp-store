import requests
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from .models import SMS_Template
from .serializators import SmsSenderSerializer  # Убираем несуществующий SendSmsSerializer
from rest_framework.views import APIView
from .models import SMS_Template as SmsTemplate
from customers.models import Customer as UserProfile
from django.conf import settings
from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from rest_framework.exceptions import APIException
import logging
from rest_framework import serializers

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

logger = logging.getLogger('sompos')

class SmsSenderViewSet(viewsets.ModelViewSet):
    queryset = SMS_Template.objects.all()
    serializer_class = SmsSenderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


# ИСПРАВЛЕНО: Обновленные учетные данные и URL
BASE_URL = "https://notify.eskiz.uz/api"
ESKIZ_EMAIL = "asirepovakkanat@gmail.com"
ESKIZ_PASSWORD = "t3sblMZoZDnC5L5Yqx2eZvIeRA6a6FvoP20Gah0F"

# Храним токен и время его жизни в памяти
_eskiz_token = None
_eskiz_token_expire = None

def get_eskiz_token():
    global _eskiz_token, _eskiz_token_expire

    # Проверяем, живой ли токен
    if _eskiz_token and _eskiz_token_expire and datetime.utcnow() < _eskiz_token_expire:
        logger.debug("Using cached Eskiz token")
        return _eskiz_token

    # Если токена нет или refresh не сработал, делаем login
    try:
        # ИСПРАВЛЕНО: Используем data вместо json для совместимости
        response = requests.post(
            f"{BASE_URL}/auth/login",
            data={  # Изменено с json на data
                "email": ESKIZ_EMAIL,
                "password": ESKIZ_PASSWORD
            },
            timeout=30  # Добавляем таймаут
        )

        logger.debug(f"Eskiz login response status: {response.status_code}")
        logger.debug(f"Eskiz login response: {response.text}")

        if response.status_code != 200:
            logger.error(f"Eskiz login failed with status {response.status_code}: {response.text}")
            raise APIException(f"Eskiz API returned {response.status_code}: {response.text}")

        data = response.json()

        # ИСПРАВЛЕНО: Более надежная проверка структуры ответа
        if "data" not in data or "token" not in data["data"]:
            logger.error(f"Eskiz login response missing token: {data}")
            raise APIException("Failed to retrieve token from Eskiz API")

        token = data["data"]["token"]
        _eskiz_token = token
        _eskiz_token_expire = datetime.utcnow() + timedelta(hours=23)

        logger.info("Eskiz token retrieved successfully")
        return _eskiz_token

    except requests.HTTPError as e:
        logger.error(f"Eskiz auth HTTP error: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response content: {e.response.text}")
        raise APIException(f"Eskiz API authentication failed: {str(e)}")
    except requests.RequestException as e:
        logger.error(f"Eskiz auth network error: {str(e)}")
        raise APIException(f"Network error while connecting to Eskiz API: {str(e)}")
    except ValueError as e:
        logger.error(f"Eskiz auth JSON decode error: {str(e)}")
        raise APIException("Invalid response from Eskiz API")
    except Exception as e:
        logger.error(f"Unexpected error in get_eskiz_token: {str(e)}")
        raise APIException(f"Unexpected error: {str(e)}")


def replace_template_variables(text, customer):
    """
    Заменяет переменные в тексте шаблона:
    @ - имя покупателя
    $ - сумма долга покупателя
    """
    if not text:
        return text

    # Получаем имя покупателя
    customer_name = customer.full_name or "Уважаемый покупатель"

    # Получаем долг покупателя
    debt_amount = str(customer.debt)

    # Заменяем переменные
    text = text.replace("@", customer_name)
    text = text.replace("$", debt_amount)

    return text


# ДОБАВЛЕНО: Создаем отсутствующий сериализатор
class SendSmsSerializer(serializers.Serializer):
    phone = serializers.CharField(required=False, help_text="Номер телефона одного получателя")
    customer_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Список ID клиентов"
    )
    text = serializers.CharField(required=False, help_text="Текст сообщения")
    template_id = serializers.IntegerField(required=False, help_text="ID шаблона")

    def validate(self, data):
        phone = data.get('phone')
        customer_ids = data.get('customer_ids')
        text = data.get('text')
        template_id = data.get('template_id')

        # Проверяем что указан либо phone, либо customer_ids
        if not phone and not customer_ids:
            # Если ничего не указано, отправляем всем
            pass

        # Проверяем что указан либо text, либо template_id
        if not text and not template_id:
            raise serializers.ValidationError("Укажите либо 'text', либо 'template_id'")

        return data


class SendSmsFlexibleView(APIView):
    def post(self, request, template_id=None):
        data_to_validate = request.data.copy()
        if template_id:
            data_to_validate['template_id'] = template_id

        serializer = SendSmsSerializer(data=data_to_validate)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data.get("phone")
        customer_ids = serializer.validated_data.get("customer_ids")
        text_message = serializer.validated_data.get("text")

        # Если текста нет — пробуем взять из шаблона
        template = None
        if not text_message and template_id:
            try:
                template = SmsTemplate.objects.get(id=template_id)
                text_message = template.content
            except SmsTemplate.DoesNotExist:
                return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)

        if not text_message:
            return Response({"error": "Text message is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Определяем получателей
        if phone:
            try:
                customer = UserProfile.objects.get(phone=phone)
                recipients = [customer]
            except UserProfile.DoesNotExist:
                return Response({"error": f"Customer with phone {phone} not found"}, status=status.HTTP_404_NOT_FOUND)
        elif customer_ids:
            recipients = UserProfile.objects.filter(id__in=customer_ids, phone__isnull=False).exclude(phone="")
            if not recipients:
                return Response({"error": "No valid customers found for the provided customer_ids"}, status=status.HTTP_404_NOT_FOUND)
        else:
            recipients = UserProfile.objects.filter(phone__isnull=False).exclude(phone="")
            if not recipients:
                return Response({"error": "No recipients found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            token = get_eskiz_token()
        except APIException as e:
            return Response({"error": f"Failed to get Eskiz token: {str(e)}"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        headers = {"Authorization": f"Bearer {token}"}

        results = []
        for customer in recipients:
            personalized_message = replace_template_variables(text_message, customer)

            # ИСПРАВЛЕНО: Правильная структура данных для отправки
            payload = {
                "mobile_phone": str(customer.phone).replace("+", "").strip(),
                "message": personalized_message,
                "from": "4546",  # Или ваш зарегистрированный отправитель
                "callback_url": "",
                "unicode": "1"  # Для поддержки кириллицы
            }

            try:
                # ИСПРАВЛЕНО: Используем правильный endpoint
                response = requests.post(
                    f"{BASE_URL}/message/sms/send",
                    headers=headers,
                    data=payload,
                    timeout=30
                )

                logger.debug(f"SMS send response for {customer.phone}: {response.status_code} - {response.text}")

                try:
                    resp_json = response.json()
                except Exception:
                    resp_json = {"error": "Invalid JSON from Eskiz", "raw": response.text}

                results.append({
                    "phone": customer.phone,
                    "customer_name": customer.full_name or "Не указано",
                    "personalized_message": personalized_message,
                    "status_code": response.status_code,
                    "response": resp_json
                })

            except requests.RequestException as e:
                logger.error(f"SMS send error for {customer.phone}: {str(e)}")
                results.append({
                    "phone": customer.phone,
                    "customer_name": customer.full_name or "Не указано",
                    "personalized_message": personalized_message,
                    "status_code": 0,
                    "response": {"error": f"Network error: {str(e)}"}
                })

        return Response({
            "status": "ok",
            "template_used": template.name if template else "Custom text",
            "total_sent": len(results),
            "results": results
        })


class TemplatePreviewView(APIView):
    """
    Предварительный просмотр шаблона с подставленными переменными
    """
    def get(self, request, template_id):
        try:
            template = SmsTemplate.objects.get(id=template_id)
        except SmsTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=status.HTTP_404_NOT_FOUND)

        # Получаем ID клиента из параметров запроса (опционально)
        customer_id = request.query_params.get('customer_id')

        if customer_id:
            try:
                customer = UserProfile.objects.get(id=customer_id)
            except UserProfile.DoesNotExist:
                return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            # Используем первого доступного клиента для примера
            customer = UserProfile.objects.first()
            if not customer:
                return Response({"error": "No customers found for preview"}, status=status.HTTP_404_NOT_FOUND)

        # Генерируем превью
        original_content = template.content
        preview_content = replace_template_variables(original_content, customer)

        return Response({
            "template_id": template.id,
            "template_name": template.name,
            "original_content": original_content,
            "preview_content": preview_content,
            "customer_used": {
                "id": customer.id,
                "name": customer.full_name or "Не указано",
                "phone": customer.phone,
                "debt": str(customer.debt)
            },
            "available_variables": {
                "@": "имя покупателя",
                "$": "сумма долга"
            }
        })


# ДОБАВЛЕНО: View для тестирования токена
class TestEskizTokenView(APIView):
    """
    Тестирование получения токена от Eskiz
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            token = get_eskiz_token()
            return Response({
                "status": "success",
                "token_preview": f"{token[:20]}..." if token else "None",
                "token_expires": _eskiz_token_expire.isoformat() if _eskiz_token_expire else None
            })
        except Exception as e:
            return Response({
                "status": "error",
                "error": str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
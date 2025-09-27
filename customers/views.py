# customers/views.py - РАСШИРЕННАЯ ВЕРСИЯ с дополнительными методами

from rest_framework import viewsets, pagination, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Q, Max, Sum, Count
from django.utils.dateparse import parse_date
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .serializers import CustomerSerializer
from .models import Customer
from stores.mixins import StoreViewSetMixin

class FlexiblePagination(pagination.PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 1000

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request

        # 👉 если ни page, ни limit/offset нет — вернуть все данные
        if not request.query_params.get("page") and not request.query_params.get("limit") and not request.query_params.get("offset"):
            self.all_data = True
            self.queryset = list(queryset)
            return self.queryset

        # 👉 режим "все данные" по ?page=all
        if request.query_params.get("page") == "all":
            self.all_data = True
            self.queryset = list(queryset)
            return self.queryset

        # 👉 режим offset/limit
        limit = request.query_params.get("limit")
        offset = request.query_params.get("offset")
        if limit is not None:
            try:
                limit = int(limit)
                offset = int(offset or 0)
                self.all_data = False
                self.queryset = queryset[offset:offset + limit]
                self.count = queryset.count()
                return list(self.queryset)
            except ValueError:
                pass

        # 👉 fallback — обычная пагинация по страницам
        self.all_data = False
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        if getattr(self, "all_data", False):
            return Response({
                "count": len(data),
                "next": None,
                "previous": None,
                "results": data
            })

        if self.request.query_params.get("limit") is not None:
            next_offset = None
            offset = int(self.request.query_params.get("offset", 0))
            limit = int(self.request.query_params.get("limit", 0))
            if self.count > (offset + len(data)):
                next_offset = offset + len(data)
            prev_offset = offset - limit if offset > 0 else None
            if prev_offset is not None and prev_offset < 0:
                prev_offset = 0

            return Response({
                "count": self.count,
                "next": f"?limit={limit}&offset={next_offset}" if next_offset is not None else None,
                "previous": f"?limit={limit}&offset={prev_offset}" if prev_offset is not None else None,
                "results": data
            })

        return super().get_paginated_response(data)


class CustomerViewSet(StoreViewSetMixin, viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    pagination_class = FlexiblePagination
    queryset = Customer.objects.all()  # ← ДОБАВЛЯЕМ базовый queryset

    def get_queryset(self):
        """
        ✅ Получаем клиентов ТОЛЬКО текущего магазина
        """
        # Базовый queryset с фильтрацией по магазину из StoreViewSetMixin
        queryset = super().get_queryset()

        # Добавляем аннотации для дополнительной информации
        queryset = queryset.annotate(
            annotated_last_purchase_date=Max(
                'purchases__created_at',
                filter=Q(purchases__status='completed')
            )
        )

        # Применяем фильтры из параметров запроса
        request = self.request
        query = request.query_params.get('q', '').strip()
        date_from_str = request.query_params.get('date_from')
        date_to_str = request.query_params.get('date_to')
        has_debt = request.query_params.get('has_debt')
        min_debt = request.query_params.get('min_debt')

        date_from = parse_date(date_from_str) if date_from_str else None
        date_to = parse_date(date_to_str) if date_to_str else None

        filters = Q()

        # Поиск по имени/телефону/email
        if query:
            name_parts = [word.capitalize() for word in query.split()]
            for part in name_parts:
                filters |= Q(full_name__icontains=part)

            phone_query = query.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
            if phone_query.isdigit() or len(phone_query) >= 3:
                filters |= Q(phone__icontains=phone_query)

            if '@' in query or not phone_query.isdigit():
                filters |= Q(email__icontains=query)

            queryset = queryset.filter(filters)

        # Фильтр по дате последней покупки
        if date_from:
            queryset = queryset.filter(annotated_last_purchase_date__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(annotated_last_purchase_date__date__lte=date_to)

        # Фильтр по наличию долга
        if has_debt == 'true':
            queryset = queryset.filter(debt__gt=0)
        elif has_debt == 'false':
            queryset = queryset.filter(debt=0)

        # Фильтр по минимальной сумме долга
        if min_debt:
            try:
                min_debt_value = float(min_debt)
                queryset = queryset.filter(debt__gte=min_debt_value)
            except ValueError:
                pass

        return queryset.distinct()

    @swagger_auto_schema(
        operation_description="Получить клиентов текущего магазина с фильтрацией",
        manual_parameters=[
            openapi.Parameter(
                'q', openapi.IN_QUERY,
                description="Поиск по имени, телефону или email",
                type=openapi.TYPE_STRING
            ),
            openapi.Parameter(
                'has_debt', openapi.IN_QUERY,
                description="Фильтр по наличию долга (true/false)",
                type=openapi.TYPE_STRING,
                enum=['true', 'false']
            ),
            openapi.Parameter(
                'min_debt', openapi.IN_QUERY,
                description="Минимальная сумма долга",
                type=openapi.TYPE_NUMBER
            ),
            openapi.Parameter(
                'date_from', openapi.IN_QUERY,
                description="Дата последней покупки от (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format='date'
            ),
            openapi.Parameter(
                'date_to', openapi.IN_QUERY,
                description="Дата последней покупки до (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format='date'
            ),
            openapi.Parameter(
                'page', openapi.IN_QUERY,
                description="Номер страницы или 'all' для всех записей",
                type=openapi.TYPE_STRING
            ),
            openapi.Parameter(
                'limit', openapi.IN_QUERY,
                description="Количество записей (для offset/limit пагинации)",
                type=openapi.TYPE_INTEGER
            ),
            openapi.Parameter(
                'offset', openapi.IN_QUERY,
                description="Смещение записей (для offset/limit пагинации)",
                type=openapi.TYPE_INTEGER
            )
        ],
        responses={200: CustomerSerializer(many=True)}
    )
    def list(self, request, *args, **kwargs):
        """Получить список клиентов текущего магазина"""
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_description="Получить клиентов с долгами",
        manual_parameters=[
            openapi.Parameter(
                'min_debt', openapi.IN_QUERY,
                description="Минимальная сумма долга",
                type=openapi.TYPE_NUMBER,
                default=0.01
            ),
            openapi.Parameter(
                'limit', openapi.IN_QUERY,
                description="Количество записей",
                type=openapi.TYPE_INTEGER
            )
        ],
        responses={200: CustomerSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def with_debt(self, request):
        """Получить клиентов с долгами"""
        min_debt = float(request.query_params.get('min_debt', 0.01))
        limit = request.query_params.get('limit')

        queryset = self.get_queryset().filter(debt__gte=min_debt).order_by('-debt')

        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'customers': serializer.data,
            'count': queryset.count() if not limit else len(serializer.data),
            'total_debt': sum(customer['debt'] for customer in serializer.data),
            'message': f'Клиенты с долгом от {min_debt} сум'
        })

    @swagger_auto_schema(
        operation_description="Получить статистику по клиентам магазина",
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'total_customers': openapi.Schema(type=openapi.TYPE_INTEGER),
                    'customers_with_debt': openapi.Schema(type=openapi.TYPE_INTEGER),
                    'total_debt': openapi.Schema(type=openapi.TYPE_NUMBER),
                    'average_debt': openapi.Schema(type=openapi.TYPE_NUMBER),
                    'customers_with_purchases': openapi.Schema(type=openapi.TYPE_INTEGER)
                }
            )
        }
    )
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Статистика по клиентам магазина"""
        queryset = self.get_queryset()

        # Основная статистика
        stats = queryset.aggregate(
            total_customers=Count('id'),
            customers_with_debt=Count('id', filter=Q(debt__gt=0)),
            total_debt=Sum('debt'),
            average_debt=models.Avg('debt')
        )

        # Клиенты с покупками
        customers_with_purchases = queryset.filter(
            purchases__status='completed'
        ).distinct().count()

        # Топ должники
        top_debtors = queryset.filter(debt__gt=0).order_by('-debt')[:5]
        top_debtors_data = CustomerSerializer(top_debtors, many=True).data

        # Получаем информацию о текущем магазине
        store_info = None
        if hasattr(request.user, 'current_store') and request.user.current_store:
            store_info = {
                'id': str(request.user.current_store.id),
                'name': request.user.current_store.name
            }

        return Response({
            'store': store_info,
            'statistics': {
                'total_customers': stats['total_customers'] or 0,
                'customers_with_debt': stats['customers_with_debt'] or 0,
                'customers_with_purchases': customers_with_purchases,
                'total_debt': float(stats['total_debt'] or 0),
                'average_debt': float(stats['average_debt'] or 0),
            },
            'top_debtors': top_debtors_data
        })

    @swagger_auto_schema(
        operation_description="Поиск клиентов по номеру телефона",
        manual_parameters=[
            openapi.Parameter(
                'phone', openapi.IN_QUERY,
                description="Номер телефона (полный или частичный)",
                type=openapi.TYPE_STRING,
                required=True
            )
        ],
        responses={200: CustomerSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def search_by_phone(self, request):
        """Поиск клиентов по телефону"""
        phone = request.query_params.get('phone', '').strip()

        if not phone:
            return Response({
                'error': 'Параметр phone обязателен'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Очищаем номер от символов
        clean_phone = phone.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', '')

        queryset = self.get_queryset().filter(
            Q(phone__icontains=clean_phone) | Q(phone__icontains=phone)
        )

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'customers': serializer.data,
            'count': queryset.count(),
            'search_query': phone
        })

    @swagger_auto_schema(
        operation_description="Получить недавно активных клиентов",
        manual_parameters=[
            openapi.Parameter(
                'days', openapi.IN_QUERY,
                description="Количество дней (по умолчанию 30)",
                type=openapi.TYPE_INTEGER,
                default=30
            ),
            openapi.Parameter(
                'limit', openapi.IN_QUERY,
                description="Максимальное количество клиентов",
                type=openapi.TYPE_INTEGER,
                default=20
            )
        ],
        responses={200: CustomerSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def recent_active(self, request):
        """Получить недавно активных клиентов"""
        from datetime import datetime, timedelta

        days = int(request.query_params.get('days', 30))
        limit = int(request.query_params.get('limit', 20))

        since_date = datetime.now().date() - timedelta(days=days)

        queryset = self.get_queryset().filter(
            purchases__created_at__date__gte=since_date,
            purchases__status='completed'
        ).distinct().order_by('-purchases__created_at')[:limit]

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'customers': serializer.data,
            'count': len(serializer.data),
            'period_days': days,
            'since_date': since_date
        })
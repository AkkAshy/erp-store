# stores/views.py (ИСПРАВЛЕННАЯ ВЕРСИЯ)
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User, Group
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework_simplejwt.tokens import RefreshToken
import logging

from .models import Store, StoreEmployee
from .serializers import (
    StoreSerializer, StoreCreateSerializer,
    StoreEmployeeSerializer, StoreSwitchSerializer
)
from .tokens import get_tokens_for_user_and_store
from users.serializers import UserSerializer

from inventory.models import Product
from customers.models import Customer

from sales.models import Transaction


logger = logging.getLogger(__name__)

# ✅ ДОБАВЛЯЕМ простые функции
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
import json


class DebugStoreAccessView(APIView):
    """
    Отладочный эндпоинт для проверки доступа к магазинам
    GET /api/stores/debug-access/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        debug_info = {
            'user_info': {
                'id': user.id,
                'username': user.username,
                'groups': list(user.groups.values_list('name', flat=True)),
                'is_superuser': user.is_superuser,
            },
            'middleware_attributes': {
                'has_current_store': hasattr(user, 'current_store'),
                'current_store_id': str(user.current_store.id) if hasattr(user, 'current_store') and user.current_store else None,
                'current_store_name': user.current_store.name if hasattr(user, 'current_store') and user.current_store else None,
                'store_role': getattr(user, 'store_role', None),
            },
            'accessible_stores': [],
            'data_counts': {},
            'potential_issues': []
        }

        # Получаем доступные магазины через StoreEmployee
        memberships = StoreEmployee.objects.filter(user=user, is_active=True).select_related('store')
        for membership in memberships:
            debug_info['accessible_stores'].append({
                'id': str(membership.store.id),
                'name': membership.store.name,
                'role': membership.role,
                'is_current': hasattr(user, 'current_store') and user.current_store and str(membership.store.id) == str(user.current_store.id)
            })

        # Проверяем доступ к данным
        debug_info['data_counts'] = {
            'all_products': Product.objects.count(),
            'all_customers': Customer.objects.count(),
            'all_transactions': Transaction.objects.count(),
        }

        # Если есть текущий магазин
        current_store = getattr(user, 'current_store', None)
        if current_store:
            debug_info['data_counts'].update({
                'current_store_products': Product.objects.filter(store=current_store).count(),
                'current_store_customers': Customer.objects.filter(store=current_store).count(),
                'current_store_transactions': Transaction.objects.filter(store=current_store).count(),
            })

            # Проверяем товары в других магазинах
            other_stores = Store.objects.exclude(id=current_store.id)
            other_stores_data = []
            for other_store in other_stores:
                other_products = Product.objects.filter(store=other_store)
                other_customers = Customer.objects.filter(store=other_store)
                other_transactions = Transaction.objects.filter(store=other_store)

                other_stores_data.append({
                    'store_id': str(other_store.id),
                    'store_name': other_store.name,
                    'products_count': other_products.count(),
                    'customers_count': other_customers.count(),
                    'transactions_count': other_transactions.count(),
                    'sample_products': [
                        {'id': p.id, 'name': p.name}
                        for p in other_products[:3]
                    ] if other_products.exists() else []
                })

                # Если видит товары других магазинов - это проблема
                if other_products.count() > 0:
                    debug_info['potential_issues'].append(
                        f"МОЖЕТ ВИДЕТЬ {other_products.count()} товаров из магазина '{other_store.name}'"
                    )

            debug_info['other_stores_data'] = other_stores_data

        # JWT токен информация
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            try:
                from rest_framework_simplejwt.tokens import AccessToken
                token = auth_header.split(' ')[1]
                decoded_token = AccessToken(token)

                debug_info['jwt_token_info'] = {
                    'store_id': decoded_token.get('store_id'),
                    'store_name': decoded_token.get('store_name'),
                    'store_role': decoded_token.get('store_role'),
                    'user_id': decoded_token.get('user_id'),
                }

                # Проверяем соответствие JWT и middleware
                jwt_store_id = decoded_token.get('store_id')
                middleware_store_id = debug_info['middleware_attributes']['current_store_id']

                if jwt_store_id != middleware_store_id:
                    debug_info['potential_issues'].append(
                        f"JWT store_id ({jwt_store_id}) != middleware store_id ({middleware_store_id})"
                    )

            except Exception as e:
                debug_info['jwt_token_info'] = {'error': str(e)}

        return Response(debug_info)


@csrf_exempt
@require_http_methods(["POST"])
def simple_store_register(request):
    """
    ПРОСТАЯ регистрация магазина без DRF
    """
    logger.info("Simple store registration started")

    try:
        # Парсим JSON
        data = json.loads(request.body.decode('utf-8'))
        logger.info(f"Registration data received: {list(data.keys())}")

        # Базовая валидация
        required_fields = ['username', 'password', 'email', 'store_name', 'store_address']
        missing_fields = [field for field in required_fields if not data.get(field)]

        if missing_fields:
            return JsonResponse({
                'error': f'Отсутствуют обязательные поля: {", ".join(missing_fields)}'
            }, status=400)

        # Проверяем существование пользователя
        if User.objects.filter(username=data['username']).exists():
            return JsonResponse({
                'error': 'Пользователь с таким именем уже существует'
            }, status=400)

        if User.objects.filter(email=data['email']).exists():
            return JsonResponse({
                'error': 'Пользователь с таким email уже существует'
            }, status=400)

        # Проверяем существование магазина
        if Store.objects.filter(name__iexact=data['store_name']).exists():
            return JsonResponse({
                'error': 'Магазин с таким названием уже существует'
            }, status=400)

        with transaction.atomic():
            # 1. Создаем пользователя
            user = User.objects.create_user(
                username=data['username'],
                email=data['email'],
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
                password=data['password']
            )
            logger.info(f"User created: {user.username}")

            # 2. Добавляем в группу admin
            admin_group, created = Group.objects.get_or_create(name='admin')
            user.groups.add(admin_group)

            # 3. Создаем магазин
            store = Store.objects.create(
                name=data['store_name'],
                address=data['store_address'],
                phone=data.get('store_phone', ''),
                email=data.get('store_email', ''),
                description=data.get('store_description', ''),
                owner=user
            )
            logger.info(f"Store created: {store.name}")

            # 4. Создаем Employee и привязываем к store
            try:
                from users.models import Employee
                Employee.objects.create(
                    user=user,
                    role='owner',  # лучше "owner", раз это создатель магазина
                    phone=data.get('phone', ''),
                    store=store
                )
                logger.info(f"Employee record created for {user.username} in {store.name}")
            except ImportError:
                logger.warning("Employee model not found, skipping")
            except Exception as e:
                logger.error(f"Error creating Employee: {e}")

            # 5. Создаем связь StoreEmployee
            store_employee = StoreEmployee.objects.create(
                store=store,
                user=user,
                role='owner'
            )
            logger.info(f"StoreEmployee created: {user.username} -> {store.name}")

            # 6. Генерируем токены
            tokens = get_tokens_for_user_and_store(user, str(store.id))

            response_data = {
                'success': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                },
                'store': {
                    'id': str(store.id),
                    'name': store.name,
                    'address': store.address,
                    'phone': store.phone,
                    'email': store.email,
                },
                'tokens': {
                    'refresh': tokens['refresh'],
                    'access': tokens['access'],
                    'store_id': tokens.get('store_id'),
                    'store_name': tokens.get('store_name'),
                },
                'role': store_employee.role,
                'message': 'Регистрация успешно завершена'
            }

            logger.info(f"Registration completed successfully for {user.username}")
            return JsonResponse(response_data, status=201)


    except json.JSONDecodeError:
        return JsonResponse({'error': 'Неверный формат JSON'}, status=400)
    except Exception as e:
        logger.error(f"Registration error: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': 'Внутренняя ошибка сервера',
            'details': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def simple_refresh_token(request):
    """Простое обновление токена без DRF"""
    try:
        data = json.loads(request.body.decode('utf-8'))
        refresh_token = data.get('refresh')
        store_id = data.get('store_id')

        if not refresh_token:
            return JsonResponse({'error': 'refresh token обязателен'}, status=400)

        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken(refresh_token)
        user_id = refresh.payload.get('user_id')

        user = User.objects.get(id=user_id)

        if store_id:
            has_access = StoreEmployee.objects.filter(
                user=user,
                store_id=store_id,
                is_active=True
            ).exists()

            if not has_access:
                return JsonResponse(
                    {'error': 'У вас нет доступа к указанному магазину'},
                    status=403
                )
        else:
            store_id = refresh.payload.get('store_id')
            if not store_id:
                membership = StoreEmployee.objects.filter(
                    user=user,
                    is_active=True
                ).first()
                if membership:
                    store_id = str(membership.store.id)

        tokens = get_tokens_for_user_and_store(user, store_id)

        return JsonResponse({
            'access': tokens['access'],
            'refresh': tokens['refresh']
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


class StoreRegisterView(APIView):
    """
    ИСПРАВЛЕНО: Регистрация первого администратора и создание магазина
    """
    # ✅ УБИРАЕМ АУТЕНТИФИКАЦИЮ ПОЛНОСТЬЮ
    permission_classes = []  # Пустой список вместо [permissions.AllowAny]
    authentication_classes = []  # Отключаем все виды аутентификации

    @swagger_auto_schema(
        operation_description="Регистрация администратора и создание магазина (без аутентификации)",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['username', 'password', 'email', 'store_name', 'store_address'],
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING, example='admin'),
                'password': openapi.Schema(type=openapi.TYPE_STRING, example='secure123'),
                'email': openapi.Schema(type=openapi.TYPE_STRING, example='admin@store.com'),
                'first_name': openapi.Schema(type=openapi.TYPE_STRING, example='John'),
                'last_name': openapi.Schema(type=openapi.TYPE_STRING, example='Doe'),
                'phone': openapi.Schema(type=openapi.TYPE_STRING, example='+998901234567'),
                'store_name': openapi.Schema(type=openapi.TYPE_STRING, example='My Store'),
                'store_address': openapi.Schema(type=openapi.TYPE_STRING, example='123 Main St'),
                'store_phone': openapi.Schema(type=openapi.TYPE_STRING, example='+998901234568'),
                'store_email': openapi.Schema(type=openapi.TYPE_STRING, example='store@example.com'),
                'store_description': openapi.Schema(type=openapi.TYPE_STRING, example='My amazing store'),
            }
        ),
        responses={
            201: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'user': openapi.Schema(type=openapi.TYPE_OBJECT),
                    'store': openapi.Schema(type=openapi.TYPE_OBJECT),
                    'tokens': openapi.Schema(type=openapi.TYPE_OBJECT),
                    'message': openapi.Schema(type=openapi.TYPE_STRING)
                }
            ),
            400: 'Ошибка валидации'
        }
    )
    def post(self, request):
        logger.info("Store registration started")
        logger.debug(f"Request data: {request.data}")

        # Базовая валидация входных данных
        required_fields = ['username', 'password', 'email', 'store_name', 'store_address']
        missing_fields = [field for field in required_fields if not request.data.get(field)]

        if missing_fields:
            return Response(
                {'error': f'Отсутствуют обязательные поля: {", ".join(missing_fields)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            try:
                # Создаем пользователя
                user_data = {
                    'username': request.data.get('username'),
                    'email': request.data.get('email'),
                    'first_name': request.data.get('first_name', ''),
                    'last_name': request.data.get('last_name', ''),
                }

                # Проверяем существование пользователя
                if User.objects.filter(username=user_data['username']).exists():
                    return Response(
                        {'error': 'Пользователь с таким именем уже существует'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if User.objects.filter(email=user_data['email']).exists():
                    return Response(
                        {'error': 'Пользователь с таким email уже существует'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Создаем пользователя
                user = User.objects.create_user(
                    username=user_data['username'],
                    email=user_data['email'],
                    first_name=user_data['first_name'],
                    last_name=user_data['last_name'],
                    password=request.data.get('password')
                )

                logger.info(f"User created: {user.username}")

                # Добавляем в группу admin
                admin_group, created = Group.objects.get_or_create(name='admin')
                user.groups.add(admin_group)

                # Создаем Employee если модель существует
                try:
                    from users.models import Employee
                    Employee.objects.create(
                        user=user,
                        role='admin',
                        phone=request.data.get('phone', '')
                    )
                    logger.info(f"Employee record created for {user.username}")
                except ImportError:
                    logger.warning("Employee model not found, skipping")
                except Exception as e:
                    logger.error(f"Error creating Employee: {e}")

                # Создаем магазин
                store_data = {
                    'name': request.data.get('store_name'),
                    'address': request.data.get('store_address'),
                    'phone': request.data.get('store_phone', ''),
                    'email': request.data.get('store_email', ''),
                    'description': request.data.get('store_description', ''),
                }

                # Проверяем уникальность имени магазина
                if Store.objects.filter(name__iexact=store_data['name']).exists():
                    return Response(
                        {'error': 'Магазин с таким названием уже существует'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                store_serializer = StoreCreateSerializer(data=store_data)
                if store_serializer.is_valid():
                    store = store_serializer.save(owner=user)
                    logger.info(f"Store created: {store.name}")

                    # Создаем связь StoreEmployee
                    store_employee = StoreEmployee.objects.create(
                        store=store,
                        user=user,
                        role='owner'
                    )
                    logger.info(f"StoreEmployee created: {user.username} -> {store.name}")

                    # Генерируем токены с информацией о магазине
                    tokens = get_tokens_for_user_and_store(user, str(store.id))

                    response_data = {
                        'success': True,
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'email': user.email,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                        },
                        'store': {
                            'id': str(store.id),
                            'name': store.name,
                            'address': store.address,
                            'phone': store.phone,
                            'email': store.email,
                        },
                        'tokens': {
                            'refresh': tokens['refresh'],
                            'access': tokens['access'],
                            'store_id': tokens.get('store_id'),
                            'store_name': tokens.get('store_name'),
                        },
                        'role': store_employee.role,
                        'message': 'Регистрация успешно завершена'
                    }

                    logger.info(f"Registration completed successfully for {user.username}")
                    return Response(response_data, status=status.HTTP_201_CREATED)
                else:
                    logger.error(f"Store serializer errors: {store_serializer.errors}")
                    return Response(
                        {'error': 'Ошибка данных магазина', 'details': store_serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            except Exception as e:
                logger.error(f"Registration error: {str(e)}", exc_info=True)
                return Response(
                    {'error': 'Внутренняя ошибка сервера', 'details': str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )


# ✅ ИСПРАВЛЯЕМ остальные views тоже
class StoreViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления магазинами
    """
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Показываем только магазины, к которым у пользователя есть доступ"""
        user = self.request.user

        # Если суперпользователь - показываем все
        if user.is_superuser:
            return Store.objects.all()

        # Иначе только магазины, где пользователь является сотрудником
        store_ids = StoreEmployee.objects.filter(
            user=user,
            is_active=True
        ).values_list('store_id', flat=True)

        return Store.objects.filter(id__in=store_ids)

    def perform_create(self, serializer):
        """При создании магазина автоматически делаем создателя владельцем"""
        store = serializer.save(owner=self.request.user)

        # Создаем связь StoreEmployee
        StoreEmployee.objects.create(
            store=store,
            user=self.request.user,
            role='owner'
        )

    @action(detail=True, methods=['get', 'post'])
    def markup_settings(self, request, pk=None):
        """
        Получить или обновить настройки наценки магазина
        """
        store = self.get_object()
        
        # Проверяем права (только owner/admin)
        user_role = getattr(request.user, 'store_role', 'cashier')
        if user_role not in ['owner', 'admin']:
            return Response({
                'error': 'Недостаточно прав для изменения настроек наценки'
            }, status=403)

        if request.method == 'GET':
            # Возвращаем текущие настройки
            return Response({
                'store_id': str(store.id),
                'store_name': store.name,
                'min_markup_percent': float(store.min_markup_percent),
                'allow_sale_below_markup': store.allow_sale_below_markup,
                'products_count': Product.objects.filter(store=store).count()
            })

        elif request.method == 'POST':
            # Обновляем настройки
            min_markup_percent = request.data.get('min_markup_percent')
            allow_sale_below_markup = request.data.get('allow_sale_below_markup')

            if min_markup_percent is not None:
                try:
                    min_markup_percent = Decimal(str(min_markup_percent))
                    if min_markup_percent < 0 or min_markup_percent > 1000:
                        return Response({
                            'error': 'Наценка должна быть от 0% до 1000%'
                        }, status=400)
                    store.min_markup_percent = min_markup_percent
                except (ValueError, TypeError):
                    return Response({
                        'error': 'Некорректный формат наценки'
                    }, status=400)

            if allow_sale_below_markup is not None:
                if not isinstance(allow_sale_below_markup, bool):
                    return Response({
                        'error': 'allow_sale_below_markup должно быть true или false'
                    }, status=400)
                store.allow_sale_below_markup = allow_sale_below_markup

            store.save()

            logger.info(f"Markup settings updated for store {store.name} by {request.user.username}")

            return Response({
                'message': 'Настройки наценки обновлены',
                'store_id': str(store.id),
                'store_name': store.name,
                'min_markup_percent': float(store.min_markup_percent),
                'allow_sale_below_markup': store.allow_sale_below_markup
            })

    @action(detail=True, methods=['get'])
    def pricing_report(self, request, pk=None):
        """
        Отчет по ценообразованию в магазине
        """
        store = self.get_object()
        
        products = Product.objects.filter(store=store).select_related('store')
        
        # Анализ товаров
        pricing_analysis = []
        below_markup_count = 0
        no_purchase_price_count = 0
        
        for product in products:
            avg_purchase = product.average_purchase_price
            min_sale_price = product.min_sale_price
            
            if not avg_purchase:
                no_purchase_price_count += 1
                continue
                
            current_margin = ((product.sale_price - avg_purchase) / avg_purchase) * 100
            
            analysis = {
                'product_id': product.id,
                'product_name': product.name,
                'sale_price': float(product.sale_price),
                'min_sale_price': float(min_sale_price),
                'avg_purchase_price': float(avg_purchase),
                'current_margin': round(current_margin, 2),
                'meets_min_markup': current_margin >= float(store.min_markup_percent),
                'unit_display': product.unit_display
            }
            
            if not analysis['meets_min_markup']:
                below_markup_count += 1
                
            pricing_analysis.append(analysis)
        
        # Сортируем по марже (от меньшей к большей)
        pricing_analysis.sort(key=lambda x: x['current_margin'])
        
        # Статистика
        margins = [p['current_margin'] for p in pricing_analysis]
        
        summary = {
            'store_info': {
                'id': str(store.id),
                'name': store.name,
                'min_markup_percent': float(store.min_markup_percent),
                'allow_sale_below_markup': store.allow_sale_below_markup
            },
            'statistics': {
                'total_products': products.count(),
                'analyzed_products': len(pricing_analysis),
                'products_below_markup': below_markup_count,
                'products_without_purchase_price': no_purchase_price_count,
                'avg_margin': round(sum(margins) / len(margins), 2) if margins else 0,
                'min_margin': min(margins) if margins else 0,
                'max_margin': max(margins) if margins else 0
            },
            'products_below_markup': [p for p in pricing_analysis if not p['meets_min_markup']][:20],
            'recommendations': []
        }
        
        # Рекомендации
        if below_markup_count > 0:
            summary['recommendations'].append({
                'type': 'warning',
                'message': f'{below_markup_count} товаров продаются ниже минимальной наценки {store.min_markup_percent}%'
            })
        
        if no_purchase_price_count > 0:
            summary['recommendations'].append({
                'type': 'info',
                'message': f'{no_purchase_price_count} товаров не имеют закупочной цены'
            })
        
        return Response(summary)


class CreateUserForStoreView(APIView):
    """
    Создание пользователя с автоматической привязкой к текущему магазину
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logger.info(f"CreateUser request from user: {request.user.username}")

        # Получаем текущий магазин
        current_store = None
        store_role = None

        # Способ 1: Из JWT токена
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            try:
                from rest_framework_simplejwt.tokens import AccessToken
                token = auth_header.split(' ')[1]
                decoded_token = AccessToken(token)
                store_id = decoded_token.get('store_id')

                if store_id:
                    from stores.models import Store
                    current_store = Store.objects.get(id=store_id, is_active=True)
                    store_role = decoded_token.get('store_role')
                    logger.info(f"✅ Store from JWT: {current_store.name}")
            except Exception as e:
                logger.error(f"Failed to get store from JWT: {e}")

        # Способ 2: Из атрибутов пользователя (middleware)
        if not current_store and hasattr(request.user, 'current_store') and request.user.current_store:
            current_store = request.user.current_store
            store_role = getattr(request.user, 'store_role', 'unknown')
            logger.info(f"✅ Store from middleware: {current_store.name}")

        # Способ 3: Из StoreEmployee
        if not current_store:
            store_membership = StoreEmployee.objects.filter(
                user=request.user,
                is_active=True
            ).select_related('store').first()

            if store_membership:
                current_store = store_membership.store
                store_role = store_membership.role
                logger.info(f"✅ Store from StoreEmployee: {current_store.name}")
            else:
                return Response(
                    {'error': 'Пользователь не привязан к магазину'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Проверяем права
        if store_role not in ['owner', 'admin']:
            return Response(
                {'error': f'У вас нет прав для создания пользователей. Ваша роль: {store_role}'},
                status=status.HTTP_403_FORBIDDEN
            )

        with transaction.atomic():
            try:
                # Извлекаем данные
                username = request.data.get('username')
                email = request.data.get('email')
                password = request.data.get('password')
                first_name = request.data.get('first_name', '')
                last_name = request.data.get('last_name', '')
                phone = request.data.get('phone', '')
                sex = request.data.get('sex', '')
                role = request.data.get('store_role', 'cashier')

                # Валидация
                if not username or not email or not password:
                    return Response(
                        {'error': 'username, email и password обязательны'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if User.objects.filter(username=username).exists():
                    return Response(
                        {'error': 'Пользователь с таким именем уже существует'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Создаем пользователя
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name
                )
                logger.info(f"✅ User created: {user.username}")

                # Привязываем к магазину через StoreEmployee
                store_employee = StoreEmployee.objects.create(
                    store=current_store,
                    user=user,
                    role=role
                )
                logger.info(f"✅ StoreEmployee created: {user.username} -> {current_store.name} ({role})")

                # ✅ ИСПРАВЛЕНИЕ: Создаем Employee С ПРИВЯЗКОЙ К МАГАЗИНУ
                try:
                    from users.models import Employee
                    employee = Employee.objects.create(
                        user=user,
                        role=role,
                        phone=phone,
                        sex=sex,
                        plain_password=password,
                        store=current_store  # ← ВАЖНО: привязываем к магазину
                    )

                    # Добавляем магазин в доступные
                    employee.accessible_stores.add(current_store)
                    employee.save()

                    logger.info(f"✅ Employee record created with store: {current_store.name}")
                except ImportError:
                    logger.warning("Employee model not found")
                except Exception as e:
                    logger.error(f"Error creating Employee: {e}")

                # Добавляем в группу
                group, _ = Group.objects.get_or_create(name=role)
                user.groups.add(group)

                # Получаем созданного пользователя с полной информацией
                from users.serializers import UserSerializer
                user_serializer = UserSerializer(user, context={'request': request})

                return Response({
                    'success': True,
                    'user': user_serializer.data,
                    'store': {
                        'id': str(current_store.id),
                        'name': current_store.name
                    },
                    'role': role,
                    'password': password,  # Возвращаем пароль для администратора
                    'message': f'Пользователь {user.username} успешно создан'
                }, status=status.HTTP_201_CREATED)

            except Exception as e:
                logger.error(f"❌ Error creating user: {str(e)}", exc_info=True)
                return Response(
                    {'error': f'Ошибка создания пользователя: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

class SwitchStoreView(APIView):
    """
    Переключение на другой магазин с генерацией нового JWT токена
    """
    permission_classes = [permissions.IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Переключиться на другой магазин и получить новый токен",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['store_id'],
            properties={
                'store_id': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    format='uuid',
                    description='ID магазина для переключения'
                )
            }
        ),
        responses={
            200: 'Магазин переключен',
            403: 'Нет доступа к магазину',
            404: 'Магазин не найден'
        }
    )
    def post(self, request):
        store_id = request.data.get('store_id')

        if not store_id:
            return Response(
                {'error': 'store_id обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Проверяем, что пользователь имеет доступ к этому магазину
        try:
            store_membership = StoreEmployee.objects.get(
                user=request.user,
                store_id=store_id,
                is_active=True
            )
        except StoreEmployee.DoesNotExist:
            return Response(
                {'error': 'У вас нет доступа к этому магазину'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Генерируем новые токены с новым магазином
        tokens = get_tokens_for_user_and_store(request.user, store_id)

        # Также сохраняем в сессию для веб-интерфейса
        request.session['current_store_id'] = str(store_id)

        return Response({
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'store': {
                'id': str(store_membership.store.id),
                'name': store_membership.store.name,
                'address': store_membership.store.address,
                'role': store_membership.role
            },
            'message': 'Магазин успешно переключен. Используйте новый access token для дальнейших запросов.'
        })


class RefreshTokenWithStoreView(APIView):
    """
    Обновление токена с сохранением информации о магазине
    """
    permission_classes = []  # Разрешаем всем для обновления токена
    authentication_classes = []

    @swagger_auto_schema(
        operation_description="Обновить access token с сохранением магазина",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['refresh'],
            properties={
                'refresh': openapi.Schema(type=openapi.TYPE_STRING),
                'store_id': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    format='uuid',
                    description='ID магазина (опционально, для смены магазина)'
                )
            }
        )
    )
    def post(self, request):
        refresh_token = request.data.get('refresh')
        store_id = request.data.get('store_id')

        if not refresh_token:
            return Response(
                {'error': 'refresh token обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken(refresh_token)
            user_id = refresh.payload.get('user_id')

            user = User.objects.get(id=user_id)

            # Если указан новый магазин, проверяем доступ
            if store_id:
                has_access = StoreEmployee.objects.filter(
                    user=user,
                    store_id=store_id,
                    is_active=True
                ).exists()

                if not has_access:
                    return Response(
                        {'error': 'У вас нет доступа к указанному магазину'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            else:
                # Берем магазин из старого токена или первый доступный
                store_id = refresh.payload.get('store_id')
                if not store_id:
                    membership = StoreEmployee.objects.filter(
                        user=user,
                        is_active=True
                    ).first()
                    if membership:
                        store_id = str(membership.store.id)

            # Генерируем новые токены
            tokens = get_tokens_for_user_and_store(user, store_id)

            return Response({
                'access': tokens['access'],
                'refresh': tokens['refresh']
            })

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class DebugTokenView(APIView):
    """
    Отладочный view для проверки JWT токена и магазина
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        debug_info = {
            'user_info': {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email,
                'is_authenticated': request.user.is_authenticated,
            },
            'user_attributes': {
                'has_current_store': hasattr(request.user, 'current_store'),
                'has_store_role': hasattr(request.user, 'store_role'),
                'has_store_id': hasattr(request.user, 'store_id'),
            },
            'current_store': None,
            'store_memberships': [],
            'jwt_info': {}
        }

        # Информация о текущем магазине
        if hasattr(request.user, 'current_store') and request.user.current_store:
            debug_info['current_store'] = {
                'id': str(request.user.current_store.id),
                'name': request.user.current_store.name,
                'role': getattr(request.user, 'store_role', 'unknown')
            }

        # Все магазины пользователя
        memberships = StoreEmployee.objects.filter(
            user=request.user
        ).select_related('store')

        for membership in memberships:
            debug_info['store_memberships'].append({
                'store_id': str(membership.store.id),
                'store_name': membership.store.name,
                'role': membership.role,
                'is_active': membership.is_active
            })

        # Информация из JWT токена
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                from rest_framework_simplejwt.tokens import AccessToken
                decoded_token = AccessToken(token)
                debug_info['jwt_info'] = {
                    'user_id': decoded_token.get('user_id'),
                    'store_id': decoded_token.get('store_id'),
                    'store_name': decoded_token.get('store_name'),
                    'store_role': decoded_token.get('store_role'),
                    'username': decoded_token.get('username'),
                    'exp': decoded_token.get('exp'),
                }
            except Exception as e:
                debug_info['jwt_info']['error'] = str(e)

        return Response(debug_info)
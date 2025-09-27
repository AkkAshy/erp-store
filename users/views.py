# users/views.py (ИСПРАВЛЕННАЯ ВЕРСИЯ)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .serializers import LoginSerializer, UserSerializer, StoreEmployeeUserSerializer
from rest_framework_simplejwt.tokens import RefreshToken
import logging
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.db.models import Q, Value
from django.db.models.functions import Concat



User = get_user_model()

logger = logging.getLogger(__name__)

# ✅ ДОБАВЛЯЕМ простую функцию логина
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
import json

@csrf_exempt
@require_http_methods(["POST"])
def simple_login(request):
    """
    Простой логин без DRF
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        username = data.get('username')
        password = data.get('password')
        store_id = data.get('store_id')

        if not username or not password:
            return JsonResponse(
                {'error': 'Username и password обязательны'},
                status=400
            )

        # Аутентификация
        user = authenticate(username=username, password=password)

        if not user or not user.is_active:
            return JsonResponse(
                {'error': 'Неверный логин или пароль'},
                status=401
            )

        # Получаем магазины
        from stores.models import StoreEmployee
        store_memberships = StoreEmployee.objects.filter(
            user=user,
            is_active=True
        ).select_related('store')

        if not store_memberships.exists():
            return JsonResponse(
                {'error': 'Пользователь не привязан ни к одному магазину'},
                status=403
            )

        # Определяем текущий магазин
        if store_id:
            current_membership = store_memberships.filter(store_id=store_id).first()
            if not current_membership:
                return JsonResponse(
                    {'error': 'У вас нет доступа к указанному магазину'},
                    status=403
                )
        else:
            current_membership = store_memberships.first()

        # Генерируем токены
        from stores.tokens import get_tokens_for_user_and_store
        tokens = get_tokens_for_user_and_store(user, str(current_membership.store.id))

        # Формируем список магазинов
        available_stores = []
        for membership in store_memberships:
            available_stores.append({
                'id': str(membership.store.id),
                'name': membership.store.name,
                'role': membership.role,
                'is_current': str(membership.store.id) == str(current_membership.store.id)
            })

        return JsonResponse({
            'success': True,
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'current_store': {
                'id': str(current_membership.store.id),
                'name': current_membership.store.name,
                'role': current_membership.role
            },
            'available_stores': available_stores
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Неверный формат JSON'}, status=400)
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Внутренняя ошибка сервера'}, status=500)


class LoginView(APIView):
    """
    ИСПРАВЛЕННЫЙ LoginView - возвращает токены с информацией о магазине
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @swagger_auto_schema(
        operation_summary="Вход пользователя с получением токенов",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING, example='testadmin'),
                'password': openapi.Schema(type=openapi.TYPE_STRING, example='secure123'),
                'store_id': openapi.Schema(type=openapi.TYPE_STRING, format='uuid', description='ID магазина (опционально)')
            },
            required=['username', 'password']
        ),
        responses={
            200: openapi.Response('Успешный вход', schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'access': openapi.Schema(type=openapi.TYPE_STRING),
                    'refresh': openapi.Schema(type=openapi.TYPE_STRING),
                    'user': openapi.Schema(type=openapi.TYPE_OBJECT),
                    'current_store': openapi.Schema(type=openapi.TYPE_OBJECT),
                    'available_stores': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT)
                    )
                }
            )),
            400: "Неверные данные",
            401: "Неверный логин или пароль"
        },
        tags=['Authentication']
    )
    def post(self, request):
        logger.info("Login attempt started")

        username = request.data.get('username')
        password = request.data.get('password')
        store_id = request.data.get('store_id')

        if not username or not password:
            return Response(
                {'error': 'Username и password обязательны'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Аутентификация пользователя
        user = authenticate(username=username, password=password)

        if not user:
            return Response(
                {"error": "Неверный логин или пароль"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {"error": "Аккаунт деактивирован"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        logger.info(f"User {username} authenticated successfully")

        # Получаем магазины пользователя
        from stores.models import StoreEmployee
        store_memberships = StoreEmployee.objects.filter(
            user=user,
            is_active=True
        ).select_related('store')

        if not store_memberships.exists():
            return Response(
                {"error": "Пользователь не привязан ни к одному магазину. Обратитесь к администратору."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Определяем текущий магазин
        if store_id:
            # Проверяем доступ к указанному магазину
            current_membership = store_memberships.filter(store_id=store_id).first()
            if not current_membership:
                return Response(
                    {"error": "У вас нет доступа к указанному магазину"},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            # Берем первый доступный магазин
            current_membership = store_memberships.first()

        # Генерируем токены с информацией о магазине
        from stores.tokens import get_tokens_for_user_and_store
        tokens = get_tokens_for_user_and_store(user, str(current_membership.store.id))

        # Формируем список всех доступных магазинов
        available_stores = []
        for membership in store_memberships:
            available_stores.append({
                'id': str(membership.store.id),
                'name': membership.store.name,
                'role': membership.role,
                'logo': membership.store.logo.url if membership.store.logo else None,
                'is_current': str(membership.store.id) == str(current_membership.store.id)
            })

        response_data = {
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'full_name': user.get_full_name() or user.username
            },
            'current_store': {
                'id': str(current_membership.store.id),
                'name': current_membership.store.name,
                'role': current_membership.role
            },
            'available_stores': available_stores,
            'message': 'Успешный вход в систему'
        }

        logger.info(f"Login successful for {username} with store {current_membership.store.name}")
        return Response(response_data, status=status.HTTP_200_OK)


# ДОБАВЛЯЕМ простую функцию логина тоже
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
import json

@csrf_exempt
@require_http_methods(["POST"])
def simple_login(request):
    """
    Простой логин без DRF
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        username = data.get('username')
        password = data.get('password')
        store_id = data.get('store_id')

        if not username or not password:
            return JsonResponse(
                {'error': 'Username и password обязательны'},
                status=400
            )

        # Аутентификация
        user = authenticate(username=username, password=password)

        if not user or not user.is_active:
            return JsonResponse(
                {'error': 'Неверный логин или пароль'},
                status=401
            )

        # Получаем магазины
        from stores.models import StoreEmployee
        store_memberships = StoreEmployee.objects.filter(
            user=user,
            is_active=True
        ).select_related('store')

        if not store_memberships.exists():
            return JsonResponse(
                {'error': 'Пользователь не привязан ни к одному магазину'},
                status=403
            )

        # Определяем текущий магазин
        if store_id:
            current_membership = store_memberships.filter(store_id=store_id).first()
            if not current_membership:
                return JsonResponse(
                    {'error': 'У вас нет доступа к указанному магазину'},
                    status=403
                )
        else:
            current_membership = store_memberships.first()

        # Генерируем токены
        from stores.tokens import get_tokens_for_user_and_store
        tokens = get_tokens_for_user_and_store(user, str(current_membership.store.id))

        # Формируем список магазинов
        available_stores = []
        for membership in store_memberships:
            available_stores.append({
                'id': str(membership.store.id),
                'name': membership.store.name,
                'role': membership.role,
                'is_current': str(membership.store.id) == str(current_membership.store.id)
            })

        return JsonResponse({
            'success': True,
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'current_store': {
                'id': str(current_membership.store.id),
                'name': current_membership.store.name,
                'role': current_membership.role
            },
            'available_stores': available_stores
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Неверный формат JSON'}, status=400)
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Внутренняя ошибка сервера'}, status=500)


# Остальные views остаются без изменений...
class RegisterView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @swagger_auto_schema(
        operation_summary="Регистрация сотрудника",
        request_body=UserSerializer,
        responses={201: UserSerializer, 400: "Неверные данные"},
        tags=['Registration']
    )
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="Обновление профиля пользователя",
        request_body=UserSerializer,
        responses={200: UserSerializer, 400: "Неверные данные"},
        tags=['Update Profile']
    )
    def patch(self, request):
        user = request.user
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    @swagger_auto_schema(
        operation_summary="Получение профиля пользователя",
        responses={200: UserSerializer, 404: "Пользователь не найден"},
        tags=['Profile']
    )
    def get(self, request):
        user = request.user
        serializer = UserSerializer(user)
        return Response(serializer.data)


class UserListView(APIView):
    permission_classes = [permissions.IsAuthenticated]


    @swagger_auto_schema(
        operation_summary="Список сотрудников текущего магазина (из JWT токена)",
        manual_parameters=[
            openapi.Parameter(
                'name',
                openapi.IN_QUERY,
                description="Поиск по имени, фамилии, username",
                type=openapi.TYPE_STRING
            ),
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="Фильтр по роли (owner, admin, manager, cashier, stockkeeper)",
                type=openapi.TYPE_STRING
            ),
            openapi.Parameter(
                'is_active',
                openapi.IN_QUERY,
                description="Только активные сотрудники",
                type=openapi.TYPE_BOOLEAN
            ),
        ],
        responses={200: openapi.Response(
            description="Список сотрудников магазина",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'store': openapi.Schema(type=openapi.TYPE_OBJECT),
                    'total_employees': openapi.Schema(type=openapi.TYPE_INTEGER),
                    'employees': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT)
                    )
                }
            )
        )},
        tags=['Users']
    )
    def get(self, request):
        from stores.models import StoreEmployee, Store
        from .serializers import StoreEmployeeUserSerializer
        import jwt
        from rest_framework_simplejwt.tokens import AccessToken

        # Получаем текущий магазин из JWT токена
        current_store = None
        current_user_role = None

        # Способ 1: Извлекаем из JWT токена
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(' ')[1]
                # Декодируем токен
                decoded_token = AccessToken(token)

                store_id = decoded_token.get('store_id')
                store_name = decoded_token.get('store_name')
                store_role = decoded_token.get('store_role')

                logger.info(f"JWT Token info - store_id: {store_id}, store_name: {store_name}, role: {store_role}")

                if store_id:
                    try:
                        current_store = Store.objects.get(id=store_id)
                        current_user_role = store_role
                        logger.info(f"✅ Store from JWT: {current_store.name}")
                    except Store.DoesNotExist:
                        logger.error(f"Store {store_id} from JWT not found")

            except Exception as e:
                logger.error(f"Error decoding JWT: {e}")

        # Способ 2: Если не удалось из JWT, пробуем из middleware
        if not current_store and hasattr(request.user, 'current_store') and request.user.current_store:
            current_store = request.user.current_store
            current_user_role = getattr(request.user, 'store_role', None)
            logger.info(f"✅ Store from middleware: {current_store.name}")

        # Способ 3: Если все еще нет, берем из базы
        if not current_store:
            store_membership = StoreEmployee.objects.filter(
                user=request.user,
                is_active=True
            ).select_related('store').first()

            if store_membership:
                current_store = store_membership.store
                current_user_role = store_membership.role
                logger.info(f"✅ Store from DB: {current_store.name}")
            else:
                logger.error(f"No store found for user {request.user.username}")
                return Response(
                    {
                        "error": "У вас нет доступа к магазину",
                        "debug_info": {
                            "user": request.user.username,
                            "jwt_decoded": auth_header.startswith('Bearer '),
                            "has_middleware_store": hasattr(request.user, 'current_store')
                        }
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        # Проверяем права доступа
        if current_user_role not in ['owner', 'admin', 'manager']:
            return Response(
                {
                    "error": "У вас нет прав для просмотра списка сотрудников",
                    "your_role": current_user_role
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Получаем ТОЛЬКО сотрудников ТЕКУЩЕГО магазина
        queryset = StoreEmployee.objects.filter(
            store=current_store  # ← ФИЛЬТРУЕМ ПО МАГАЗИНУ ИЗ JWT
        ).select_related('user', 'user__employee')

        logger.info(f"Filtering employees for store: {current_store.name} (ID: {current_store.id})")

        # Применяем дополнительные фильтры
        role_filter = request.query_params.get('role')
        if role_filter:
            queryset = queryset.filter(role=role_filter)

        def str_to_bool(value: str) -> bool:
            return str(value).strip().lower() in ['true', '1', 'yes', 'y']

        is_active = request.query_params.get('is_active')
        if is_active is not None:
            is_active_bool = str_to_bool(is_active)
            queryset = queryset.filter(is_active=is_active_bool)

        search_name = request.query_params.get('name')
        if search_name:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search_name) |
                Q(user__last_name__icontains=search_name) |
                Q(user__username__icontains=search_name)
            )

        # Получаем пользователей
        users = []
        for se in queryset:
            user = se.user
            users.append(user)

        logger.info(f"Found {len(users)} employees in store {current_store.name}")

        # Сериализуем с контекстом магазина
        serializer = StoreEmployeeUserSerializer(
            users,
            many=True,
            context={
                'store': current_store,
                'request': request
            }
        )

        # Формируем статистику
        stats = {
            'total': queryset.count(),
            'active': queryset.filter(is_active=True).count(),
            'by_role': {}
        }

        for role_choice in StoreEmployee.ROLE_CHOICES:
            role_code = role_choice[0]
            stats['by_role'][role_code] = queryset.filter(role=role_code).count()

        return Response({
            'store': {
                'id': str(current_store.id),
                'name': current_store.name,
                'address': current_store.address
            },
            'current_user': {
                'username': request.user.username,
                'role': current_user_role
            },
            'statistics': stats,
            'employees': serializer.data
        })

    def _get_current_store(self, request):
        """Вспомогательный метод для получения текущего магазина"""
        from stores.models import StoreEmployee

        # Пытаемся получить из атрибута пользователя
        if hasattr(request.user, 'current_store') and request.user.current_store:
            return request.user.current_store

        # Если нет, получаем из базы
        store_membership = StoreEmployee.objects.filter(
            user=request.user,
            is_active=True
        ).select_related('store').first()

        return store_membership.store if store_membership else None

class UserDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="Детальная информация о сотруднике магазина",
        responses={
            200: StoreEmployeeUserSerializer(),
            403: "Нет доступа",
            404: "Пользователь не найден"
        },
        tags=['Users']
    )
    def get(self, request, pk):
        from stores.models import StoreEmployee, Store
        from .serializers import StoreEmployeeUserSerializer
        from rest_framework_simplejwt.tokens import AccessToken

        # Получаем текущий магазин из JWT
        current_store = None
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(' ')[1]
                decoded_token = AccessToken(token)
                store_id = decoded_token.get('store_id')

                if store_id:
                    current_store = Store.objects.filter(id=store_id).first()

            except Exception as e:
                logger.error(f"Error decoding JWT: {e}")

        # Fallback на другие методы
        if not current_store:
            current_store = self._get_current_store(request)

        if not current_store:
            return Response(
                {"error": "У вас нет доступа к магазину"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Проверяем что запрашиваемый пользователь является сотрудником ЭТОГО магазина
        try:
            store_employee = StoreEmployee.objects.get(
                user_id=pk,
                store=current_store  # ← Проверяем магазин
            )
        except StoreEmployee.DoesNotExist:
            return Response(
                {
                    "error": "Пользователь не найден в этом магазине",
                    "store": current_store.name,
                    "user_id": pk
                },
                status=status.HTTP_404_NOT_FOUND
            )

        user = store_employee.user

        # Сериализуем с контекстом магазина
        serializer = StoreEmployeeUserSerializer(
            user,
            context={'store': current_store, 'request': request}
        )

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Обновить информацию о сотруднике",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                'email': openapi.Schema(type=openapi.TYPE_STRING),
                'password': openapi.Schema(type=openapi.TYPE_STRING),
                'phone': openapi.Schema(type=openapi.TYPE_STRING),
                'sex': openapi.Schema(type=openapi.TYPE_STRING),
                'role': openapi.Schema(type=openapi.TYPE_STRING),
                'is_active': openapi.Schema(type=openapi.TYPE_BOOLEAN),
            }
        ),
        responses={
            200: "Успешно обновлено",
            403: "Нет прав",
            404: "Не найден"
        },
        tags=['Users']
    )
    def patch(self, request, pk):
        from stores.models import StoreEmployee, Store
        from .models import Employee
        from rest_framework_simplejwt.tokens import AccessToken

        # Получаем текущий магазин из JWT
        current_store = None
        current_user_role = None
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(' ')[1]
                decoded_token = AccessToken(token)
                store_id = decoded_token.get('store_id')
                current_user_role = decoded_token.get('store_role')

                if store_id:
                    current_store = Store.objects.filter(id=store_id).first()

            except Exception as e:
                logger.error(f"Error decoding JWT: {e}")

        if not current_store:
            current_store = self._get_current_store(request)

        if not current_store:
            return Response(
                {"error": "У вас нет доступа к магазину"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Проверяем права (только owner и admin могут редактировать)
        if not current_user_role:
            user_membership = StoreEmployee.objects.filter(
                user=request.user,
                store=current_store
            ).first()
            current_user_role = user_membership.role if user_membership else None

        if current_user_role not in ['owner', 'admin']:
            return Response(
                {
                    "error": "У вас нет прав для редактирования сотрудников",
                    "your_role": current_user_role
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Находим сотрудника В ЭТОМ МАГАЗИНЕ
        try:
            store_employee = StoreEmployee.objects.get(
                user_id=pk,
                store=current_store  # ← Проверяем магазин
            )
        except StoreEmployee.DoesNotExist:
            return Response(
                {"error": "Пользователь не найден в этом магазине"},
                status=status.HTTP_404_NOT_FOUND
            )

        user = store_employee.user

        # Обновляем данные пользователя
        if 'first_name' in request.data:
            user.first_name = request.data['first_name']
        if 'last_name' in request.data:
            user.last_name = request.data['last_name']
        if 'email' in request.data:
            user.email = request.data['email']

        # ОБНОВЛЯЕМ ПАРОЛЬ
        if 'password' in request.data:
            new_password = request.data['password']
            if len(new_password) < 6:
                return Response(
                    {"error": "Пароль должен быть не менее 6 символов"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Меняем пароль пользователя
            user.set_password(new_password)

            # Обновляем пароль в Employee
            try:
                employee = user.employee
                employee.plain_password = new_password
                employee.save()
                logger.info(f"Password updated for {user.username} by {request.user.username}")
            except Employee.DoesNotExist:
                # Создаем Employee если не существует
                Employee.objects.create(
                    user=user,
                    role=store_employee.role,
                    plain_password=new_password
                )

        user.save()

        # Обновляем роль и статус в магазине
        if 'role' in request.data:
            store_employee.role = request.data['role']
        if 'is_active' in request.data:
            store_employee.is_active = request.data['is_active']



        # Обновляем данные Employee
        if 'phone' in request.data or 'sex' in request.data:
            try:
                employee = user.employee
                if 'phone' in request.data:
                    employee.phone = request.data['phone']
                    print(f"Updating phone to: {request.data['phone']}")  # Отладка
                if 'sex' in request.data:
                    employee.sex = request.data['sex']
                    print(f"Updating sex to: {request.data['sex']}")  # Отладка
                employee.save()
                print(f"Employee saved with phone: {employee.phone}, sex: {employee.sex}")  # Отладка
            except Employee.DoesNotExist:
                print("Employee not found, creating new one")  # Отладка
                Employee.objects.create(
                    user=user,
                    role=store_employee.role,
                    phone=request.data.get('phone', ''),
                    sex=request.data.get('sex', ''),
                    # store=current_store  # Добавить если нужно
                )

        store_employee.save()

        # Обновленный ответ с номером телефона и полом
        return Response({
            "message": "Информация о сотруднике обновлена",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.employee.phone if hasattr(user, 'employee') else None,
                "sex": user.employee.sex if hasattr(user, 'employee') else None,  # ← ДОБАВЛЕНО
                "password": user.employee.plain_password if hasattr(user, 'employee') else None
            }
        })

    @swagger_auto_schema(
        operation_summary="Удалить сотрудника из магазина",
        responses={
            204: "Успешно удален",
            403: "Нет прав",
            404: "Не найден"
        },
        tags=['Users']
    )
    def delete(self, request, pk):
        from stores.models import StoreEmployee, Store
        from rest_framework_simplejwt.tokens import AccessToken

        # Получаем текущий магазин из JWT
        current_store = None
        current_user_role = None
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(' ')[1]
                decoded_token = AccessToken(token)
                store_id = decoded_token.get('store_id')
                current_user_role = decoded_token.get('store_role')

                if store_id:
                    current_store = Store.objects.filter(id=store_id).first()

            except Exception as e:
                logger.error(f"Error decoding JWT: {e}")

        if not current_store:
            return Response(
                {"error": "У вас нет доступа к магазину"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Только owner может удалять сотрудников
        if current_user_role != 'owner':
            return Response(
                {"error": "Только владелец может удалять сотрудников"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Находим и удаляем связь с магазином
        try:
            store_employee = StoreEmployee.objects.get(
                user_id=pk,
                store=current_store  # ← Проверяем магазин
            )

            # Нельзя удалить владельца
            if store_employee.role == 'owner':
                return Response(
                    {"error": "Нельзя удалить владельца магазина"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Удаляем связь с магазином (но не самого пользователя)
            store_employee.delete()

            logger.info(f"Employee {store_employee.user.username} removed from store {current_store.name}")

            return Response(status=status.HTTP_204_NO_CONTENT)

        except StoreEmployee.DoesNotExist:
            return Response(
                {"error": "Пользователь не найден в этом магазине"},
                status=status.HTTP_404_NOT_FOUND
            )

    def _get_current_store(self, request):
        """Вспомогательный метод для получения текущего магазина"""
        from stores.models import StoreEmployee

        if hasattr(request.user, 'current_store') and request.user.current_store:
            return request.user.current_store

        store_membership = StoreEmployee.objects.filter(
            user=request.user,
            is_active=True
        ).select_related('store').first()

        return store_membership.store if store_membership else None

# users/views.py - добавьте этот класс

from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView
from stores.tokens import StoreTokenObtainPairSerializer

class CustomTokenObtainPairView(BaseTokenObtainPairView):
    """
    Кастомный view для логина, который возвращает токены с информацией о магазине
    """
    serializer_class = StoreTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            # Добавляем информацию о пользователе и магазине в ответ
            from django.contrib.auth import authenticate
            from stores.models import StoreEmployee

            username = request.data.get('username')
            password = request.data.get('password')
            user = authenticate(username=username, password=password)

            if user:
                # Получаем информацию о магазинах
                store_memberships = StoreEmployee.objects.filter(
                    user=user,
                    is_active=True
                ).select_related('store')

                # Берем первый магазин
                current_membership = store_memberships.first()

                # Список всех доступных магазинов
                available_stores = []
                for membership in store_memberships:
                    available_stores.append({
                        'id': str(membership.store.id),
                        'name': membership.store.name,
                        'role': membership.role,
                        'is_current': membership == current_membership
                    })

                # Добавляем информацию в ответ
                response.data['user'] = {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'full_name': user.get_full_name() or user.username
                }

                if current_membership:
                    response.data['current_store'] = {
                        'id': str(current_membership.store.id),
                        'name': current_membership.store.name,
                        'role': current_membership.role
                    }

                response.data['available_stores'] = available_stores

        return response

class CustomLoginView(APIView):
    """
    Кастомный логин с полной информацией о магазине
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @swagger_auto_schema(
        operation_description="Вход в систему с получением токенов и информации о магазине",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['username', 'password'],
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING, example='testadmin'),
                'password': openapi.Schema(type=openapi.TYPE_STRING, example='secure123'),
                'store_id': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    format='uuid',
                    description='ID магазина (опционально)'
                )
            }
        ),
        responses={
            200: openapi.Response('Успешный вход'),
            401: 'Неверные учетные данные'
        }
    )
    def post(self, request):
        from django.contrib.auth import authenticate
        from stores.models import StoreEmployee
        from stores.tokens import get_tokens_for_user_and_store

        username = request.data.get('username')
        password = request.data.get('password')
        store_id = request.data.get('store_id')

        if not username or not password:
            return Response(
                {'error': 'Username и password обязательны'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Аутентификация
        user = authenticate(username=username, password=password)

        if not user:
            return Response(
                {'error': 'Неверные учетные данные'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {'error': 'Аккаунт деактивирован'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Получаем магазины пользователя
        store_memberships = StoreEmployee.objects.filter(
            user=user,
            is_active=True
        ).select_related('store')

        if not store_memberships.exists():
            return Response(
                {'error': 'Пользователь не привязан ни к одному магазину'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Определяем текущий магазин
        if store_id:
            current_membership = store_memberships.filter(store_id=store_id).first()
            if not current_membership:
                return Response(
                    {'error': 'У вас нет доступа к указанному магазину'},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            current_membership = store_memberships.first()

        # Генерируем токены с информацией о магазине
        tokens = get_tokens_for_user_and_store(user, str(current_membership.store.id))

        # Формируем список всех доступных магазинов
        available_stores = []
        for membership in store_memberships:
            available_stores.append({
                'id': str(membership.store.id),
                'name': membership.store.name,
                'role': membership.role,
                'is_current': str(membership.store.id) == str(current_membership.store.id)
            })

        # Проверяем токены на наличие информации о магазине
        import jwt
        try:
            decoded_access = jwt.decode(tokens['access'], options={"verify_signature": False})
            logger.info(f"Access token содержит: store_id={decoded_access.get('store_id')}, store_name={decoded_access.get('store_name')}")
        except Exception as e:
            logger.error(f"Ошибка декодирования токена: {e}")

        return Response({
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'full_name': user.get_full_name() or user.username
            },
            'current_store': {
                'id': str(current_membership.store.id),
                'name': current_membership.store.name,
                'role': current_membership.role
            },
            'available_stores': available_stores,
            'message': 'Успешный вход в систему'
        })
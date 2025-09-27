# stores/middleware.py
from django.utils.deprecation import MiddlewareMixin
import logging

logger = logging.getLogger(__name__)

class CurrentStoreMiddleware(MiddlewareMixin):
    """
    Middleware для установки текущего магазина пользователя из JWT токена
    """
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Импорты внутри метода чтобы избежать circular imports
        from rest_framework_simplejwt.authentication import JWTAuthentication
        from django.contrib.auth.models import AnonymousUser
        
        logger.debug(f"🔍 Processing {request.method} {request.path}")
        logger.debug(f"👤 User: {request.user}, Type: {type(request.user)}")
        logger.debug(f"🔐 Is authenticated: {request.user.is_authenticated}")
        logger.debug(f"📋 Headers: {dict(request.headers)}")

        # Пропускаем публичные endpoints
        public_paths = [
            '/api/stores/register/',
            '/api/stores/refresh-token/',
            '/users/login/',
            '/users/register/',
            '/admin/',
            '/swagger/',
            '/redoc/',
            '/static/',
            '/media/',
        ]

        if any(request.path.startswith(path) for path in public_paths):
            logger.debug(f"⏭️ Skipping public path: {request.path}")
            return None

        # Инициализируем атрибуты магазина
        if not hasattr(request.user, 'current_store'):
            request.user.current_store = None
            request.user.store_role = None
            request.user.store_id = None

        # Если пользователь не аутентифицирован, пропускаем
        if isinstance(request.user, AnonymousUser) or not request.user.is_authenticated:
            logger.debug("👤 User not authenticated, skipping store setup")
            return None

        try:
            # Импортируем модели внутри try блока
            from .models import StoreEmployee, Store
            
            # Пытаемся получить JWT токен и извлечь store_id
            jwt_auth = JWTAuthentication()
            auth_result = jwt_auth.authenticate(request)

            if auth_result:
                authenticated_user, validated_token = auth_result

                # Обновляем request.user если нужно
                if request.user != authenticated_user:
                    request.user = authenticated_user

                # Извлекаем данные магазина из токена
                store_id = validated_token.get('store_id')
                store_role = validated_token.get('store_role')

                logger.debug(f"🏪 Token store_id: {store_id}, role: {store_role}")

                if store_id:
                    try:
                        # Получаем магазин и проверяем доступ
                        store = Store.objects.get(id=store_id, is_active=True)

                        # Проверяем доступ пользователя к магазину
                        store_membership = StoreEmployee.objects.filter(
                            user=request.user,
                            store=store,
                            is_active=True
                        ).first()

                        if store_membership:
                            # Устанавливаем атрибуты магазина
                            request.user.current_store = store
                            request.user.store_role = store_membership.role
                            request.user.store_id = str(store.id)

                            logger.info(f"✅ Store set: {store.name} for {request.user.username} ({store_membership.role})")
                            return None
                        else:
                            logger.warning(f"⚠️ User {request.user.username} has no access to store {store_id}")

                    except Store.DoesNotExist:
                        logger.error(f"❌ Store {store_id} not found")

                # Если магазин из токена недоступен, берем первый доступный
                store_membership = StoreEmployee.objects.filter(
                    user=request.user,
                    is_active=True
                ).select_related('store').first()

                if store_membership:
                    request.user.current_store = store_membership.store
                    request.user.store_role = store_membership.role
                    request.user.store_id = str(store_membership.store.id)

                    logger.info(f"✅ Fallback store set: {store_membership.store.name}")
                else:
                    logger.warning(f"⚠️ No accessible stores found for user {request.user.username}")

            else:
                # JWT не найден, но пользователь аутентифицирован
                logger.debug("🔑 No JWT token, trying session-based store")

                store_membership = StoreEmployee.objects.filter(
                    user=request.user,
                    is_active=True
                ).select_related('store').first()

                if store_membership:
                    request.user.current_store = store_membership.store
                    request.user.store_role = store_membership.role
                    request.user.store_id = str(store_membership.store.id)

                    logger.info(f"✅ Session store set: {store_membership.store.name}")

        except Exception as e:
            logger.error(f"❌ Error in store middleware: {str(e)}")
            # Не прерываем запрос, просто логируем ошибку

        return None

    def process_response(self, request, response):
        # Логируем финальное состояние для отладки
        if hasattr(request, 'user') and hasattr(request.user, 'current_store'):
            store_name = request.user.current_store.name if request.user.current_store else None
            logger.debug(f"🏁 Final store for {request.path}: {store_name}")

        return response
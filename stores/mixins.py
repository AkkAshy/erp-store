# stores/mixins.py (ИСПРАВЛЕННАЯ ВЕРСИЯ)
from django.db import models
from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import serializers
from .models import Store
import logging
from rest_framework.permissions import BasePermission
import jwt
from rest_framework_simplejwt.authentication import JWTAuthentication
from stores.services.store_access_service import store_access_service



logger = logging.getLogger(__name__)



class StoreJWTPermission(BasePermission):
    """
    Permission для JWT-аутентификации с информацией о магазине в токене
    """
    
    def has_permission(self, request, view):
        # Получаем токен из заголовка
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header or not auth_header.startswith('Bearer '):
            return False
        
        token = auth_header.split(' ')[1]
        
        try:
            # Декодируем токен (без проверки подписи для получения данных)
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            
            # Получаем данные из токена
            user_id = decoded_token.get('user_id')
            store_id = decoded_token.get('store_id')
            store_name = decoded_token.get('store_name')
            
            if not user_id or not store_id:
                return False
            
            # Получаем пользователя
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            try:
                user = User.objects.get(id=user_id)
                request.user = user
            except User.DoesNotExist:
                return False
            
            # Получаем магазин
            from stores.models import Store
            try:
                store = Store.objects.get(id=store_id)
                request.current_store = store
                
                # Устанавливаем current_store для user (для совместимости)
                user.current_store = store
                
            except Store.DoesNotExist:
                return False
            
            # Проверяем права пользователя в магазине
            from stores.models import StoreEmployee
            membership = StoreEmployee.objects.filter(
                user=user,
                store=store,
                is_active=True
            ).first()
            
            if not membership:
                return False
            
            # Сохраняем роль для дальнейшего использования
            request.user_store_role = membership.role
            
            return True
            
        except (jwt.DecodeError, KeyError, ValueError) as e:
            print(f"DEBUG: JWT decode error: {e}")
            return False
    
    def has_object_permission(self, request, view, obj):
        # Проверяем, что объект принадлежит магазину из токена
        if hasattr(obj, 'store') and hasattr(request, 'current_store'):
            return obj.store == request.current_store
        return True
    


class StoreJWTAuthentication(JWTAuthentication):
    """
    Кастомная JWT-аутентификация с установкой текущего магазина
    """
    
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        
        # Получаем store_id из токена
        store_id = validated_token.get('store_id')
        if store_id:
            from stores.models import Store
            try:
                store = Store.objects.get(id=store_id)
                user.current_store = store
            except Store.DoesNotExist:
                pass
        
        return user

class SimpleStorePermission(BasePermission):
    """
    Простая проверка после JWT-аутентификации
    """
    
    def has_permission(self, request, view):
        # Пользователь уже аутентифицирован через JWT
        if not hasattr(request, 'user') or not request.user:
            return False
        
        # Проверяем наличие current_store
        if hasattr(request.user, 'current_store') and request.user.current_store:
            request.current_store = request.user.current_store
            return True
        
        return False
    


class StoreOwnedModel(models.Model):
    """
    Абстрактная модель для всех сущностей, принадлежащих магазину
    """
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='%(class)s_set',
        verbose_name="Магазин",
        editable=False
    )

    class Meta:
        abstract = True


class StoreFilteredQuerySet(models.QuerySet):
    """
    QuerySet, который автоматически фильтрует по магазину
    """
    def for_store(self, store):
        """Фильтрация по конкретному магазину"""
        if store:
            return self.filter(store=store)
        return self.none()

    def for_user(self, user):
        """Фильтрация по магазину пользователя"""
        if hasattr(user, 'current_store') and user.current_store:
            return self.filter(store=user.current_store)
        return self.none()


class StoreOwnedManager(models.Manager):
    """
    ✅ ИСПРАВЛЕННЫЙ менеджер для моделей, принадлежащих магазину
    """
    def get_queryset(self):
        """
        Возвращает queryset с фильтрацией удаленных записей (если поле есть)
        """
        queryset = StoreFilteredQuerySet(self.model, using=self._db)

        # ✅ ИСПРАВЛЕНИЕ: Проверяем есть ли поле is_deleted перед фильтрацией
        if hasattr(self.model, '_meta'):
            field_names = [field.name for field in self.model._meta.get_fields()]
            if 'is_deleted' in field_names:
                queryset = queryset.filter(is_deleted=False)

        return queryset

    def for_store(self, store):
        return self.get_queryset().for_store(store)

    def for_user(self, user):
        return self.get_queryset().for_user(user)

    def include_deleted(self):
        """Получить все записи включая удаленные"""
        return StoreFilteredQuerySet(self.model, using=self._db)

    def only_deleted(self):
        """Получить только удаленные записи"""
        queryset = StoreFilteredQuerySet(self.model, using=self._db)

        # Проверяем есть ли поле is_deleted
        if hasattr(self.model, '_meta'):
            field_names = [field.name for field in self.model._meta.get_fields()]
            if 'is_deleted' in field_names:
                return queryset.filter(is_deleted=True)

        return queryset.none()


class StoreViewSetMixin:
    """
    Миксин для ViewSet'ов с автоматической фильтрацией по магазину
    """
    def get_current_store(self):
        """Получить текущий магазин с резервными способами"""
        user = self.request.user

        # Способ 1: Из атрибутов пользователя (установлено middleware)
        if hasattr(user, 'current_store') and user.current_store:
            # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: есть ли у пользователя доступ к этому магазину
            if self._user_has_access_to_store(user, user.current_store):
                logger.debug(f"✅ Store from user attribute: {user.current_store.name}")
                return user.current_store
            else:
                logger.warning(f"⚠️ User {user.username} has no access to store {user.current_store.name}")

        # Способ 2: Через Employee модель
        if hasattr(user, 'employee') and user.employee and user.employee.store:
            store = user.employee.store
            if self._user_has_access_to_store(user, store):
                logger.debug(f"✅ Store from Employee model: {store.name}")
                user.current_store = store
                return store

        # Способ 3: Из JWT токена напрямую
        try:
            auth_header = self.request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                from rest_framework_simplejwt.tokens import AccessToken
                decoded_token = AccessToken(token)
                store_id = decoded_token.get('store_id')

                if store_id:
                    from stores.models import Store
                    store = Store.objects.get(id=store_id, is_active=True)

                    # ✅ ПРОВЕРЯЕМ ДОСТУП К МАГАЗИНУ ИЗ ТОКЕНА
                    if self._user_has_access_to_store(user, store):
                        logger.debug(f"✅ Store from JWT token: {store.name}")
                        user.current_store = store
                        return store
                    else:
                        logger.warning(f"⚠️ User {user.username} has no access to store from JWT: {store.name}")

        except Exception as e:
            logger.debug(f"Failed to get store from JWT: {e}")

        # ✅ ИСПРАВЛЕНО: Способ 4 - Берем ПЕРВЫЙ ДОСТУПНЫЙ магазин пользователя
        accessible_stores = self._get_user_accessible_stores(user)
        if accessible_stores:
            first_store = accessible_stores.first()
            logger.debug(f"✅ Using first accessible store: {first_store.name}")
            user.current_store = first_store
            return first_store

        logger.warning(f"❌ No accessible stores found for user {user.username}")
        return None

    def _user_has_access_to_store(self, user, store):
        """Проверяет, есть ли у пользователя доступ к конкретному магазину"""
        from stores.models import StoreEmployee

        return StoreEmployee.objects.filter(
            user=user,
            store=store,
            is_active=True
        ).exists()

    def _get_user_accessible_stores(self, user):
        """Получает все магазины, к которым у пользователя есть доступ"""
        from stores.models import StoreEmployee, Store

        # Получаем ID магазинов, где пользователь является активным сотрудником
        accessible_store_ids = StoreEmployee.objects.filter(
            user=user,
            is_active=True
        ).values_list('store_id', flat=True)

        # Возвращаем только активные магазины
        return Store.objects.filter(
            id__in=accessible_store_ids,
            is_active=True
        )

    def get_queryset(self):
        """Автоматически фильтруем по магазину"""
        queryset = super().get_queryset()

        # Проверяем, что модель поддерживает магазины
        if not hasattr(queryset.model, 'store'):
            logger.debug(f"Model {queryset.model.__name__} doesn't have store field, skipping filter")
            return queryset

        # Получаем текущий магазин
        current_store = self.get_current_store()

        if current_store:
            queryset = queryset.filter(store=current_store)
            logger.debug(f"✅ Filtered queryset by store: {current_store.name}")
        else:
            # ✅ ИСПРАВЛЕНО: Если магазин не найден, возвращаем пустой queryset
            logger.warning(f"⚠️ No store found for {queryset.model.__name__}, returning empty queryset")
            queryset = queryset.none()

        return queryset

    def perform_create(self, serializer):
        """✅ ИСПРАВЛЕННОЕ создание с правильным порядком операций"""
        current_store = self.get_current_store()

        if not current_store:
            logger.error(f"❌ Cannot create {serializer.Meta.model.__name__}: no store found")
            raise ValidationError({
                'non_field_errors': ['Магазин не определен. Переавторизуйтесь или выберите магазин.'],
                'debug_info': {
                    'user_id': self.request.user.id,
                    'username': self.request.user.username,
                    'accessible_stores': list(self._get_user_accessible_stores(self.request.user).values_list('name', flat=True))
                }
            })

        # Подготавливаем данные для сохранения
        save_kwargs = {'store': current_store}

        # Дополнительные поля
        if hasattr(serializer.Meta.model, 'created_by'):
            save_kwargs['created_by'] = self.request.user

        if hasattr(serializer.Meta.model, 'cashier'):
            save_kwargs['cashier'] = self.request.user

        try:
            # ✅ ИСПРАВЛЕНИЕ: Убираем специальную логику для Product
            # Для всех моделей используем одинаковый подход

            # Проверяем, есть ли уже созданный instance без ID
            if hasattr(serializer, 'instance') and serializer.instance and not serializer.instance.pk:
                # Если объект создан в serializer.create(), но не сохранен
                instance = serializer.instance
                for key, value in save_kwargs.items():
                    setattr(instance, key, value)
                instance.save()
                serializer.instance = instance
                logger.info(f"✅ Saved existing instance: {serializer.Meta.model.__name__} for store {current_store.name}")
            else:
                # Обычное сохранение через serializer.save()
                serializer.save(**save_kwargs)
                logger.info(f"✅ Created new {serializer.Meta.model.__name__} for store {current_store.name}")

        except Exception as e:
            logger.error(f"❌ Error creating {serializer.Meta.model.__name__}: {str(e)}")
            raise

    def perform_update(self, serializer):
        """Проверяем принадлежность к магазину при обновлении"""
        instance = self.get_object()
        current_store = self.get_current_store()

        if hasattr(instance, 'store') and current_store:
            if instance.store != current_store:
                raise PermissionDenied("Вы не можете редактировать данные другого магазина")

        serializer.save()

    def perform_destroy(self, instance):
        """Проверяем принадлежность к магазину при удалении"""
        current_store = self.get_current_store()

        if hasattr(instance, 'store') and current_store:
            if instance.store != current_store:
                raise PermissionDenied("Вы не можете удалять данные другого магазина")

        instance.delete()


class StoreSerializerMixin:
    """
    Миксин для сериализаторов - убирает store из полей
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Убираем поле store из сериализатора, если оно есть
        if 'store' in self.fields:
            self.fields.pop('store')


class StorePermissionMixin:
    """
    Миксин для проверки прав доступа на основе роли в магазине
    """
    def has_store_permission(self, user, permission_name):
        """Проверяет, есть ли у пользователя разрешение в текущем магазине"""
        if not hasattr(user, 'current_store') or not user.current_store:
            return False

        from .models import StoreEmployee
        try:
            membership = StoreEmployee.objects.get(
                user=user,
                store=user.current_store,
                is_active=True
            )
            return getattr(membership, permission_name, False)
        except StoreEmployee.DoesNotExist:
            return False

    def check_store_permission(self, user, permission_name):
        """Проверяет разрешение и выбрасывает исключение если нет доступа"""
        if not self.has_store_permission(user, permission_name):
            raise PermissionDenied(f"У вас нет разрешения: {permission_name}")
        

class StorePermissionWrapper(BasePermission):
    """
    🛡️ Страж ворот — использует мудрость StoreAccessService
    """
    
    def has_permission(self, request, view):
        """
        🚪 Проверка на вход: аутентификация + доступ к магазину
        """
        if not request.user.is_authenticated:
            logger.debug("🚫 Анонимный гость у ворот")
            return False
        
        logger.debug(f"👤 Гость: {request.user.username}")
        
        # Спрашиваем у оракула, куда идти этому пользователю
        current_store = store_access_service.get_current_store(request.user, request)
        request.user.current_store = current_store  # Сохраняем для потомков
        
        logger.debug(f"🏪 Назначен магазин: {getattr(current_store, 'name', 'НЕТ')}")
        
        # Базовая проверка доступа к магазину
        if not current_store:
            self.message = "Ключей к этому царству у тебя нет"
            logger.warning(f"⚠️ {request.user.username} — бездомный странник")
            return False
        
        # Сохраняем магазин в запросе для всех
        request.current_store = current_store
        
        # Для чтения — открываем двери
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            logger.debug(f"📖 Чтение разрешено для {request.user.username}")
            return True
        
        # Для изменений — проверяем конкретные полномочия
        required_permission = self._get_permission_for_method(request.method)
        has_permission = self._check_user_permission(request.user, required_permission)
        
        logger.debug(f"🔑 {required_permission}-разрешение: {'✅' if has_permission else '❌'}")
        return has_permission
    
    def has_object_permission(self, request, view, obj):
        """
        🔍 Проверка конкретного сокровища
        """
        if not request.user.is_authenticated:
            return False
        
        # Базовый доступ должен быть
        if not hasattr(request, 'current_store') or not request.current_store:
            return False
        
        # Сокровище должно принадлежать твоему царству
        if hasattr(obj, 'store') and obj.store != request.current_store:
            logger.debug(f"🚫 {obj} принадлежит другому дому")
            return False
        
        # Чтение — всегда приветствуется
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return True
        
        # Изменения требуют специального благословения
        required_permission = self._get_permission_for_method(request.method)
        return self._check_user_permission(request.user, required_permission)
    
    def _check_user_permission(self, user, permission_name: str) -> bool:
        """
        🎭 Проверяет конкретное разрешение пользователя
        """
        # Базовый доступ к магазину
        current_store = getattr(user, 'current_store', None)
        if not current_store or not store_access_service._user_has_access_to_store(user, current_store):
            return False
        
        # TODO: Здесь можешь добавить более сложную логику разрешений
        # Например, проверку ролей в StoreEmployee (manager, cashier, etc.)
        
        # Пока что — если есть доступ к магазину, то есть и к действию
        permissions_map = {
            'view': True,
            'add': True,   # Или проверяй: user.employee.role in ['manager', 'admin']
            'change': True,
            'delete': False  # Только для админов, например
        }
        
        return permissions_map.get(permission_name, False)
    
    def _get_permission_for_method(self, method):
        """
        🗺️ Путь от HTTP к разрешению
        """
        method_to_permission = {
            'GET': 'view',
            'POST': 'add',
            'PUT': 'change',
            'PATCH': 'change',
            'DELETE': 'delete',
            'HEAD': 'view',
            'OPTIONS': 'view'
        }
        return method_to_permission.get(method, 'view')
    
    def check_store_permission(self, user, permission_name: str, raise_exception=True):
        """
        🔑 Универсальная проверка с опцией бунта
        """
        has_access = self._check_user_permission(user, permission_name)
        
        if raise_exception and not has_access:
            raise PermissionDenied(f"Полномочий {permission_name} у тебя нет, странник")
        
        return has_access
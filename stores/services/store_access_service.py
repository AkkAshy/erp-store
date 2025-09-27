# services/store_access_service.py
import logging
from typing import Optional
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import AccessToken
from stores.models import Store, StoreEmployee

logger = logging.getLogger(__name__)
User = get_user_model()

class StoreAccessService:
    """
    🎭 Хранитель тайн магазинов — знает, куда пользователю путь открыт
    """
    
    def __init__(self):
        self._cache = {}  # Кэш для избежания повторных запросов
    
    def get_current_store(self, user, request=None) -> Optional[Store]:
        """
        🌟 Главный оракул: находит текущий магазин пользователя
        Использует несколько путей поиска, как мудрый следопыт
        """
        cache_key = f"{user.id}_current_store"
        if cache_key in self._cache:
            logger.debug(f"📦 Используем кэш для пользователя {user.username}")
            return self._cache[cache_key]
        
        # Способ 1: Из атрибутов пользователя (установлено middleware)
        if hasattr(user, 'current_store') and user.current_store:
            if self._user_has_access_to_store(user, user.current_store):
                logger.debug(f"✅ Магазин из атрибута пользователя: {user.current_store.name}")
                self._cache[cache_key] = user.current_store
                return user.current_store
            else:
                logger.warning(f"⚠️ У пользователя {user.username} нет доступа к {user.current_store.name}")

        # Способ 2: Через Employee модель
        if hasattr(user, 'employee') and user.employee and user.employee.store:
            store = user.employee.store
            if self._user_has_access_to_store(user, store):
                logger.debug(f"✅ Магазин из Employee: {store.name}")
                user.current_store = store
                self._cache[cache_key] = store
                return store

        # Способ 3: Из JWT токена напрямую
        if request:
            try:
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                    decoded_token = AccessToken(token)
                    store_id = decoded_token.get('store_id')

                    if store_id:
                        store = Store.objects.get(id=store_id, is_active=True)
                        if self._user_has_access_to_store(user, store):
                            logger.debug(f"✅ Магазин из JWT: {store.name}")
                            user.current_store = store
                            self._cache[cache_key] = store
                            return store
                        else:
                            logger.warning(f"⚠️ Нет доступа к магазину из JWT: {store.name}")
            except Exception as e:
                logger.debug(f"Не удалось получить магазин из JWT: {e}")

        # Способ 4: Берем ПЕРВЫЙ ДОСТУПНЫЙ магазин пользователя
        accessible_stores = self._get_user_accessible_stores(user)
        if accessible_stores:
            first_store = accessible_stores.first()
            logger.debug(f"✅ Используем первый доступный магазин: {first_store.name}")
            user.current_store = first_store
            self._cache[cache_key] = first_store
            return first_store

        logger.warning(f"❌ Не найдено доступных магазинов для {user.username}")
        self._cache[cache_key] = None
        return None

    def _user_has_access_to_store(self, user, store) -> bool:
        """🔑 Проверяет, есть ли у пользователя ключ к этому магазину"""
        return StoreEmployee.objects.filter(
            user=user,
            store=store,
            is_active=True
        ).exists()

    def _get_user_accessible_stores(self, user):
        """🗺️ Карта доступных территорий пользователя"""
        accessible_store_ids = StoreEmployee.objects.filter(
            user=user,
            is_active=True
        ).values_list('store_id', flat=True)

        return Store.objects.filter(
            id__in=accessible_store_ids,
            is_active=True
        )

    def clear_cache_for_user(self, user):
        """🧹 Очищает кэш для пользователя (полезно после смены магазина)"""
        cache_key = f"{user.id}_current_store"
        if cache_key in self._cache:
            del self._cache[cache_key]
            logger.debug(f"🧹 Кэш очищен для пользователя {user.username}")

    def get_user_stores_info(self, user) -> dict:
        """📊 Информация о доступных магазинах пользователя"""
        accessible_stores = self._get_user_accessible_stores(user)
        return {
            'total_count': accessible_stores.count(),
            'store_names': list(accessible_stores.values_list('name', flat=True)),
            'has_access': accessible_stores.exists()
        }


# 🎪 Глобальный экземпляр сервиса (как единый центр управления)
store_access_service = StoreAccessService()
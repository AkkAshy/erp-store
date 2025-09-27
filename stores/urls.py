# stores/urls.py (ПОЛНАЯ ВЕРСИЯ)
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.http import JsonResponse
from .views import (
    StoreViewSet, CreateUserForStoreView, SwitchStoreView,
    simple_store_register, simple_refresh_token, DebugTokenView,
    DebugStoreAccessView
)

# Отладочный view
def debug_urls(request):
    return JsonResponse({
        'message': 'Stores URLs работают!',
        'available_endpoints': [
            '/api/stores/register/ (POST) - Регистрация магазина',
            '/api/stores/refresh-token/ (POST) - Обновление токена',
            '/api/stores/debug/ (GET) - Этот endpoint',
            '/api/stores/ (GET) - Список магазинов (требует авторизацию)',
            '/api/stores/{id}/ (GET/PUT/PATCH/DELETE) - Управление магазином',
            '/api/stores/{id}/employees/ (GET) - Список сотрудников',
            '/api/stores/{id}/add_employee/ (POST) - Добавить сотрудника',
            '/api/stores/{id}/remove_employee/ (DELETE) - Удалить сотрудника',
            '/api/stores/{id}/statistics/ (GET) - Статистика магазина',
            '/api/stores/current/ (GET) - Текущий магазин',
            '/api/stores/switch-store/ (POST) - Переключение магазина',
            '/api/stores/create-user/ (POST) - Создать пользователя',
        ]
    })

router = DefaultRouter()
router.register(r'', StoreViewSet, basename='store')

urlpatterns = [
    # ✅ ОТЛАДОЧНЫЙ endpoint
    path('debug/', debug_urls, name='debug-urls'),
    path('debug-access/', DebugStoreAccessView.as_view(), name='debug-store-access'),

    # ✅ ПРОСТЫЕ функции без DRF (без аутентификации)
    path('register/', simple_store_register, name='simple-store-register'),
    path('refresh-token/', simple_refresh_token, name='simple-refresh-token'),

    path('debug-token/', DebugTokenView.as_view(), name='debug-token'),

    # ✅ DRF views (с аутентификацией)
    path('switch-store/', SwitchStoreView.as_view(), name='switch-store'),
    path('create-user/', CreateUserForStoreView.as_view(), name='create-store-user'),

    # ✅ ViewSet через роутер
    path('', include(router.urls)),
]
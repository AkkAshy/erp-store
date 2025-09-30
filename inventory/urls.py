# inventory/urls.py - ОБНОВЛЕННАЯ ВЕРСИЯ
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'inventory'

# Создаем роутер для ViewSets
router = DefaultRouter()
router.register(r'analytics/payments', views.PaymentAnalyticsViewSet, basename='payment-analytics')
router.register(r'analytics/sizes', views.SizeAnalyticsViewSet, basename='size-analytics')
router.register(r'analytics/financial-summary', views.FinancialSummaryViewSet, basename='financial-summary')
router.register(r'categories', views.ProductCategoryViewSet, basename='productcategory')
router.register(r'attribute-types', views.AttributeTypeViewSet, basename='attributetype')
router.register(r'attribute-values', views.AttributeValueViewSet, basename='attributevalue')
router.register(r'products', views.ProductViewSet, basename='product')
router.register(r'batches', views.ProductBatchViewSet, basename='productbatch')
router.register(r'stock', views.StockViewSet, basename='stock')
router.register(r'size-info', views.SizeInfoViewSet, basename='sizeinfo')
router.register(r'custom-units', views.CustomUnitViewSet, basename='customunit')  # ← НОВЫЙ
router.register(r'stock-history', views.StockHistoryViewSet, basename='stock-history')
router.register(r'documents', views.DocumentViewSet, basename='document')

urlpatterns = [
    # ViewSets через роутер
    path('', include(router.urls)),

    # Дополнительные эндпоинты
    path('stats/', views.InventoryStatsView.as_view(), name='inventory-stats'),
    path('media/<path:path>', views.serve_media, name='serve_media'),
    path("products/<int:pk>/label/", views.product_label_proxy, name="product_label_proxy"),
]

"""
ОБНОВЛЕННЫЙ список доступных эндпоинтов:

КАТЕГОРИИ:
- GET    categories/                    - Список всех категорий
- POST   categories/                    - Создать категорию
- GET    categories/{id}/               - Получить категорию
- PUT    categories/{id}/               - Обновить категорию
- PATCH  categories/{id}/               - Частично обновить
- DELETE categories/{id}/               - Удалить категорию (soft delete)
- GET    categories/deleted/            - Список удаленных категорий
- POST   categories/{id}/restore/       - Восстановить удаленную категорию
- DELETE categories/{id}/hard_delete/   - Окончательное удаление (только админы)

ПОЛЬЗОВАТЕЛЬСКИЕ ЕДИНИЦЫ ИЗМЕРЕНИЯ (НОВОЕ):
- GET    custom-units/                  - Список пользовательских единиц
- POST   custom-units/                  - Создать единицу измерения
- GET    custom-units/{id}/             - Получить единицу
- PUT    custom-units/{id}/             - Обновить единицу
- PATCH  custom-units/{id}/             - Частично обновить
- DELETE custom-units/{id}/             - Удалить единицу
- GET    custom-units/presets/          - Получить предустановленные шаблоны

РАЗМЕРНАЯ ИНФОРМАЦИЯ (ОБНОВЛЕНО):
- GET    size-info/                     - Список размерной информации
- POST   size-info/                     - Создать размерную информацию
- GET    size-info/{id}/                - Получить размерную информацию
- PUT    size-info/{id}/                - Обновить размерную информацию
- PATCH  size-info/{id}/                - Частично обновить
- DELETE size-info/{id}/                - Удалить (soft delete)
- GET    size-info/deleted/             - Список удаленных размеров
- POST   size-info/{id}/restore/        - Восстановить удаленный размер
- DELETE size-info/{id}/hard_delete/    - Окончательное удаление
- GET    size-info/by_category/         - Размеры по категориям
- POST   size-info/import_standard_sizes/ - Импорт стандартных размеров

ТОВАРЫ (ОБНОВЛЕНО):
- GET    products/                      - Список товаров
- POST   products/                      - Создать товар/добавить партию
- GET    products/{id}/                 - Получить товар
- PUT    products/{id}/                 - Обновить товар
- PATCH  products/{id}/                 - Частично обновить товар
- DELETE products/{id}/                 - Удалить товар (soft delete)
- GET    products/scan_barcode/?barcode=123 - Сканировать штрих-код
- POST   products/{id}/sell/            - Продать товар
- GET    products/low_stock/            - Товары с низким остатком
- POST   products/create_multi_size/    - Создать товары с размерами
- GET    products/available_sizes/      - Доступные размеры
- GET    products/product_sizes_info/   - Информация о размерах товаров
- GET    products/sizes_summary/        - Сводка по размерам
- POST   products/check_sizes/          - Проверить размеры товаров
- POST   products/{id}/restore/         - Восстановить товар
- GET    products/deleted/              - Удаленные товары
- DELETE products/{id}/force_delete/    - Принудительное удаление
- GET    products/units_info/           - Информация о единицах измерения (НОВОЕ)
- GET    products/pricing_analysis/     - Анализ ценообразования (НОВОЕ)
- POST   products/{id}/update_pricing/  - Обновить цену товара (НОВОЕ)
- POST   products/bulk_update_pricing/  - Массовое обновление цен (НОВОЕ)

ПАРТИИ ТОВАРОВ (ОБНОВЛЕНО):
- GET    batches/                       - Список партий
- POST   batches/                       - Создать партию
- GET    batches/{id}/                  - Получить партию
- PUT    batches/{id}/                  - Обновить партию
- PATCH  batches/{id}/                  - Частично обновить партию
- DELETE batches/{id}/                  - Удалить партию
- GET    batches/expiring_soon/         - Партии с истекающим сроком

ОСТАТКИ НА СКЛАДЕ:
- GET    stock/                         - Список остатков
- POST   stock/                         - Создать остаток
- GET    stock/{id}/                    - Получить остаток
- PUT    stock/{id}/                    - Обновить остаток
- PATCH  stock/{id}/                    - Частично обновить остаток
- DELETE stock/{id}/                    - Удалить остаток
- GET    stock/summary/                 - Сводка по остаткам
- POST   stock/{id}/adjust/             - Корректировка остатков

ТИПЫ АТРИБУТОВ:
- GET    attribute-types/               - Список типов атрибутов
- POST   attribute-types/               - Создать тип атрибута
- GET    attribute-types/{id}/          - Получить тип атрибута
- PUT    attribute-types/{id}/          - Обновить тип атрибута
- PATCH  attribute-types/{id}/          - Частично обновить
- DELETE attribute-types/{id}/          - Удалить тип атрибута
- GET    attribute-types/for_product_creation/ - Атрибуты для создания товара

ЗНАЧЕНИЯ АТРИБУТОВ:
- GET    attribute-values/              - Список значений атрибутов
- POST   attribute-values/              - Создать значение атрибута
- GET    attribute-values/{id}/         - Получить значение атрибута
- PUT    attribute-values/{id}/         - Обновить значение атрибута
- PATCH  attribute-values/{id}/         - Частично обновить
- DELETE attribute-values/{id}/         - Удалить значение атрибута

СТАТИСТИКА (ОБНОВЛЕНО):
- GET    stats/                         - Расширенная статистика склада

МЕДИА:
- GET    media/<path>                   - Получить медиа файл
- GET    products/{id}/label/           - Получить этикетку товара

НОВЫЕ ВОЗМОЖНОСТИ:
✅ Пользовательские единицы измерения
✅ Обновленная система размеров с параметрами
✅ Анализ ценообразования и наценок
✅ Массовое обновление цен
✅ Импорт стандартных размеров для сантехники
✅ Soft delete для категорий и размеров
✅ Группировка размеров по категориям
"""

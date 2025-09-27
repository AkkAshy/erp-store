# inventory/filters.py - ОБНОВЛЕННАЯ ВЕРСИЯ
import django_filters
from django_filters import rest_framework as filters
from django.db.models import Q
from .models import Product, ProductBatch, Stock, AttributeType, AttributeValue, SizeInfo, CustomUnit


class CustomUnitFilter(django_filters.FilterSet):
    """
    Фильтры для пользовательских единиц измерения
    """
    name = django_filters.CharFilter(
        lookup_expr='icontains',
        label='Название содержит'
    )
    
    short_name = django_filters.CharFilter(
        lookup_expr='icontains',
        label='Сокращение содержит'
    )
    
    allow_decimal = django_filters.BooleanFilter(
        label='Разрешает дробные значения'
    )
    
    min_quantity_range = django_filters.RangeFilter(
        field_name='min_quantity',
        label='Диапазон минимального количества'
    )

    class Meta:
        model = CustomUnit
        fields = ['name', 'short_name', 'allow_decimal', 'min_quantity_range']


class SizeInfoFilter(filters.FilterSet):
    """
    ОБНОВЛЕННЫЙ фильтр для размерной информации с новыми полями
    """
    # Фильтр по размеру
    size = filters.CharFilter(
        lookup_expr='icontains',
        label='Размер (содержит)'
    )
    
    size_exact = filters.CharFilter(
        field_name='size',
        lookup_expr='exact',
        label='Размер (точное совпадение)'
    )
    
    # Фильтры по новым параметрам
    dimension1_min = filters.NumberFilter(
        field_name='dimension1',
        lookup_expr='gte',
        label='Минимальный параметр 1'
    )
    dimension1_max = filters.NumberFilter(
        field_name='dimension1',
        lookup_expr='lte',
        label='Максимальный параметр 1'
    )
    dimension1_range = filters.RangeFilter(
        field_name='dimension1',
        label='Диапазон параметра 1'
    )
    
    dimension2_min = filters.NumberFilter(
        field_name='dimension2',
        lookup_expr='gte',
        label='Минимальный параметр 2'
    )
    dimension2_max = filters.NumberFilter(
        field_name='dimension2',
        lookup_expr='lte',
        label='Максимальный параметр 2'
    )
    dimension2_range = filters.RangeFilter(
        field_name='dimension2',
        label='Диапазон параметра 2'
    )
    
    dimension3_min = filters.NumberFilter(
        field_name='dimension3',
        lookup_expr='gte',
        label='Минимальный параметр 3'
    )
    dimension3_max = filters.NumberFilter(
        field_name='dimension3',
        lookup_expr='lte',
        label='Максимальный параметр 3'
    )
    dimension3_range = filters.RangeFilter(
        field_name='dimension3',
        label='Диапазон параметра 3'
    )
    
    # Фильтр по описанию
    description = filters.CharFilter(
        lookup_expr='icontains',
        label='Описание содержит'
    )
    
    # Фильтр для пустых значений
    has_dimension1 = filters.BooleanFilter(
        field_name='dimension1',
        lookup_expr='isnull',
        exclude=True,
        label='Есть параметр 1'
    )
    has_dimension2 = filters.BooleanFilter(
        field_name='dimension2',
        lookup_expr='isnull',
        exclude=True,
        label='Есть параметр 2'
    )
    has_dimension3 = filters.BooleanFilter(
        field_name='dimension3',
        lookup_expr='isnull',
        exclude=True,
        label='Есть параметр 3'
    )
    
    # Фильтр по порядку сортировки
    sort_order_range = filters.RangeFilter(
        field_name='sort_order',
        label='Диапазон порядка сортировки'
    )

    class Meta:
        model = SizeInfo
        fields = {
            'size': ['exact', 'icontains'],
            'dimension1': ['exact', 'gte', 'lte', 'range'],
            'dimension2': ['exact', 'gte', 'lte', 'range'],
            'dimension3': ['exact', 'gte', 'lte', 'range'],
            'sort_order': ['exact', 'gte', 'lte', 'range'],
        }

    def filter_by_measurements(self, queryset, name, value):
        """
        Кастомный фильтр для поиска по приближенным размерам
        """
        if value:
            # Логика для поиска подходящих размеров по параметрам
            return queryset.filter(
                dimension1__lte=value + 5,
                dimension1__gte=value - 5
            )
        return queryset


class ProductFilter(django_filters.FilterSet):
    """
    ОБНОВЛЕННЫЙ фильтр для товаров с новой системой единиц измерения
    """
    name = django_filters.CharFilter(lookup_expr='icontains', label='Название содержит')
    barcode = django_filters.CharFilter(lookup_expr='exact', label='Точный штрих-код')
    category = django_filters.NumberFilter(field_name='category', label='Категория')

    # --- фильтры по создателю ---
    created_by = django_filters.NumberFilter(
        field_name='created_by__id',
        lookup_expr='exact',
        label='ID создателя'
    )
    created_by_username = django_filters.CharFilter(
        field_name='created_by__username',
        lookup_expr='iexact',
        label='Имя создателя'
    )

    # ========== ФИЛЬТРАЦИЯ ПО ЕДИНИЦАМ ИЗМЕРЕНИЯ ==========
    
    # Системные единицы
    unit_type = django_filters.ChoiceFilter(
        choices=Product.SYSTEM_UNITS,
        label='Системная единица измерения'
    )
    
    # Пользовательские единицы
    custom_unit = django_filters.ModelChoiceFilter(
        queryset=CustomUnit.objects.all(),
        label='Пользовательская единица'
    )
    
    custom_unit_name = django_filters.CharFilter(
        field_name='custom_unit__name',
        lookup_expr='icontains',
        label='Название пользовательской единицы'
    )
    
    # Товары с переопределенными настройками
    has_override_min = django_filters.BooleanFilter(
        field_name='override_min_quantity',
        lookup_expr='isnull',
        exclude=True,
        label='Есть переопределение минимума'
    )
    
    has_override_step = django_filters.BooleanFilter(
        field_name='override_step',
        lookup_expr='isnull',
        exclude=True,
        label='Есть переопределение шага'
    )

    # ========== ФИЛЬТРАЦИЯ ПО РАЗМЕРАМ ==========

    # Товары с размерами
    has_sizes = django_filters.BooleanFilter(
        label='Имеет размеры/варианты'
    )
    
    # Фильтр по основному размеру
    default_size = django_filters.ModelChoiceFilter(
        queryset=SizeInfo.objects.all(),
        label='Основной размер'
    )
    
    default_size_name = django_filters.CharFilter(
        field_name='default_size__size',
        lookup_expr='icontains',
        label='Название основного размера'
    )
    
    # Фильтр по доступным размерам
    available_sizes = django_filters.ModelMultipleChoiceFilter(
        queryset=SizeInfo.objects.all(),
        label='Доступные размеры'
    )
    
    # Кастомный фильтр для поиска подходящего размера по параметрам
    suitable_size = django_filters.CharFilter(
        method='filter_suitable_size',
        label='Подходящий размер (param1,param2,param3)'
    )

    # ========== СТАРЫЕ ФИЛЬТРЫ ПО АТРИБУТАМ ==========

    brand = django_filters.ModelChoiceFilter(
        queryset=AttributeValue.objects.filter(attribute_type__slug='brand'),
        field_name='attributes',
        label='Бренд'
    )

    color = django_filters.ModelChoiceFilter(
        queryset=AttributeValue.objects.filter(attribute_type__slug='color'),
        field_name='attributes',
        label='Цвет'
    )

    # --- фильтрация по остаткам ---
    min_stock = django_filters.NumberFilter(
        field_name='stock__quantity',
        lookup_expr='gte',
        label='Минимальный остаток'
    )

    max_stock = django_filters.NumberFilter(
        field_name='stock__quantity',
        lookup_expr='lte',
        label='Максимальный остаток'
    )

    # --- фильтрация по цене ---
    min_price = django_filters.NumberFilter(
        field_name='sale_price',
        lookup_expr='gte',
        label='Минимальная цена'
    )

    max_price = django_filters.NumberFilter(
        field_name='sale_price',
        lookup_expr='lte',
        label='Максимальная цена'
    )

    # --- специальные фильтры ---
    has_stock = django_filters.BooleanFilter(
        method='filter_has_stock',
        label='Есть на складе'
    )

    low_stock = django_filters.BooleanFilter(
        method='filter_low_stock',
        label='Низкий остаток'
    )
    
    # Фильтр по удаленным товарам
    include_deleted = django_filters.BooleanFilter(
        method='filter_include_deleted',
        label='Включить удаленные товары'
    )

    class Meta:
        model = Product
        fields = [
            'name', 'barcode', 'category',
            # Единицы измерения
            'unit_type', 'custom_unit', 'custom_unit_name',
            'has_override_min', 'has_override_step',
            # Размеры
            'has_sizes', 'default_size', 'default_size_name',
            'available_sizes', 'suitable_size',
            # Старые поля
            'brand', 'color',
            'min_stock', 'max_stock', 'min_price', 'max_price',
            'has_stock', 'low_stock', 'created_by', 'created_by_username',
            'include_deleted'
        ]

    def filter_has_stock(self, queryset, name, value):
        if value:
            return queryset.filter(stock__quantity__gt=0)
        return queryset.filter(stock__quantity=0)

    def filter_low_stock(self, queryset, name, value):
        if value:
            return queryset.filter(stock__quantity__lte=10, stock__quantity__gt=0)
        return queryset

    def filter_suitable_size(self, queryset, name, value):
        """
        Кастомный фильтр для поиска подходящих размеров по параметрам
        Формат: "param1,param2,param3" например "15,20,2.5"
        """
        if not value:
            return queryset

        try:
            params = value.split(',')
            if len(params) != 3:
                return queryset

            dimension1 = float(params[0]) if params[0] else None
            dimension2 = float(params[1]) if params[1] else None
            dimension3 = float(params[2]) if params[2] else None

            # Создаем Q-объекты для фильтрации с допуском ±5%
            q_filter = Q()

            if dimension1:
                tolerance = dimension1 * 0.05  # 5% допуск
                q_filter &= Q(
                    default_size__dimension1__gte=dimension1-tolerance, 
                    default_size__dimension1__lte=dimension1+tolerance
                )
            if dimension2:
                tolerance = dimension2 * 0.05
                q_filter &= Q(
                    default_size__dimension2__gte=dimension2-tolerance, 
                    default_size__dimension2__lte=dimension2+tolerance
                )
            if dimension3:
                tolerance = dimension3 * 0.05
                q_filter &= Q(
                    default_size__dimension3__gte=dimension3-tolerance, 
                    default_size__dimension3__lte=dimension3+tolerance
                )

            return queryset.filter(q_filter)

        except (ValueError, TypeError):
            return queryset

    def filter_include_deleted(self, queryset, name, value):
        """Включить или исключить удаленные товары"""
        if value:
            # Используем all_objects для получения всех товаров включая удаленные
            return Product.all_objects.filter(
                store=queryset.first().store if queryset.exists() else None
            )
        return queryset  # По умолчанию возвращает только активные


class ProductBatchFilter(django_filters.FilterSet):
    """
    ОБНОВЛЕННЫЙ фильтр для партий товаров
    """
    product_name = django_filters.CharFilter(
        field_name='product__name',
        lookup_expr='icontains',
        label='Название товара'
    )

    supplier = django_filters.CharFilter(
        lookup_expr='icontains',
        label='Поставщик'
    )
    
    # Фильтр по размеру партии
    size = django_filters.ModelChoiceFilter(
        queryset=SizeInfo.objects.all(),
        label='Размер'
    )
    
    size_name = django_filters.CharFilter(
        field_name='size__size',
        lookup_expr='icontains',
        label='Название размера'
    )

    min_quantity = django_filters.NumberFilter(
        field_name='quantity',
        lookup_expr='gte',
        label='Минимальное количество'
    )

    max_quantity = django_filters.NumberFilter(
        field_name='quantity',
        lookup_expr='lte',
        label='Максимальное количество'
    )
    
    # Фильтры по цене закупки
    min_purchase_price = django_filters.NumberFilter(
        field_name='purchase_price',
        lookup_expr='gte',
        label='Минимальная цена закупки'
    )

    max_purchase_price = django_filters.NumberFilter(
        field_name='purchase_price',
        lookup_expr='lte',
        label='Максимальная цена закупки'
    )

    created_from = django_filters.DateFilter(
        field_name='created_at',
        lookup_expr='gte',
        label='Создано с'
    )

    created_to = django_filters.DateFilter(
        field_name='created_at',
        lookup_expr='lte',
        label='Создано до'
    )

    expires_from = django_filters.DateFilter(
        field_name='expiration_date',
        lookup_expr='gte',
        label='Истекает с'
    )

    expires_to = django_filters.DateFilter(
        field_name='expiration_date',
        lookup_expr='lte',
        label='Истекает до'
    )

    expiring_soon = django_filters.BooleanFilter(
        method='filter_expiring_soon',
        label='Истекает скоро'
    )
    
    # Фильтр по товарам с размерами
    has_size = django_filters.BooleanFilter(
        field_name='size',
        lookup_expr='isnull',
        exclude=True,
        label='Есть размер'
    )

    class Meta:
        model = ProductBatch
        fields = [
            'product', 'product_name', 'supplier', 'size', 'size_name',
            'min_quantity', 'max_quantity', 'min_purchase_price', 'max_purchase_price',
            'created_from', 'created_to', 'expires_from', 'expires_to', 
            'expiring_soon', 'has_size'
        ]

    def filter_expiring_soon(self, queryset, name, value):
        if value:
            from datetime import date, timedelta
            expiry_date = date.today() + timedelta(days=7)
            return queryset.filter(
                expiration_date__lte=expiry_date,
                expiration_date__isnull=False
            )
        return queryset


class StockFilter(django_filters.FilterSet):
    """
    ОБНОВЛЕННЫЙ фильтр для остатков на складе
    """
    product_name = django_filters.CharFilter(
        field_name='product__name',
        lookup_expr='icontains',
        label='Название товара'
    )

    product_barcode = django_filters.CharFilter(
        field_name='product__barcode',
        lookup_expr='exact',
        label='Штрих-код товара'
    )

    category = django_filters.NumberFilter(
        field_name='product__category',
        label='Категория'
    )
    
    # Фильтр по единицам измерения
    unit_type = django_filters.ChoiceFilter(
        field_name='product__unit_type',
        choices=Product.SYSTEM_UNITS,
        label='Системная единица измерения'
    )
    
    custom_unit = django_filters.ModelChoiceFilter(
        field_name='product__custom_unit',
        queryset=CustomUnit.objects.all(),
        label='Пользовательская единица'
    )
    
    # Фильтры по размерам товара
    product_has_sizes = django_filters.BooleanFilter(
        field_name='product__has_sizes',
        label='Товар имеет размеры'
    )
    
    product_default_size = django_filters.ModelChoiceFilter(
        field_name='product__default_size',
        queryset=SizeInfo.objects.all(),
        label='Основной размер товара'
    )

    min_quantity = django_filters.NumberFilter(
        field_name='quantity',
        lookup_expr='gte',
        label='Минимальное количество'
    )

    max_quantity = django_filters.NumberFilter(
        field_name='quantity',
        lookup_expr='lte',
        label='Максимальное количество'
    )

    zero_stock = django_filters.BooleanFilter(
        method='filter_zero_stock',
        label='Нулевой остаток'
    )

    low_stock = django_filters.BooleanFilter(
        method='filter_low_stock',
        label='Низкий остаток'
    )

    class Meta:
        model = Stock
        fields = [
            'product', 'product_name', 'product_barcode', 'category',
            'unit_type', 'custom_unit', 'product_has_sizes', 'product_default_size',
            'min_quantity', 'max_quantity', 'zero_stock', 'low_stock'
        ]

    def filter_zero_stock(self, queryset, name, value):
        if value:
            return queryset.filter(quantity=0)
        return queryset.filter(quantity__gt=0)

    def filter_low_stock(self, queryset, name, value):
        if value:
            return queryset.filter(quantity__lte=10, quantity__gt=0)
        return queryset


# ========== РАСШИРЕННЫЕ ФИЛЬТРЫ ==========

class AdvancedProductFilter(ProductFilter):
    """
    Расширенный фильтр с дополнительными возможностями
    """

    # Комбинированный поиск по размерам
    any_size = django_filters.CharFilter(
        method='filter_any_size',
        label='Размер (поиск везде)'
    )

    # Фильтр по размерному диапазону для труб
    diameter_range = django_filters.CharFilter(
        method='filter_diameter_range',
        label='Диапазон диаметров (например: 15-25)'
    )
    
    # Поиск по всем параметрам размера
    dimension_search = django_filters.CharFilter(
        method='filter_dimension_search',
        label='Поиск по любому параметру размера'
    )

    def filter_any_size(self, queryset, name, value):
        """
        Ищет размер в названии размера и в описании
        """
        if not value:
            return queryset

        return queryset.filter(
            Q(default_size__size__icontains=value) |
            Q(default_size__description__icontains=value) |
            Q(available_sizes__size__icontains=value) |
            Q(available_sizes__description__icontains=value)
        ).distinct()

    def filter_diameter_range(self, queryset, name, value):
        """
        Фильтрует по диапазону диаметров (например: 15-25 вернет все диаметры от 15 до 25)
        """
        if not value or '-' not in value:
            return queryset

        try:
            start_diameter, end_diameter = value.split('-')
            start_diameter = float(start_diameter.strip())
            end_diameter = float(end_diameter.strip())

            if start_diameter > end_diameter:
                start_diameter, end_diameter = end_diameter, start_diameter

            return queryset.filter(
                Q(default_size__dimension1__gte=start_diameter, default_size__dimension1__lte=end_diameter) |
                Q(default_size__dimension2__gte=start_diameter, default_size__dimension2__lte=end_diameter)
            )

        except (ValueError, IndexError):
            return queryset

    def filter_dimension_search(self, queryset, name, value):
        """
        Поиск по любому из параметров размера
        """
        if not value:
            return queryset

        try:
            search_value = float(value)
            tolerance = search_value * 0.1  # 10% допуск

            return queryset.filter(
                Q(default_size__dimension1__gte=search_value-tolerance, default_size__dimension1__lte=search_value+tolerance) |
                Q(default_size__dimension2__gte=search_value-tolerance, default_size__dimension2__lte=search_value+tolerance) |
                Q(default_size__dimension3__gte=search_value-tolerance, default_size__dimension3__lte=search_value+tolerance)
            ).distinct()

        except (ValueError, TypeError):
            # Если не число, ищем по тексту
            return queryset.filter(
                Q(default_size__size__icontains=value) |
                Q(default_size__description__icontains=value)
            ).distinct()
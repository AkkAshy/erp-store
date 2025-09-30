# inventory/serializers.py - ОБНОВЛЕННАЯ ВЕРСИЯ
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from drf_yasg.utils import swagger_serializer_method
from django.db import transaction
from decimal import Decimal

from .models import (Product, ProductCategory, Stock,
                     ProductBatch, AttributeType,
                     AttributeValue, ProductAttribute,
                     SizeChart, SizeInfo, CustomUnit,
                     ProductBatchAttribute, StockHistory,
                     FinancialSummary, Document
                     )
from users.serializers import UserSerializer
import logging
from stores.mixins import StoreSerializerMixin


logger = logging.getLogger('inventory')


class StockHistorySerializer(serializers.ModelSerializer):
    """
    ✅ СЕРИАЛИЗАТОР ДЛЯ StockHistory — полный доступ к истории стока
    """
    # Читаемые поля — для удобства в API
    product_name = serializers.CharField(source='product.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    size_name = serializers.CharField(source='size.size', read_only=True, allow_null=True)
    cashier_name = serializers.CharField(source='user.get_full_name', read_only=True, allow_null=True)
    batch_name = serializers.CharField(source='batch.supplier', read_only=True, allow_null=True)
    
    # Форматированные поля
    timestamp_formatted = serializers.DateTimeField(
        source='timestamp', 
        format='%Y-%m-%d %H:%M:%S', 
        read_only=True
    )
    date_only_formatted = serializers.DateField(
        source='date_only', 
        format='%Y-%m-%d', 
        read_only=True
    )
    
    # Финансовые метрики (вычисляемые)
    line_value = serializers.SerializerMethodField()
    margin = serializers.SerializerMethodField()
    
    class Meta:
        model = StockHistory
        fields = [
            'id', 'timestamp', 'timestamp_formatted', 'date_only', 'date_only_formatted',
            'product', 'product_name', 'store', 'store_name', 
            'batch', 'batch_name', 'size', 'size_name',
            'operation_type', 'quantity_before', 'quantity_after', 
            'quantity_change', 'line_value', 'margin',
            'reference_id', 'user', 'cashier_name', 'notes', 'is_automatic'
        ]
        read_only_fields = [
            'id', 'timestamp', 'date_only', 'quantity_before', 'quantity_after',
            'quantity_change', 'reference_id', 'user', 'is_automatic'
        ]
        extra_kwargs = {
            'product': {'read_only': True},
            'store': {'read_only': True},
            'batch': {'read_only': True},
            'size': {'read_only': True},
        }
    
    def get_line_value(self, obj):
        """✅ Вычисляемая стоимость операции"""
        if obj.operation_type == 'SALE':
            return float(obj.quantity_change * -1 * obj.sale_price_at_time) if obj.sale_price_at_time else 0
        elif obj.operation_type == 'INCOMING':
            return float(obj.quantity_change * obj.purchase_price_at_time) if obj.purchase_price_at_time else 0
        return 0
    
    def get_margin(self, obj):
        """✅ Маржа операции (для продаж)"""
        if obj.operation_type == 'SALE' and obj.sale_price_at_time and obj.purchase_price_at_time:
            qty_sold = abs(obj.quantity_change)
            revenue = qty_sold * obj.sale_price_at_time
            cost = qty_sold * obj.purchase_price_at_time
            return float((revenue - cost) / revenue * 100) if revenue > 0 else 0
        return None


class StockHistorySummarySerializer(serializers.Serializer):
    """
    ✅ СВОДКА ПО ИСТОРИИ СТОКА — для дашбордов
    """
    period_days = serializers.IntegerField()
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    
    # Метрики
    total_movements = serializers.IntegerField()
    total_incoming = serializers.DecimalField(max_digits=12, decimal_places=3)
    total_sales = serializers.DecimalField(max_digits=12, decimal_places=3)
    net_stock_change = serializers.DecimalField(max_digits=12, decimal_places=3)
    current_stock = serializers.DecimalField(max_digits=12, decimal_places=3)
    
    # Финансовые
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_margin = serializers.DecimalField(max_digits=12, decimal_places=2)
    margin_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    
    # Аналитика
    stockout_days = serializers.IntegerField()
    stockout_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    inventory_turnover = serializers.DecimalField(max_digits=10, decimal_places=2)
    days_of_stock = serializers.DecimalField(max_digits=5, decimal_places=1)
    
    # Разбивка по операциям
    operation_breakdown = serializers.ListField(child=serializers.DictField())
    
    def __init__(self, *args, **kwargs):
        # Можно передать данные напрямую
        data = kwargs.pop('data', {})
        super().__init__(data=data, **kwargs)

class FinancialSummarySerializer(serializers.ModelSerializer):
    """
    Сериализатор для финансовой сводки с правильным преобразованием типов
    """
    
    # Явно определяем поля как DecimalField для правильной сериализации
    grand_total = serializers.DecimalField(max_digits=20, decimal_places=2, coerce_to_string=False)
    cash_total = serializers.DecimalField(max_digits=20, decimal_places=2, coerce_to_string=False)
    card_total = serializers.DecimalField(max_digits=20, decimal_places=2, coerce_to_string=False)
    transfer_total = serializers.DecimalField(max_digits=20, decimal_places=2, coerce_to_string=False)
    total_margin = serializers.DecimalField(max_digits=20, decimal_places=2, coerce_to_string=False)
    margin_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=False)
    avg_transaction = serializers.DecimalField(max_digits=20, decimal_places=2, coerce_to_string=False)
    grand_total_usd = serializers.SerializerMethodField()
    total_margin_usd = serializers.SerializerMethodField()
    
    # Целочисленные поля
    total_transactions = serializers.IntegerField()
    unique_customers = serializers.IntegerField(required=False, allow_null=True)
    
    # Дополнительные вычисляемые поля
    cash_percentage = serializers.SerializerMethodField()
    card_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = FinancialSummary
        fields = [
            'id', 'store', 'date',
            'grand_total', 'cash_total', 'card_total', 'transfer_total',
            'total_margin', 'margin_percentage',
            'total_transactions', 'avg_transaction', 'unique_customers',
            'cash_percentage', 'card_percentage',
            'created_at', 'updated_at', "total_margin_usd",
             "grand_total_usd"
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    
    def get_usd_rate(self, obj):
        from .models import ExchangeRate
        try:
            rate_obj = ExchangeRate.objects.get(date=obj.date)
            return rate_obj.usd_rate
        except ExchangeRate.DoesNotExist:
            rate_obj = ExchangeRate.objects.filter(date__lte=obj.date).order_by('-date').first()
            return rate_obj.usd_rate if rate_obj else Decimal('0')

    def get_grand_total_usd(self, obj):
        usd_rate = self.get_usd_rate(obj)
        return float(obj.grand_total / usd_rate) if usd_rate > 0 else 0.0

    def get_total_margin_usd(self, obj):
        usd_rate = self.get_usd_rate(obj)
        return float(obj.total_margin / usd_rate) if usd_rate > 0 else 0.0

    def get_cash_percentage(self, obj):
        """Процент наличных платежей"""
        if obj.grand_total and obj.grand_total > 0:
            return float((obj.cash_total / obj.grand_total) * 100)
        return 0.0
    
    def get_card_percentage(self, obj):
        """Процент карточных платежей"""
        if obj.grand_total and obj.grand_total > 0:
            return float((obj.card_total / obj.grand_total) * 100)
        return 0.0
    
    def to_representation(self, instance):
        """
        Преобразование для гарантии правильных типов в JSON
        """
        data = super().to_representation(instance)
        
        # Гарантируем, что все decimal поля - числа, а не строки
        decimal_fields = [
            'grand_total', 'cash_total', 'card_total', 'transfer_total',
            'total_margin', 'margin_percentage', 'avg_transaction'
        ]
        
        for field in decimal_fields:
            if field in data and data[field] is not None:
                # Преобразуем в float для JSON (Decimal не сериализуется в JSON)
                data[field] = float(data[field])
        
        # Гарантируем целые числа
        int_fields = ['total_transactions', 'unique_customers']
        for field in int_fields:
            if field in data and data[field] is not None:
                data[field] = int(data[field])
        
        return data

class CustomUnitSerializer(StoreSerializerMixin, serializers.ModelSerializer):
    """
    Сериализатор для пользовательских единиц измерения
    """
    class Meta:
        model = CustomUnit
        fields = [
            'id', 'name', 'short_name', 'allow_decimal', 
            'min_quantity', 'step'
        ]
        read_only_fields = ['id']

    def validate_short_name(self, value):
        """Проверяем уникальность сокращения в рамках магазина"""
        value = value.strip()
        request = self.context.get('request')
        
        if request and hasattr(request.user, 'current_store') and request.user.current_store:
            current_store = request.user.current_store
            
            existing_query = CustomUnit.objects.filter(
                store=current_store,
                short_name__iexact=value
            )
            
            if self.instance:
                existing_query = existing_query.exclude(pk=self.instance.pk)
            
            if existing_query.exists():
                raise serializers.ValidationError(
                    f"Единица с сокращением '{value}' уже существует в вашем магазине"
                )
        
        return value


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ['id', 'name', 'created_at', 'is_deleted']
        read_only_fields = ['created_at', 'is_deleted']
        extra_kwargs = {'name': {'trim_whitespace': True}}
        ref_name = 'ProductCategorySerializerInventory'

    def validate_name(self, value):
        value = value.strip()
        request = self.context.get('request')

        if not request:
            if ProductCategory.objects.filter(name__iexact=value).exists():
                raise serializers.ValidationError(
                    _("Категория с названием '%(name)s' уже существует") % {'name': value},
                    code='duplicate_category'
                )
            return value

        # Получаем текущий магазин
        current_store = None

        if hasattr(request.user, 'current_store') and request.user.current_store:
            current_store = request.user.current_store

        if not current_store:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Bearer '):
                try:
                    from rest_framework_simplejwt.tokens import AccessToken
                    token = auth_header.split(' ')[1]
                    decoded_token = AccessToken(token)
                    store_id = decoded_token.get('store_id')

                    if store_id:
                        from stores.models import Store
                        current_store = Store.objects.filter(id=store_id).first()
                except Exception:
                    pass

            if not current_store:
                from stores.models import StoreEmployee
                store_membership = StoreEmployee.objects.filter(
                    user=request.user,
                    is_active=True
                ).select_related('store').first()

                if store_membership:
                    current_store = store_membership.store

        if not current_store:
            raise serializers.ValidationError(
                _("Не удалось определить текущий магазин"),
                code='no_store'
            )

        # Проверяем уникальность только среди АКТИВНЫХ категорий
        existing_query = ProductCategory.objects.filter(
            store=current_store,
            name__iexact=value
        )

        if self.instance:
            existing_query = existing_query.exclude(pk=self.instance.pk)

        if existing_query.exists():
            deleted_category = ProductCategory.all_objects.filter(
                store=current_store,
                name__iexact=value,
                deleted_at__isnull=False
            ).first()

            if deleted_category:
                raise serializers.ValidationError(
                    _("Категория с названием '%(name)s' была удалена. Восстановите её или выберите другое название") % {'name': value},
                    code='category_was_deleted'
                )
            else:
                raise serializers.ValidationError(
                    _("Категория с названием '%(name)s' уже существует в вашем магазине") % {'name': value},
                    code='duplicate_category_in_store'
                )

        return value

    def update(self, instance, validated_data):
        """При обновлении проверяем что категория принадлежит текущему магазину и не удалена"""
        request = self.context.get('request')
        if request and hasattr(request.user, 'current_store') and request.user.current_store:
            if instance.store != request.user.current_store:
                raise serializers.ValidationError(
                    _("Вы не можете редактировать категории другого магазина"),
                    code='wrong_store'
                )

            if instance.is_deleted:
                raise serializers.ValidationError(
                    _("Нельзя редактировать удаленную категорию"),
                    code='category_deleted'
                )

        return super().update(instance, validated_data)


class SizeInfoSerializer(StoreSerializerMixin, serializers.ModelSerializer):
    """
    ОБНОВЛЕННЫЙ сериализатор для размерной информации с новыми полями
    """
    size = serializers.CharField()
    store_name = serializers.CharField(source='store.name', read_only=True)
    full_description = serializers.CharField(read_only=True)

    class Meta:
        model = SizeInfo
        fields = [
            'id', 'size', 'dimension1', 'dimension2', 'dimension3',
            'dimension1_label', 'dimension2_label', 'dimension3_label',
            'description', 'sort_order', 'store_name', 'is_deleted',
            'full_description'
        ]
        read_only_fields = ['id', 'store_name', 'is_deleted', 'full_description']
        swagger_schema_fields = {
            'example': {
                'size': '1/2"',
                'dimension1': 15.0,
                'dimension2': 20.0,
                'dimension3': 2.5,
                'dimension1_label': 'Внутр. диаметр',
                'dimension2_label': 'Внешн. диаметр',
                'dimension3_label': 'Толщина стенки',
                'description': 'Труба полипропиленовая',
                'sort_order': 0
            }
        }

    def validate_size(self, value):
        """Валидация размера"""
        if not value or not value.strip():
            raise serializers.ValidationError("Размер не может быть пустым")

        value = value.strip()

        if len(value) > 50:
            raise serializers.ValidationError("Размер не может быть длиннее 50 символов")

        return value

    def validate(self, attrs):
        """Комплексная валидация с учетом soft delete"""
        attrs = super().validate(attrs)
        request = self.context.get('request')

        if not request:
            return attrs

        # Получаем текущий магазин
        current_store = None

        if hasattr(request.user, 'current_store') and request.user.current_store:
            current_store = request.user.current_store

        if not current_store:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Bearer '):
                try:
                    from rest_framework_simplejwt.tokens import AccessToken
                    token = auth_header.split(' ')[1]
                    decoded_token = AccessToken(token)
                    store_id = decoded_token.get('store_id')

                    if store_id:
                        from stores.models import Store
                        current_store = Store.objects.filter(id=store_id).first()
                except Exception:
                    pass

            if not current_store:
                from stores.models import StoreEmployee
                store_membership = StoreEmployee.objects.filter(
                    user=request.user,
                    is_active=True
                ).select_related('store').first()

                if store_membership:
                    current_store = store_membership.store

        if not current_store:
            raise serializers.ValidationError("Не удалось определить текущий магазин")

        size = attrs.get('size')

        # Проверяем уникальность только среди АКТИВНЫХ размеров
        existing_query = SizeInfo.objects.filter(
            store=current_store,
            size=size
        )

        if self.instance:
            existing_query = existing_query.exclude(pk=self.instance.pk)

        if existing_query.exists():
            deleted_size = SizeInfo.all_objects.filter(
                store=current_store,
                size=size,
                deleted_at__isnull=False
            ).first()

            if deleted_size:
                raise serializers.ValidationError(
                    f"Размер '{size}' был удален. Восстановите его или выберите другое название"
                )
            else:
                raise serializers.ValidationError(
                    f"Размер '{size}' уже существует в этом магазине"
                )

        return attrs

    def update(self, instance, validated_data):
        """При обновлении проверяем что размер принадлежит текущему магазину и не удален"""
        request = self.context.get('request')
        if request and hasattr(request.user, 'current_store') and request.user.current_store:
            if instance.store != request.user.current_store:
                raise serializers.ValidationError(
                    "Вы не можете редактировать размеры другого магазина"
                )

            if instance.is_deleted:
                raise serializers.ValidationError(
                    "Нельзя редактировать удаленный размер"
                )

        return super().update(instance, validated_data)


# Остальные сериализаторы остаются без изменений
class AttributeValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttributeValue
        fields = ['id', 'attribute_type', 'value', 'slug']

class AttributeTypeSerializer(serializers.ModelSerializer):
    values = AttributeValueSerializer(many=True, read_only=True)

    class Meta:
        model = AttributeType
        fields = ['id', 'name', 'slug', 'is_filterable', 'values']

class ProductAttributeSerializer(serializers.ModelSerializer):
    attribute = AttributeValueSerializer(read_only=True)
    attribute_id = serializers.PrimaryKeyRelatedField(
        queryset=AttributeValue.objects.all(),
        source='attribute',
        write_only=True,
        help_text=_('ID значения атрибута')
    )

    class Meta:
        model = ProductAttribute
        fields = ['attribute', 'attribute_id']


class SizeChartSerializer(serializers.ModelSerializer):
    class Meta:
        model = SizeChart
        fields = ['id', 'name', 'description', 'created_at']
        read_only_fields = ['created_at']



class ProductBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    size_info = serializers.SerializerMethodField()
    purchase_price_uzs = serializers.SerializerMethodField()


    

    class Meta:
        model = ProductBatch
        fields = [
            'id', 'product', 'product_name', 'quantity', 'purchase_price',
            'size_info', 'supplier', 'expiration_date', 'created_at', 'supplier_country',
            'purchase_price_usd', 'purchase_rate', 'purchase_price_uzs',
        ]

    def get_size_info(self, obj):
        """Возвращает информацию о размере"""
        if obj.size:
            return {
                'id': obj.size.id,
                'size': obj.size.size,
                'dimension1': float(obj.size.dimension1) if obj.size.dimension1 else None,
                'dimension2': float(obj.size.dimension2) if obj.size.dimension2 else None,
                'dimension3': float(obj.size.dimension3) if obj.size.dimension3 else None,
                'dimension1_label': obj.size.dimension1_label,
                'dimension2_label': obj.size.dimension2_label,
                'dimension3_label': obj.size.dimension3_label,
                'full_description': obj.size.full_description
            }
        return None

    def get_purchase_price_uzs(self, obj):
        if obj.purchase_price_usd and obj.purchase_rate:
            return float(obj.purchase_price_usd * obj.purchase_rate)
        return None

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                _("Количество должно быть больше нуля"),
                code='invalid_quantity'
            )
        return value
    
    def create(self, validated_data):
        """Создание батча с автоматическим сохранением курса"""
        from .models import ExchangeRate
        from datetime import date
        
        # Если есть USD цена и курс - сохраняем курс
        purchase_price_usd = validated_data.get('purchase_price_usd')
        purchase_rate = validated_data.get('purchase_rate')
        
        if purchase_price_usd and purchase_rate:
            # Сохраняем или обновляем курс на сегодня
            today = date.today()
            ExchangeRate.objects.update_or_create(
                date=today,
                defaults={'usd_rate': purchase_rate}
            )
            
            # Также вычисляем цену в сумах если не указана
            if not validated_data.get('purchase_price'):
                validated_data['purchase_price'] = purchase_price_usd * purchase_rate
        
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Обновление батча с автоматическим сохранением курса"""
        from .models import ExchangeRate
        from datetime import date
        
        purchase_price_usd = validated_data.get('purchase_price_usd')
        purchase_rate = validated_data.get('purchase_rate')
        
        if purchase_price_usd and purchase_rate:
            today = date.today()
            ExchangeRate.objects.update_or_create(
                date=today,
                defaults={'usd_rate': purchase_rate}
            )
            
            if not validated_data.get('purchase_price'):
                validated_data['purchase_price'] = purchase_price_usd * purchase_rate
        
        return super().update(instance, validated_data)

    def validate(self, data):

        usd = data.get('purchase_price_usd')
        rate = data.get('purchase_rate')
        
        if (usd and not rate) or (rate and not usd):
            raise serializers.ValidationError(
                "Если указана цена в долларах, нужно указать и курс (и наоборот)."
            )
        
        # Проверяем разумность курса
        if rate and (rate < Decimal('10000') or rate > Decimal('20000')):
            raise serializers.ValidationError(
                f"Курс {rate} выглядит неправильным. "
                f"Ожидается значение между 10000 и 20000"
            )
        
        expiration_date = data.get('expiration_date')
        if expiration_date and expiration_date < timezone.now().date():
            raise serializers.ValidationError(
                {'expiration_date': _("Срок годности не может быть в прошлом")},
                code='expired_product'
            )
        usd = data.get('purchase_price_usd')
        rate = data.get('purchase_rate')
        if (usd and not rate) or (rate and not usd):
            raise serializers.ValidationError(
                _("Если указана цена в долларах, нужно указать и курс (и наоборот).")
            )
        return data


class DocumentSerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
                'id', 'name', 'date_from', 'date_to',
                'file', 'created_at', 'product_count'
                ]
        read_only_fields = ['created_at']

    def get_product_count(self, obj):
        return obj.products.count()

    def validate(self, attrs):
        date_from = attrs.get('date_from')
        date_to = attrs.get('date_to')

        if date_from and date_to and date_to < date_from:
            raise serializers.ValidationError({
                'date_to': "Дата окончание не может быть раньше чем дата заключение"
                })
        return attrs


class ProductSerializer(StoreSerializerMixin, serializers.ModelSerializer):
    """
    ОБНОВЛЕННЫЙ сериализатор для товаров с новой системой единиц измерения
    """
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    # Размеры и варианты
    default_size = SizeInfoSerializer(read_only=True)
    available_sizes = SizeInfoSerializer(many=True, read_only=True)
    default_size_id = serializers.PrimaryKeyRelatedField(
        source='default_size',
        queryset=SizeInfo.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )
    available_size_ids = serializers.PrimaryKeyRelatedField(
        source='available_sizes',
        queryset=SizeInfo.objects.all(),
        many=True,
        write_only=True,
        required=False
    )
    batch_attributes = serializers.SerializerMethodField()
    batch_info = serializers.DictField(required=False, write_only=True)

    # Единицы измерения
    custom_unit = CustomUnitSerializer(read_only=True)
    custom_unit_id = serializers.PrimaryKeyRelatedField(
        source='custom_unit',
        queryset=CustomUnit.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )
    unit_display = serializers.CharField(read_only=True)
    
    # Остатки и партии
    current_stock = serializers.IntegerField(
        source='stock.quantity',
        read_only=True,
        help_text=_('Текущий остаток на складе')
    )
    batches = ProductBatchSerializer(many=True, read_only=True)
    
    # Ценовая информация
    price_info = serializers.JSONField(read_only=True)
    
    # Размерная информация
    sizes_info = serializers.JSONField(read_only=True)
    
    # Метаданные
    created_by = UserSerializer(read_only=True)

    document = DocumentSerializer(read_only=True)
    document_id = serializers.PrimaryKeyRelatedField(
            source = 'document',
            queryset=Document.objects.none(),
            write_only=True,
            required = False,
            allow_null = True,
            help_text = "ID Договрв (опцианально)"
        )

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'barcode', 'category', 'category_name',
            'document', 'document_id',
            'unit_type', 'custom_unit', 'custom_unit_id', 'unit_display',
            'override_min_quantity', 'override_step',
            'sale_price', 'price_info',
            'has_sizes', 'default_size', 'default_size_id', 
            'available_sizes', 'available_size_ids', 'sizes_info',
            'attributes', 'created_at', 'created_by',
            'current_stock', 'batches', 'image_label',
            'is_deleted', 'deleted_at', 'batch_info', 'batch_attributes',
        ]
        read_only_fields = [
            'created_at', 'current_stock', 'created_by', 'unit_display',
            'price_info', 'sizes_info', 'is_deleted', 'deleted_at'
        ]
        extra_kwargs = {
            'name': {'trim_whitespace': True},
            'barcode': {'required': False, 'allow_blank': True},
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get('request')
        if request and hasattr(request.user, 'current_store') and request.user.current_store:
            current_store = request.user.current_store
            self.fields['document_id'].queryset = Document.object.filter(
                    store=current_store
            )

    def validate_sale_price(self, value):
        if value < 0:
            raise serializers.ValidationError(
                _("Цена не может быть отрицательной"),
                code='negative_price'
            )
        return round(value, 2)


    def validate_document_id(self, value):
        if value:
            request = self.context.get('request')
            if request and hasattr(request.user, 'current_store'):
                raise serializers.ValidationError(
                        "Договор не принадлежить данному магазину"
                        )
        return value
    
    def get_batch_attributes(self, obj):
        """Получить все атрибуты из всех партий товара"""
        from .models import ProductBatchAttribute
        
        attributes = []
        for batch in obj.batches.all():
            # Правильно получаем ProductBatchAttribute через related_name
            batch_attributes = ProductBatchAttribute.objects.filter(
                batch=batch
            ).select_related('product_attribute__attribute_value__attribute_type')
            
            for batch_attr in batch_attributes:
                attributes.append({
                    'batch_id': batch.id,
                    'attribute_type': batch_attr.product_attribute.attribute_value.attribute_type.name,
                    'attribute_value': batch_attr.product_attribute.attribute_value.value,
                    'attribute_value_id': batch_attr.product_attribute.attribute_value.id,
                    'quantity': float(batch_attr.quantity)
                })
        
        return attributes

    def validate_barcode(self, value):
        if not value:
            return value

        value = value.strip()
        if not value.isdigit():
            raise serializers.ValidationError(
                _("Штрихкод должен содержать только цифры"),
                code='invalid_barcode_format'
            )

        if len(value) > 100:
            raise serializers.ValidationError(
                _("Штрихкод не может быть длиннее 100 символов"),
                code='barcode_too_long'
            )

        # Проверяем уникальность с учетом магазина
        request = self.context.get('request')
        if request and hasattr(request.user, 'current_store') and request.user.current_store:
            existing_query = Product.objects.filter(
                store=request.user.current_store,
                barcode=value
            )

            if self.instance:
                existing_query = existing_query.exclude(pk=self.instance.pk)

            if existing_query.exists():
                raise serializers.ValidationError(
                    _("Товар с таким штрихкодом уже существует в этом магазине"),
                    code='duplicate_barcode'
                )

        return value

    def validate(self, attrs):
        """Валидация единиц измерения"""
        unit_type = attrs.get('unit_type')
        custom_unit = attrs.get('custom_unit')

        # Должна быть указана единица измерения
        if not unit_type and not custom_unit:
            raise serializers.ValidationError(
                "Укажите единицу измерения (системную или пользовательскую)"
            )

        if unit_type and custom_unit:
            raise serializers.ValidationError(
                "Выберите либо системную, либо пользовательскую единицу"
            )

        return attrs
    
    def validate_batch_info(self, value):
        """Валидация batch_info для одиночного создания"""
        if not value:
            return value
        
        required_fields = ['quantity', 'purchase_price', 'supplier']
        for field in required_fields:
            if field not in value:
                raise serializers.ValidationError(f"Поле '{field}' обязательно для batch_info")

        if value['quantity'] <= 0:
            raise serializers.ValidationError("Количество должно быть больше нуля")
        if value['purchase_price'] < 0:
            raise serializers.ValidationError("Цена закупки должна быть >= 0")

        # ✅ Обработка атрибутов (аналогично мульти-креатору)
        attributes = value.get('attributes', [])
        if attributes:
            # Проверка структуры атрибутов
            for attr in attributes:
                if 'attribute_value_id' not in attr or 'quantity' not in attr:
                    raise serializers.ValidationError(
                        "Каждый атрибут должен содержать attribute_value_id и quantity"
                    )
                if attr['quantity'] <= 0:
                    raise serializers.ValidationError("Количество атрибута должно быть > 0")
                
                if not AttributeValue.objects.filter(id=attr['attribute_value_id']).exists():
                    raise serializers.ValidationError(
                        f"Атрибут с ID {attr['attribute_value_id']} не найден"
                    )

            # Проверка суммы атрибутов
            total_attr_qty = sum([Decimal(attr['quantity']) for attr in attributes])
            if total_attr_qty > Decimal(value['quantity']):
                raise serializers.ValidationError(
                    "Сумма количеств атрибутов не может превышать quantity партии"
                )

        # Обработка size_id (если передан)
        size_id = value.get('size_id')
        if size_id and not SizeInfo.objects.filter(id=size_id).exists():
            raise serializers.ValidationError(f"Размер с ID {size_id} не найден")

        return value

    def create(self, validated_data):
        """Создание товара с дебагом — поймём, где теряются данные"""
        import logging
        from .models import ExchangeRate
        from datetime import date
        logger = logging.getLogger(__name__)

        
        
        # ✅ ШПИОН 1: Что пришло в validated_data?
        logger.info(f"=== ДЕБАГ СОЗДАНИЯ ТОВАРА ===")
        logger.info(f"VALIDATED_DATA: {validated_data}")
        
        store = self.context.get('request').user.current_store
        created_by = self.context.get('request').user
        logger.info(f"STORE: {store.id if store else 'None'}")
        logger.info(f"CREATED_BY: {created_by.id if created_by else 'None'}")
        
        # ✅ ШПИОН 2: Что в batch_info?
        batch_info = validated_data.pop('batch_info', None)
        logger.info(f"BATCH_INFO: {batch_info}")
        
        if batch_info:
            logger.info(f"BATCH_INFO SIZE_ID: {batch_info.get('size_id')}")
            logger.info(f"BATCH_INFO ATTRIBUTES: {batch_info.get('attributes')}")
            purchase_price_usd = batch_info.get('purchase_price_usd')
            purchase_rate = batch_info.get('purchase_rate')

            if purchase_price_usd and purchase_rate:
                # Сохраняем курс
                today = date.today()
                rate, created = ExchangeRate.objects.update_or_create(
                    date=today,
                    defaults={'usd_rate': purchase_rate}
                )
                logger.info(f"{'Создан' if created else 'Обновлен'} курс: {purchase_rate} на {today}")
                
                # Вычисляем цену в сумах если не указана
                if not batch_info.get('purchase_price'):
                    batch_info['purchase_price'] = Decimal(str(purchase_price_usd)) * Decimal(str(purchase_rate))
        
        # ✅ ШПИОН 3: Что с размерами?

        default_size = validated_data.pop('default_size', None)
        available_sizes = validated_data.pop('available_sizes', [])
        logger.info(f"DEFAULT_SIZE: {default_size}")
        logger.info(f"AVAILABLE_SIZES: {available_sizes}")

        
        
        # ✅ Создание товара (без дублирования store)
        product_data = validated_data.copy()
        if 'store' not in product_data:
            product_data['store'] = store
        if 'created_by' not in product_data:
            product_data['created_by'] = created_by
        
        logger.info(f"PRODUCT_DATA: {product_data}")
        product = Product.objects.create(**product_data)
        logger.info(f"ПРОДУКТ СОЗДАН: ID={product.id}, has_sizes={product.has_sizes}")
        
        # ✅ Обработка размеров
        has_size_changes = False
        if default_size:
            product.default_size = default_size
            product.has_sizes = True
            has_size_changes = True
            logger.info(f"УСТАНОВЛЕН DEFAULT_SIZE: {default_size.id}")
        
        if available_sizes:
            product.available_sizes.set(available_sizes)
            product.has_sizes = True
            has_size_changes = True
            logger.info(f"УСТАНОВЛЕНА LIST СНАЙЗОВ: {len(available_sizes)} шт.")
        
        if has_size_changes:
            product.save()
            logger.info(f"ПРОДУКТ СО СНАЙЗАМИ СОХРАНЁН: has_sizes={product.has_sizes}")
        
        # ✅ Stock
        Stock.objects.get_or_create(
            product=product, 
            defaults={'store': store, 'quantity': 0}
        )
        logger.info("STOCK СОЗДАН/ОБНОВЛЁН")
        
        # ✅ Батч
        if batch_info:
            logger.info("=== СОЗДАНИЕ БАТЧА ===")
            
            # Определяем размер
            size_instance = None
            if 'size_id' in batch_info:
                try:
                    size_instance = SizeInfo.objects.get(id=batch_info['size_id'])
                    logger.info(f"SIZE_INSTANCE НАЙДЕН: {size_instance.id} - {size_instance.size}")
                except SizeInfo.DoesNotExist:
                    logger.error(f"SIZE_ID {batch_info['size_id']} НЕ НАЙДЕН!")
                    raise serializers.ValidationError(f"Размер с ID {batch_info['size_id']} не найден")
            elif default_size:
                size_instance = default_size
                logger.info(f"SIZE_INSTANCE ИЗ DEFAULT: {size_instance.id}")
            
            # Создаём батч
            batch_data = {
                'product': product,
                'store': store,
                'size': size_instance,
                'quantity': batch_info['quantity'],
                'purchase_price': batch_info.get('purchase_price'),
                'purchase_price_usd': batch_info.get('purchase_price_usd'),
                'purchase_rate': batch_info.get('purchase_rate'),
                'supplier': batch_info['supplier'],
                'supplier_country': batch_info.get('supplier_country'),
                'expiration_date': batch_info.get('expiration_date')
            }
            logger.info(f"BATCH_DATA: {batch_data}")
            
            batch = ProductBatch.objects.create(**batch_data)
            logger.info(f"БАТЧ СОЗДАН: ID={batch.id}, size={batch.size_id if batch.size else 'None'}")
            
            # ✅ Атрибуты
            attributes = batch_info.get('attributes', [])
            logger.info(f"АТРИБУТЫ ДЛЯ ОБРАБОТКИ: {len(attributes)} шт.")
            
            if attributes:
                from collections import defaultdict
                grouped_attributes = defaultdict(int)
                
                # Группируем
                for attr in attributes:
                    attr_value_id = attr['attribute_value_id']
                    quantity = attr['quantity']
                    grouped_attributes[attr_value_id] += quantity
                    logger.info(f"ГРУППИРУЕМ: attr_id={attr_value_id}, qty={quantity}")
                
                # Создаём ProductAttribute и ProductBatchAttribute
                created_attrs = []
                for attr_value_id, total_quantity in grouped_attributes.items():
                    logger.info(f"СОЗДАЁМ АТРИБУТ: {attr_value_id} = {total_quantity}")
                    
                    # ProductAttribute
                    prod_attr, created = ProductAttribute.objects.get_or_create(
                        product=product,
                        attribute_value_id=attr_value_id
                    )
                    logger.info(f"PRODUCT_ATTRIBUTE: ID={prod_attr.id}, created={created}")
                    
                    # ProductBatchAttribute
                    batch_attr = ProductBatchAttribute.objects.create(
                        batch=batch,
                        product_attribute=prod_attr,
                        quantity=total_quantity,
                        store=store
                    )
                    created_attrs.append(batch_attr.id)
                    logger.info(f"BATCH_ATTRIBUTE СОЗДАН: ID={batch_attr.id}")
                
                logger.info(f"ВСЕГО АТРИБУТОВ СОЗДАНО: {len(created_attrs)}")
            
            # Обновляем сток
            if hasattr(product, 'stock') and hasattr(product.stock, 'update_quantity'):
                product.stock.update_quantity()
                logger.info("СТОК ОБНОВЛЁН")
            else:
                logger.warning("НЕТ МЕТОДА update_quantity() или нет stock!")
        
        logger.info("=== КОНЕЦ СОЗДАНИЯ ===")
        return product
    
    def update(self, instance, validated_data):
        """Обновление товара с обработкой размеров"""
        # Извлекаем размеры
        default_size = validated_data.pop('default_size', None)
        available_sizes = validated_data.pop('available_sizes', None)

        # Обновляем основные поля
        product = super().update(instance, validated_data)

        # Обновляем размеры
        if default_size is not None:
            product.default_size = default_size

        if available_sizes is not None:
            product.available_sizes.set(available_sizes)

        product.save()
        return product


class StockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_barcode = serializers.CharField(source='product.barcode', read_only=True, allow_null=True)
    unit_display = serializers.CharField(source='product.unit_display', read_only=True)

    class Meta:
        model = Stock
        fields = [
            'product', 'product_name', 'product_barcode', 'unit_display',
            'quantity', 'updated_at'
        ]
        read_only_fields = ['updated_at', 'product_name', 'product_barcode', 'unit_display']

    def validate_quantity(self, value):
        if value < 0:
            raise serializers.ValidationError(
                _("Количество не может быть отрицательным"),
                code='negative_quantity'
            )
        return value


class ProductMultiSizeCreateSerializer(serializers.Serializer):
    """
    Сериализатор для создания товаров с размерами и батчами с атрибутами
    """
    name = serializers.CharField(max_length=255)
    category = serializers.PrimaryKeyRelatedField(queryset=ProductCategory.objects.all())
    sale_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    unit_type = serializers.ChoiceField(
        choices=Product.SYSTEM_UNITS, required=False, allow_null=True
    )
    custom_unit_id = serializers.PrimaryKeyRelatedField(
        queryset=CustomUnit.objects.all(), required=False, allow_null=True
    )
    batch_info = serializers.ListField(child=serializers.DictField(), required=True)
    batch_attributes = serializers.SerializerMethodField()
    
    document_id = serializers.PrimaryKeyRelatedField(
            queryset=Document.objects.all(),
            required=False,
            allow_null=True,
            help_text='ID Договора (Опционально)'
        )

    def validate_document_id(self, value):
        if value:
            requst = self.context.gey('request')
            if request and hasattr(request.user, 'current_store'):
                raise serializers.ValidatorError(
                        "Договор не принадлежит вашему магазину"
                        )
        return value

    def validate(self, attrs):
        unit_type = attrs.get('unit_type')
        custom_unit_id = attrs.get('custom_unit_id')

        if not unit_type and not custom_unit_id:
            raise serializers.ValidationError(
                "Укажите единицу измерения (системную или пользовательскую)"
            )
        if unit_type and custom_unit_id:
            raise serializers.ValidationError(
                "Выберите либо системную, либо пользовательскую единицу"
            )
        return attrs

    def validate_batch_info(self, value):
        if not value:
            raise serializers.ValidationError("batch_info обязателен")

        for batch in value:
            required_fields = ["size_id", "quantity", "purchase_price", "supplier"]
            for field in required_fields:
                if field not in batch:
                    raise serializers.ValidationError(
                        f"Поле '{field}' обязательно для batch_info"
                    )

            if batch["quantity"] <= 0:
                raise serializers.ValidationError("Количество должно быть больше нуля")
            if batch["purchase_price"] < 0:
                raise serializers.ValidationError("Цена закупки должна быть >= 0")

            # Проверка уникальности attribute_value_id в рамках одной партии
            attributes = batch.get("attributes", [])
            if attributes:
                attr_ids = [attr["attribute_value_id"] for attr in attributes]
                if len(attr_ids) != len(set(attr_ids)):
                    raise serializers.ValidationError(
                        "В одной партии не может быть повторяющихся атрибутов. "
                        "Если нужно указать разные количества одного атрибута — суммируйте их."
                    )

            # Проверка структуры и значений атрибутов
            for attr in attributes:
                if "attribute_value_id" not in attr or "quantity" not in attr:
                    raise serializers.ValidationError(
                        "Каждый атрибут должен содержать attribute_value_id и quantity"
                    )
                if attr["quantity"] <= 0:
                    raise serializers.ValidationError(
                        "Количество атрибута должно быть > 0"
                    )

                if not AttributeValue.objects.filter(
                    id=attr["attribute_value_id"]
                ).exists():
                    raise serializers.ValidationError(
                        f"Атрибут с ID {attr['attribute_value_id']} не найден"
                    )

            # Проверка, что сумма атрибутов ≤ quantity партии
            total_attr_qty = sum([Decimal(attr["quantity"]) for attr in attributes])
            if total_attr_qty > Decimal(batch["quantity"]):
                raise serializers.ValidationError(
                    "Сумма количеств атрибутов не может превышать quantity партии"
                )

        return value

    def create(self, validated_data):
        from .models import ExchangeRate
        from datetime import date
        
        document = validated_data.get("document_id")
        store = validated_data.get("store")
        created_by = validated_data.get("created_by")
        batch_info = validated_data.get("batch_info", [])
        created_products = []
        
        today = date.today()
        rate_saved = False

        if not store or not created_by:
            raise serializers.ValidationError("store и created_by обязательны")

        batch_info = validated_data.get("batch_info", [])
        created_products = []

        try:
            with transaction.atomic():
                for batch_data in batch_info:
                    purchase_price_usd = batch_data.get('purchase_price_usd')
                    purchase_rate = batch_data.get('purchase_rate')
                    size_instance = SizeInfo.objects.get(id=batch_data["size_id"])
                    product_name = f"{validated_data['name']} - {size_instance.size}"
                    unique_barcode = self.generate_unique_barcode(store)

                    if purchase_price_usd and purchase_rate and not rate_saved:
                        ExchangeRate.objects.update_or_create(
                            date=today,
                            defaults={'usd_rate': purchase_rate}
                        )
                        rate_saved = True
                        logger.info(f"Курс {purchase_rate} сохранен на {today}")

                    if purchase_price_usd and purchase_rate and not batch_data.get('purchase_price'):
                        batch_data['purchase_price'] = Decimal(str(purchase_price_usd)) * Decimal(str(purchase_rate))

                    # --- Product ---
                    product_data = {
                        "name": product_name,
                        "barcode": unique_barcode,
                        "created_by": created_by,
                        "category": validated_data["category"],
                        "purchase_price": batch_data.get("purchase_price"),
                        "purchase_price_usd": purchase_price_usd,
                        "purchase_rate": purchase_rate,
                        "sale_price": validated_data["sale_price"],
                        "store": store,
                        "has_sizes": True,
                        "document": document,
                        "default_size": size_instance,
                    }


                    if validated_data.get("unit_type"):
                        product_data["unit_type"] = validated_data["unit_type"]
                    elif validated_data.get("custom_unit_id"):
                        product_data["custom_unit"] = validated_data["custom_unit_id"]

                    product = Product.objects.create(**product_data)

                    # --- Stock ---
                    Stock.objects.get_or_create(
                        product=product, defaults={"store": store, "quantity": 0}
                    )

                    # --- ProductBatch ---
                    batch_payload = {
                        "product": product,
                        "store": store,
                        "size": size_instance,
                        "quantity": batch_data["quantity"],
                        "purchase_price": batch_data.get("purchase_price"),
                        "purchase_price_usd": batch_data.get("purchase_price_usd"),
                        "purchase_rate": batch_data.get("purchase_rate"),
                        "supplier": batch_data["supplier"],
                        "supplier_country": batch_data.get("supplier_country"),
                        "expiration_date": batch_data.get("expiration_date"),
                        "invoice_number": batch_data.get("invoice_number"),
                    }
                    batch = ProductBatch.objects.create(**batch_payload)

                    # --- Attributes ---
                    from collections import defaultdict

                    attributes = batch_data.get("attributes", [])
                    grouped_attributes = defaultdict(int)

                    for attr in attributes:
                        grouped_attributes[attr["attribute_value_id"]] += attr["quantity"]

                    for attr_value_id, total_quantity in grouped_attributes.items():
                        prod_attr, _ = ProductAttribute.objects.get_or_create(
                            product=product, attribute_value_id=attr_value_id
                        )

                        ProductBatchAttribute.objects.create(
                            batch=batch,
                            product_attribute=prod_attr,
                            quantity=total_quantity,
                            store=store,
                        )

                    # --- Stock update ---
                    product.stock.update_quantity()
                    created_products.append(product)

        except Exception as e:
            logger.error(
                f"Ошибка создания товаров с батчами и атрибутами: {str(e)}", exc_info=True
            )
            raise

        return created_products

    # --- Barcode ---
    def generate_unique_barcode(self, store):
        import random, time, uuid

        max_attempts = 100
        attempts = 0
        while attempts < max_attempts:
            timestamp = str(int(time.time()))[-6:]
            random_part = str(random.randint(100000, 999999))
            code = timestamp + random_part
            checksum = self._calculate_ean13_checksum(code)
            full_barcode = code + checksum
            if not Product.objects.filter(store=store, barcode=full_barcode).exists():
                return full_barcode
            attempts += 1
        return str(uuid.uuid4().int)[:12]

    def _calculate_ean13_checksum(self, digits):
        weights = [1, 3] * 6
        total = sum(int(d) * w for d, w in zip(digits, weights))
        return str((10 - (total % 10)) % 10)

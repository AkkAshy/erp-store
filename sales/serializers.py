# sales/serializers.py - ОБНОВЛЕННАЯ ВЕРСИЯ
from rest_framework import serializers
from .models import Transaction, TransactionItem, TransactionHistory, TransactionRefund, TransactionRefundItem
from inventory.models import Product
from customers.models import Customer
from django.utils.translation import gettext_lazy as _
import logging
import json
from django.contrib.auth import get_user_model
from django.db import models
from decimal import Decimal, ROUND_HALF_UP


User = get_user_model()

logger = logging.getLogger('sales')


class TransactionItemSerializer(serializers.ModelSerializer):
    """
    ОБНОВЛЕННЫЙ сериализатор для элементов транзакции с поддержкой дробных единиц
    """
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source='product',
        help_text="ID товара"
    )
    quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        min_value=Decimal('0.001'),
        help_text="Количество товара (поддерживает дробные значения)"
    )
    # Цена только для чтения - берется из товара
    price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
        help_text="Цена за единицу (берется из товара)"
    )
    # Дополнительная информация для вывода
    unit_display = serializers.CharField(read_only=True)
    unit_type = serializers.CharField(read_only=True)
    subtotal = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    size_snapshot = serializers.JSONField(read_only=True)

    class Meta:
        model = TransactionItem
        fields = [
            'product_id', 'quantity', 'price', 'unit_display', 
            'unit_type', 'subtotal', 'size_snapshot'
        ]

    def validate_quantity(self, value):
        """
        Валидация количества с учетом настроек товара
        """
        # Базовая проверка
        if value <= 0:
            raise serializers.ValidationError("Количество должно быть больше нуля")

        # Получаем товар из контекста (если есть)
        if hasattr(self, 'initial_data'):
            product_id = self.initial_data.get('product_id')
            if product_id:
                try:
                    product = Product.objects.get(id=product_id)
                    
                    # Проверяем минимальное количество
                    min_quantity = product.min_sale_quantity
                    if value < min_quantity:
                        raise serializers.ValidationError(
                            f"Минимальное количество для продажи: {min_quantity} {product.unit_display}"
                        )
                    
                    # Проверяем поддержку дробных значений
                    if not product.allow_decimal and value % 1 != 0:
                        raise serializers.ValidationError(
                            f"Товар '{product.name}' не поддерживает дробные количества"
                        )
                    
                    # Проверяем соответствие шагу
                    step = product.quantity_step
                    if step and step > 0:
                        remainder = value % step
                        if remainder > Decimal('0.001'):  # Допуск на погрешность
                            raise serializers.ValidationError(
                                f"Количество должно соответствовать шагу {step} {product.unit_display}"
                            )
                
                except Product.DoesNotExist:
                    pass  # Ошибка обработается в другом месте

        return value


class TransactionSerializer(serializers.ModelSerializer):
    """
    ОБНОВЛЕННЫЙ сериализатор для транзакций с поддержкой гибридной оплаты
    """
    items = TransactionItemSerializer(many=True)
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(), required=False, allow_null=True
    )
    new_customer = serializers.DictField(
        child=serializers.CharField(), required=False
    )
    cashier_name = serializers.CharField(source='cashier.username', read_only=True)
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    # ← НОВЫЕ ПОЛЯ для гибридной оплаты
    cash_amount = serializers.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        required=False, 
        min_value=0,
        help_text="Сумма наличными (только для гибридной оплаты)"
    )
    transfer_amount = serializers.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        required=False, 
        min_value=0,
        help_text="Сумма переводом (только для гибридной оплаты)"
    )
    card_amount = serializers.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        required=False, 
        min_value=0,
        help_text="Сумма картой (только для гибридной оплаты)"
    )
    
    # Дополнительная информация
    payment_details = serializers.SerializerMethodField()
    items_with_units = serializers.SerializerMethodField()
    items_count_display = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'cashier', 'cashier_name', 'total_amount',
            'payment_method', 'status', 'customer', 'customer_name',
            'new_customer', 'items', 'created_at', 'store_name',
            'cash_amount', 'transfer_amount', 'card_amount',  # ← НОВЫЕ ПОЛЯ
            'payment_details', 'items_with_units', 'items_count_display'
        ]
        read_only_fields = [
            'id', 'cashier', 'cashier_name', 'total_amount', 'created_at', 
            'store_name', 'payment_details', 'items_with_units', 'items_count_display'
        ]

    def get_payment_details(self, obj):
        """Возвращает детали оплаты"""
        return obj.payment_details

    def get_items_with_units(self, obj):
        """Возвращает информацию о товарах с единицами измерения"""
        try:
            return obj.get_total_items_with_units()
        except:
            return []

    def get_items_count_display(self, obj):
        """Возвращает красивое отображение количества товаров"""
        try:
            items_count = obj.items_count
            if items_count % 1 == 0:
                return f"{int(items_count)} ед."
            else:
                return f"{items_count} ед."
        except:
            return "0 ед."

    def validate(self, data):
        """
        ОБНОВЛЕННАЯ валидация с поддержкой гибридной оплаты
        """
        items = data.get('items', [])
        customer = data.get('customer')
        new_customer = data.get('new_customer')
        payment_method = data.get('payment_method', 'cash')
        
        # ← НОВЫЕ ПОЛЯ для валидации
        cash_amount = data.get('cash_amount', Decimal('0'))
        transfer_amount = data.get('transfer_amount', Decimal('0'))
        card_amount = data.get('card_amount', Decimal('0'))

        if not items:
            raise serializers.ValidationError({
                "items": _("Должен быть хотя бы один товар")
            })

        if payment_method == 'debt' and not (customer or new_customer):
            raise serializers.ValidationError({
                "error": _("Для оплаты в долг требуется customer_id или new_customer")
            })

        # Получаем пользователя для проверки роли
        request = self.context.get('request')
        user_role = getattr(request.user, 'store_role', 'cashier') if request else 'cashier'

        # Получаем текущий магазин
        current_store = None
        if request and hasattr(request.user, 'current_store'):
            current_store = request.user.current_store

        # Рассчитываем сумму с проверкой минимальной цены
        total_amount = Decimal('0')
        validated_items = []
        pricing_errors = []
        
        for item_data in items:
            product = item_data['product']
            quantity = Decimal(str(item_data['quantity']))
            
            # Получаем цену из запроса или используем цену товара
            proposed_price = item_data.get('price')
            if proposed_price:
                proposed_price = Decimal(str(proposed_price))
            else:
                proposed_price = product.sale_price

            # Валидация минимальной цены
            price_validation = product.validate_sale_price(proposed_price, user_role)
            
            if not price_validation['valid']:
                pricing_errors.append({
                    'product': product.name,
                    'error': price_validation['error'],
                    'proposed_price': float(proposed_price),
                    'min_price': price_validation.get('min_price'),
                    'min_markup_percent': price_validation.get('min_markup_percent')
                })
                continue
            elif 'warning' in price_validation:
                logger.warning(f"Price below markup allowed for admin: {product.name}, price: {proposed_price}")

            # Проверяем принадлежность к магазину
            if current_store and hasattr(product, 'store'):
                if product.store != current_store:
                    raise serializers.ValidationError({
                        "items": _(f"Товар {product.name} не принадлежит текущему магазину")
                    })

            # Проверяем наличие на складе
            if not hasattr(product, 'stock'):
                raise serializers.ValidationError({
                    "items": _(f"У товара {product.name} нет информации о складе")
                })

            quantity_float = float(quantity)
            if product.stock.quantity < quantity_float:
                raise serializers.ValidationError({
                    "items": _(f"Недостаточно товара {product.name} на складе. "
                            f"Доступно: {product.stock.quantity} {product.unit_display}, "
                            f"запрошено: {quantity} {product.unit_display}")
                })

            # Валидируем количество согласно настройкам товара
            min_quantity = product.min_sale_quantity
            if quantity < min_quantity:
                raise serializers.ValidationError({
                    "items": _(f"Количество {quantity} {product.unit_display} товара {product.name} "
                            f"меньше минимального: {min_quantity} {product.unit_display}")
                })

            # Считаем общую сумму с ВАЛИДИРОВАННОЙ ценой
            item_total = proposed_price * quantity
            total_amount += item_total
            
            validated_items.append({
                'product': product,
                'quantity': quantity,
                'price': proposed_price,
                'subtotal': item_total
            })

        # Проверяем ошибки ценообразования
        if pricing_errors:
            raise serializers.ValidationError({
                "pricing_errors": pricing_errors,
                "message": "Некоторые товары имеют цену ниже минимальной наценки"
            })

        # ← НОВАЯ ВАЛИДАЦИЯ для гибридной оплаты
        if payment_method == 'hybrid':
            hybrid_total = cash_amount + transfer_amount + card_amount
            
            # Проверяем что сумма гибридной оплаты равна общей сумме (с допуском на погрешность)
            if abs(hybrid_total - total_amount) > Decimal('0.01'):
                raise serializers.ValidationError({
                    "hybrid_payment_error": f"Сумма гибридной оплаты ({hybrid_total}) не равна общей сумме товаров ({total_amount})",
                    "details": {
                        "calculated_total": float(total_amount),
                        "hybrid_total": float(hybrid_total),
                        "cash_amount": float(cash_amount),
                        "transfer_amount": float(transfer_amount),
                        "card_amount": float(card_amount)
                    }
                })
            
            # Проверяем что указан хотя бы один способ оплаты
            if hybrid_total == 0:
                raise serializers.ValidationError({
                    "hybrid_payment_error": "Для гибридной оплаты должен быть указан хотя бы один способ с суммой больше нуля"
                })
                
            # Проверяем что все суммы неотрицательные
            if cash_amount < 0 or transfer_amount < 0 or card_amount < 0:
                raise serializers.ValidationError({
                    "hybrid_payment_error": "Все суммы в гибридной оплате должны быть неотрицательными"
                })
                
        else:
            # Для обычных методов оплаты игнорируем гибридные поля
            data['cash_amount'] = Decimal('0')
            data['transfer_amount'] = Decimal('0')
            data['card_amount'] = Decimal('0')
        total_amount = total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        for item in validated_items:
            item['subtotal'] = item['subtotal'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            item['price'] = item['price'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        data['total_amount'] = total_amount
        data['validated_items'] = validated_items
        
        logger.info(f"Total amount calculated: {total_amount}, payment_method: {payment_method}")
        if payment_method == 'hybrid':
            logger.info(f"Hybrid payment: cash={cash_amount}, transfer={transfer_amount}, card={card_amount}")
        
            
        return data

    def create(self, validated_data):
        """
        ✅ ИСПРАВЛЕННОЕ создание транзакции с правильным cash_amount
        """
        items_data = validated_data.pop('items', [])
        validated_items = validated_data.pop('validated_items', [])
        customer = validated_data.pop('customer', None)
        new_customer = validated_data.pop('new_customer', None)
        validated_data.pop('cashier', None)

        request = self.context['request']
        user = request.user

        # Проверяем магазин
        if 'store' not in validated_data:
            if hasattr(user, 'current_store') and user.current_store:
                validated_data['store'] = user.current_store
            else:
                raise serializers.ValidationError({
                    "error": "Не удалось определить текущий магазин"
                })

        # Обрабатываем нового покупателя
        if new_customer:
            phone = new_customer['phone']
            customer, created = Customer.objects.get_or_create(
                phone=phone,
                store=validated_data['store'],
                defaults={'full_name': new_customer['full_name']}
            )
            if created:
                logger.info(f"Created new customer: {customer.full_name}")

        # ✅ КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: Устанавливаем правильные значения для полей оплаты
        payment_method = validated_data.get('payment_method')
        total_amount = validated_data.get('total_amount', Decimal('0'))
        
        # ВАЖНО: Устанавливаем cash_amount для обычных методов оплаты
        if payment_method == 'cash':
            validated_data['cash_amount'] = total_amount
            validated_data['card_amount'] = Decimal('0')
            validated_data['transfer_amount'] = Decimal('0')
            logger.info(f"✅ Setting cash_amount = {total_amount} for cash payment")
            
        elif payment_method == 'card':
            validated_data['cash_amount'] = Decimal('0')
            validated_data['card_amount'] = total_amount
            validated_data['transfer_amount'] = Decimal('0')
            logger.info(f"✅ Setting card_amount = {total_amount} for card payment")
            
        elif payment_method == 'transfer':
            validated_data['cash_amount'] = Decimal('0')
            validated_data['card_amount'] = Decimal('0')
            validated_data['transfer_amount'] = total_amount
            logger.info(f"✅ Setting transfer_amount = {total_amount} for transfer payment")
            
        elif payment_method == 'debt':
            # Для долга все суммы нулевые
            validated_data['cash_amount'] = Decimal('0')
            validated_data['card_amount'] = Decimal('0')
            validated_data['transfer_amount'] = Decimal('0')
            logger.info(f"✅ All amounts set to 0 for debt payment")
            
        elif payment_method == 'hybrid':
            # Для гибридной оплаты значения уже должны быть установлены в validate()
            logger.info(f"✅ Using hybrid payment amounts: cash={validated_data.get('cash_amount')}, "
                    f"card={validated_data.get('card_amount')}, transfer={validated_data.get('transfer_amount')}")
        else:
            # По умолчанию обнуляем все поля
            validated_data['cash_amount'] = Decimal('0')
            validated_data['card_amount'] = Decimal('0')
            validated_data['transfer_amount'] = Decimal('0')

        # Создаем транзакцию с правильными полями оплаты
        transaction = Transaction.objects.create(
            cashier=user,
            customer=customer,
            **validated_data
        )
        
        payment_info = "гибридная" if transaction.payment_method == 'hybrid' else transaction.get_payment_method_display()
        logger.info(f"Transaction #{transaction.id} created with {payment_info} payment, cash_amount={transaction.cash_amount}")

        # Создаем элементы транзакции
        for item_data in validated_items:
            product = item_data['product']
            quantity = item_data['quantity']
            price_from_db = item_data['price']

            if price_from_db <= 0:
                logger.error(f"Invalid price in DB for product {product.name}: {price_from_db}")
                raise serializers.ValidationError({
                    "error": f"Некорректная цена товара {product.name} в базе данных"
                })

            transaction_item = TransactionItem.objects.create(
                transaction=transaction,
                product=product,
                quantity=quantity,
                price=price_from_db,
                store=transaction.store
            )
            
            logger.info(
                f"Transaction item created: {product.name} x{quantity} {product.unit_display} "
                f"@ {price_from_db}"
            )

        # Обрабатываем продажу
        try:
            transaction.process_sale()
            logger.info(f"Transaction #{transaction.id} processed. Total: {transaction.total_amount}, Cash: {transaction.cash_amount}")
            
            # ✅ Дополнительная проверка для отладки
            if transaction.payment_method == 'cash' and transaction.cash_amount > 0:
                logger.info(f"💰 Cash transaction should update register: {transaction.cash_amount}")
            
        except Exception as e:
            logger.error(f"Error processing transaction #{transaction.id}: {str(e)}")
            transaction.status = 'failed'
            transaction.save()
            raise serializers.ValidationError({
                "error": f"Ошибка обработки продажи: {str(e)}"
            })

        return transaction

    def to_representation(self, instance):
        """
        ОБНОВЛЕННОЕ представление с информацией о гибридной оплате
        """
        data = super().to_representation(instance)

        # Добавляем информацию о магазине
        if instance.store:
            data['store'] = {
                'id': str(instance.store.id),
                'name': instance.store.name
            }

        # Добавляем детали товаров с единицами измерения
        items_detail = []
        for item in instance.items.all():
            item_detail = {
                'product_id': item.product.id,
                'product_name': item.product.name,
                'quantity': str(item.quantity),
                'quantity_display': f"{item.quantity} {item.unit_display}",
                'unit_display': item.unit_display,
                'unit_type': item.unit_type,
                'price': str(item.price),
                'subtotal': str(item.subtotal),
                'is_fractional': item.quantity % 1 != 0
            }
            
            # Добавляем информацию о размере если есть
            if item.size_snapshot:
                item_detail['size_info'] = item.size_snapshot
            
            items_detail.append(item_detail)
            
        data['items_detail'] = items_detail

        # Добавляем сводную информацию о единицах измерения
        units_summary = {}
        for item in instance.items.all():
            unit_key = item.unit_display or 'шт'
            if unit_key not in units_summary:
                units_summary[unit_key] = {
                    'total_quantity': Decimal('0'),
                    'total_amount': Decimal('0'),
                    'items_count': 0
                }
            
            units_summary[unit_key]['total_quantity'] += item.quantity
            units_summary[unit_key]['total_amount'] += item.subtotal
            units_summary[unit_key]['items_count'] += 1

        # Конвертируем в сериализуемый формат
        for unit_key in units_summary:
            units_summary[unit_key]['total_quantity'] = str(units_summary[unit_key]['total_quantity'])
            units_summary[unit_key]['total_amount'] = str(units_summary[unit_key]['total_amount'])

        data['units_summary'] = units_summary

        return data

# Остальные сериализаторы остаются без изменений
class FilteredTransactionHistorySerializer(serializers.ModelSerializer):
    """
    Сериализатор с фильтрацией - возвращает только валидные записи
    """
    parsed_details = serializers.SerializerMethodField()

    class Meta:
        model = TransactionHistory
        fields = ['id', 'transaction', 'action', 'parsed_details', 'created_at']

    def get_parsed_details(self, obj):
        try:
            details = json.loads(obj.details)

            # Возвращаем только если есть обязательные поля
            if (details.get('total_amount') and
                details.get('items') and
                len(details.get('items', [])) > 0):
                return details

            return None  # Если данные неполные

        except json.JSONDecodeError:
            return None


class CashierAggregateSerializer(serializers.Serializer):
    cashier_id = serializers.IntegerField()
    cashier_name = serializers.CharField()
    total_quantity = serializers.DecimalField(max_digits=15, decimal_places=3)  # Обновлено
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


# НОВЫЕ сериализаторы для возвратов
class TransactionRefundItemSerializer(serializers.ModelSerializer):
    """
    Сериализатор для элементов возврата
    """
    original_product_name = serializers.CharField(source='original_item.product.name', read_only=True)
    original_quantity = serializers.DecimalField(
        source='original_item.quantity', 
        max_digits=15, 
        decimal_places=3, 
        read_only=True
    )
    can_refund_quantity = serializers.DecimalField(
        max_digits=15, 
        decimal_places=3, 
        read_only=True
    )

    class Meta:
        model = TransactionRefundItem
        fields = [
            'id', 'original_item', 'original_product_name', 
            'original_quantity', 'refunded_quantity', 'refunded_amount',
            'can_refund_quantity'
        ]

    def validate_refunded_quantity(self, value):
        """Проверяем, что не возвращаем больше чем было продано"""
        if self.instance:
            original_item = self.instance.original_item
        else:
            original_item = self.initial_data.get('original_item')
            if isinstance(original_item, int):
                original_item = TransactionItem.objects.get(id=original_item)

        if not original_item:
            raise serializers.ValidationError("Не найден оригинальный элемент транзакции")

        # Проверяем максимальное количество для возврата
        max_refund = self.get_max_refund_quantity(original_item)
        
        if value > max_refund:
            raise serializers.ValidationError(
                f"Нельзя вернуть больше {max_refund} {original_item.unit_display}"
            )

        return value

    def get_max_refund_quantity(self, original_item):
        """Вычисляет максимальное количество для возврата"""
        already_refunded = TransactionRefundItem.objects.filter(
            original_item=original_item
        ).exclude(id=self.instance.id if self.instance else None).aggregate(
            total=models.Sum('refunded_quantity')
        )['total'] or Decimal('0')
        
        return original_item.quantity - already_refunded


class TransactionRefundSerializer(serializers.ModelSerializer):
    """
    Сериализатор для возвратов транзакций
    """
    items = TransactionRefundItemSerializer(many=True)
    processed_by_name = serializers.CharField(source='processed_by.username', read_only=True)
    original_transaction_number = serializers.IntegerField(source='original_transaction.id', read_only=True)

    class Meta:
        model = TransactionRefund
        fields = [
            'id', 'original_transaction', 'original_transaction_number',
            'refund_transaction', 'refunded_amount', 'refund_type',
            'reason', 'processed_by', 'processed_by_name', 'created_at', 'items'
        ]
        read_only_fields = ['processed_by', 'created_at']

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        
        # Устанавливаем обработчика
        validated_data['processed_by'] = self.context['request'].user
        
        refund = TransactionRefund.objects.create(**validated_data)
        
        # Создаем элементы возврата
        for item_data in items_data:
            TransactionRefundItem.objects.create(refund=refund, **item_data)
        
        return refund
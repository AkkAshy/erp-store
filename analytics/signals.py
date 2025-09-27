# analytics/signals.py - ОБНОВЛЕННАЯ ВЕРСИЯ
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from django.db.models import Sum, F
from django.core.cache import cache
from django.utils import timezone
from sales.models import Transaction
from analytics.models import (
    SalesSummary, ProductAnalytics, CustomerAnalytics,
    UnitAnalytics, SizeAnalytics, CategoryAnalytics,
    CashRegister
)

import logging
from decimal import Decimal

logger = logging.getLogger('analytics')

@receiver(post_save, sender=Transaction)
def process_transaction_analytics(sender, instance, created, **kwargs):
    """
    ✅ ОБНОВЛЕННЫЙ сигнал для обработки аналитики с поддержкой гибридной оплаты
    """

    # Обрабатываем только завершённые транзакции
    if instance.status != 'completed':
        logger.debug(f"⏭️ Skipping non-completed transaction {instance.id}")
        return

    # Проверяем, не обработана ли уже эта транзакция
    processed_key = f"analytics_processed_{instance.id}"
    if cache.get(processed_key):
        logger.info(f"⚠️ Analytics already processed for transaction {instance.id}")
        return

    # Устанавливаем блокировку на обработку
    lock_key = f"analytics_lock_{instance.id}"
    if cache.get(lock_key):
        logger.warning(f"🔒 Analytics processing is locked for transaction {instance.id}")
        return

    # Устанавливаем блокировку на 60 секунд
    cache.set(lock_key, True, 60)

    try:
        with transaction.atomic():
            logger.info(f"🔄 Processing analytics for transaction {instance.id} (amount: {instance.total_amount})")

            # Обрабатываем все виды аналитики
            _process_sales_summary_with_hybrid(instance)  # ← ОБНОВЛЕННАЯ ФУНКЦИЯ
            _process_product_analytics(instance)
            _process_unit_analytics(instance)
            _process_size_analytics(instance)
            _process_category_analytics(instance)

            if instance.customer:
                _process_customer_analytics(instance)

            # Отмечаем транзакцию как обработанную (на 24 часа)
            cache.set(processed_key, True, 86400)

            logger.info(f"✅ Analytics processed successfully for transaction {instance.id}")

    except Exception as e:
        logger.error(f"❌ Error processing analytics for transaction {instance.id}: {str(e)}")
        # Не поднимаем исключение, чтобы не ломать сохранение транзакции

    finally:
        # Всегда снимаем блокировку
        cache.delete(lock_key)

def _process_sales_summary_with_hybrid(instance):
    """
    ОБНОВЛЕННАЯ обработка сводки продаж с поддержкой гибридной оплаты
    """
    date = instance.created_at.date()
    
    # Подсчитываем количество товаров в транзакции
    items_count = instance.items.aggregate(
        total=Sum('quantity')
    )['total'] or 0

    if instance.payment_method == 'hybrid':
        # Для гибридной оплаты создаем записи для каждого способа оплаты отдельно
        hybrid_payments = []
        
        if instance.cash_amount > 0:
            hybrid_payments.append(('cash', instance.cash_amount))
        if instance.transfer_amount > 0:
            hybrid_payments.append(('transfer', instance.transfer_amount))
        if instance.card_amount > 0:
            hybrid_payments.append(('card', instance.card_amount))
        
        # Пропорционально распределяем количество товаров между способами оплаты
        total_hybrid = instance.cash_amount + instance.transfer_amount + instance.card_amount
        
        for payment_method, amount in hybrid_payments:
            # Рассчитываем пропорциональное количество товаров для этого способа оплаты
            if total_hybrid > 0:
                proportional_items = int((amount / total_hybrid) * items_count)
            else:
                proportional_items = 0
                
            _update_sales_summary_record(
                instance, date, payment_method, amount, 1, proportional_items
            )
            
        logger.info(f"Processed hybrid payment for transaction {instance.id}: {len(hybrid_payments)} payment methods")
        
    else:
        # Обычная обработка для простых способов оплаты
        _update_sales_summary_record(
            instance, date, instance.payment_method, instance.total_amount, 1, items_count
        )

def _update_sales_summary_record(instance, date, payment_method, amount, transaction_count, items_count):
    """
    Обновляет или создает запись в SalesSummary
    """
    try:
        # Ищем существующую запись
        summary = SalesSummary.objects.filter(
            store=instance.store,
            date=date,
            payment_method=payment_method
        ).first()

        if summary:
            # Проверяем, не включена ли уже эта транзакция
            if _is_transaction_already_included_in_summary(instance, summary):
                logger.warning(f"Transaction {instance.id} already included in SalesSummary for {payment_method}")
                return

            # Добавляем к существующей записи
            summary.total_amount += amount
            summary.total_transactions += transaction_count
            summary.total_items_sold += items_count
            summary.cashier = instance.cashier  # Обновляем на последнего кассира
            summary.save()

            logger.info(f"Updated SalesSummary ({payment_method}): +{amount} (total: {summary.total_amount})")

        else:
            # Создаем новую запись
            summary = SalesSummary.objects.create(
                store=instance.store,
                date=date,
                payment_method=payment_method,
                cashier=instance.cashier,
                total_amount=amount,
                total_transactions=transaction_count,
                total_items_sold=items_count
            )

            logger.info(f"Created new SalesSummary ({payment_method}): {amount}")

    except Exception as e:
        logger.error(f"Error processing sales summary for transaction {instance.id}, method {payment_method}: {str(e)}")
        raise


def _process_sales_summary(instance):
    """
    Обрабатывает сводку продаж с защитой от дублирования
    """
    date = instance.created_at.date()
    payment_method = instance.payment_method

    # Подсчитываем количество товаров в транзакции
    items_count = instance.items.aggregate(
        total=Sum('quantity')
    )['total'] or 0

    try:
        # Ищем существующую запись
        summary = SalesSummary.objects.filter(
            store=instance.store,
            date=date,
            payment_method=payment_method
        ).first()

        if summary:
            # Проверяем, не включена ли уже эта транзакция
            if _is_transaction_already_included_in_summary(instance, summary):
                logger.warning(f"Transaction {instance.id} already included in SalesSummary")
                return

            # Добавляем к существующей записи
            summary.total_amount += instance.total_amount
            summary.total_transactions += 1
            summary.total_items_sold += items_count
            summary.cashier = instance.cashier  # Обновляем на последнего кассира
            summary.save()

            logger.info(f"Updated SalesSummary: +{instance.total_amount} (total: {summary.total_amount})")

        else:
            # Создаем новую запись
            summary = SalesSummary.objects.create(
                store=instance.store,
                date=date,
                payment_method=payment_method,
                cashier=instance.cashier,
                total_amount=instance.total_amount,
                total_transactions=1,
                total_items_sold=items_count
            )

            logger.info(f"Created new SalesSummary: {instance.total_amount}")

    except Exception as e:
        logger.error(f"Error processing sales summary for transaction {instance.id}: {str(e)}")
        raise


def _process_product_analytics(instance):
    """
    ОБНОВЛЕННАЯ обработка аналитики по товарам с учетом дробных единиц
    """
    date = instance.created_at.date()

    try:
        for item in instance.items.all():
            # Ищем существующую запись
            analytics = ProductAnalytics.objects.filter(
                product=item.product,
                date=date
            ).first()

            # Конвертируем количество в Decimal для точности
            item_quantity = Decimal(str(item.quantity))
            item_price = Decimal(str(item.price))
            item_revenue = item_quantity * item_price

            if analytics:
                # Проверяем дублирование
                if _is_item_already_included_in_product_analytics(item, analytics, date):
                    logger.warning(f"Item {item.product.name} from transaction {instance.id} already included")
                    continue

                # Добавляем к существующей записи
                analytics.quantity_sold += item_quantity
                analytics.revenue += item_revenue
                analytics.cashier = instance.cashier
                
                # Пересчитываем среднюю цену
                if analytics.quantity_sold > 0:
                    analytics.average_unit_price = analytics.revenue / analytics.quantity_sold
                
                analytics.save()

                logger.debug(f"Updated ProductAnalytics for {item.product.name}: +{item_quantity} {item.product.unit_display}")

            else:
                # Создаем новую запись
                analytics = ProductAnalytics.objects.create(
                    product=item.product,
                    date=date,
                    cashier=instance.cashier,
                    quantity_sold=item_quantity,
                    revenue=item_revenue,
                    average_unit_price=item_price
                )

                logger.debug(f"Created ProductAnalytics for {item.product.name}: {item_quantity} {item.product.unit_display}")

    except Exception as e:
        logger.error(f"Error processing product analytics for transaction {instance.id}: {str(e)}")
        raise


def _process_unit_analytics(instance):
    """
    НОВАЯ функция: Обработка аналитики по единицам измерения
    """
    date = instance.created_at.date()

    try:
        # Группируем товары по единицам измерения
        unit_groups = {}
        
        for item in instance.items.all():
            product = item.product
            unit_key = (product.unit_type or 'custom', product.unit_display)
            
            if unit_key not in unit_groups:
                unit_groups[unit_key] = {
                    'unit_type': product.unit_type or 'custom',
                    'unit_display': product.unit_display,
                    'is_custom': product.custom_unit is not None,
                    'quantity': Decimal('0'),
                    'revenue': Decimal('0'),
                    'products': set(),
                    'transactions': 1
                }
            
            item_quantity = Decimal(str(item.quantity))
            item_revenue = item_quantity * Decimal(str(item.price))
            
            unit_groups[unit_key]['quantity'] += item_quantity
            unit_groups[unit_key]['revenue'] += item_revenue
            unit_groups[unit_key]['products'].add(product.id)

        # Обрабатываем каждую единицу измерения
        for unit_key, unit_data in unit_groups.items():
            unit_type = unit_data['unit_type']
            unit_display = unit_data['unit_display']
            
            # Ищем или создаем запись аналитики
            analytics, created = UnitAnalytics.objects.get_or_create(
                store=instance.store,
                date=date,
                unit_type=unit_type,
                unit_display=unit_display,
                defaults={
                    'is_custom': unit_data['is_custom'],
                    'total_quantity_sold': unit_data['quantity'],
                    'total_revenue': unit_data['revenue'],
                    'products_count': len(unit_data['products']),
                    'transactions_count': 1
                }
            )
            
            if not created:
                analytics.total_quantity_sold += unit_data['quantity']
                analytics.total_revenue += unit_data['revenue']
                
                # Обновляем product_ids
                analytics.product_ids = list(set(analytics.product_ids + list(unit_data['products'])))
                analytics.products_count = len(analytics.product_ids)
                
                analytics.transactions_count += 1
                analytics.save()

            # Рассчитываем метрики
            analytics.calculate_metrics()
            analytics.save()

            logger.debug(f"Processed UnitAnalytics for {unit_display}: +{unit_data['quantity']}")

    except Exception as e:
        logger.error(f"Error processing unit analytics for transaction {instance.id}: {str(e)}")
        # Не поднимаем исключение, так как это дополнительная аналитика


def _process_size_analytics(instance):
    """
    НОВАЯ функция: Обработка аналитики по размерам
    """
    date = instance.created_at.date()

    try:
        # Группируем товары по размерам
        size_groups = {}
        
        for item in instance.items.all():
            product = item.product
            
            # Пропускаем товары без размеров
            if not product.has_sizes or not product.default_size:
                continue
                
            size_info = product.default_size
            size_key = size_info.size
            
            if size_key not in size_groups:
                size_groups[size_key] = {
                    'size_name': size_info.size,
                    'dimension1': size_info.dimension1,
                    'dimension2': size_info.dimension2,
                    'dimension3': size_info.dimension3,
                    'dimension1_label': size_info.dimension1_label,
                    'dimension2_label': size_info.dimension2_label,
                    'dimension3_label': size_info.dimension3_label,
                    'quantity': Decimal('0'),
                    'revenue': Decimal('0'),
                    'products': set(),
                    'transactions': 1
                }
            
            item_quantity = Decimal(str(item.quantity))
            item_revenue = item_quantity * Decimal(str(item.price))
            
            size_groups[size_key]['quantity'] += item_quantity
            size_groups[size_key]['revenue'] += item_revenue
            size_groups[size_key]['products'].add(product.id)

        # Обрабатываем каждый размер
        for size_key, size_data in size_groups.items():
            # Ищем или создаем запись аналитики
            analytics, created = SizeAnalytics.objects.get_or_create(
                store=instance.store,
                date=date,
                size_name=size_data['size_name'],
                defaults={
                    'dimension1': size_data['dimension1'],
                    'dimension2': size_data['dimension2'],
                    'dimension3': size_data['dimension3'],
                    'dimension1_label': size_data['dimension1_label'],
                    'dimension2_label': size_data['dimension2_label'],
                    'dimension3_label': size_data['dimension3_label'],
                    'total_quantity_sold': size_data['quantity'],
                    'total_revenue': size_data['revenue'],
                    'products_count': len(size_data['products']),
                    'transactions_count': 1
                }
            )
            
            if not created:
                analytics.total_quantity_sold += size_data['quantity']
                analytics.total_revenue += size_data['revenue']
                analytics.transactions_count += 1
                analytics.save()

            logger.debug(f"Processed SizeAnalytics for {size_key}: +{size_data['quantity']}")

    except Exception as e:
        logger.error(f"Error processing size analytics for transaction {instance.id}: {str(e)}")
        # Не поднимаем исключение, так как это дополнительная аналитика


def _process_category_analytics(instance):
    """
    НОВАЯ функция: Обработка аналитики по категориям
    """
    date = instance.created_at.date()

    try:
        # Группируем товары по категориям
        category_groups = {}
        
        for item in instance.items.all():
            product = item.product
            category = product.category
            category_id = category.id
            
            if category_id not in category_groups:
                category_groups[category_id] = {
                    'category': category,
                    'quantity': Decimal('0'),
                    'revenue': Decimal('0'),
                    'products': set(),
                    'transactions': 1
                }
            
            item_quantity = Decimal(str(item.quantity))
            item_revenue = item_quantity * Decimal(str(item.price))
            
            category_groups[category_id]['quantity'] += item_quantity
            category_groups[category_id]['revenue'] += item_revenue
            category_groups[category_id]['products'].add(product.id)

        # Обрабатываем каждую категорию
        for category_id, category_data in category_groups.items():
            # Ищем или создаем запись аналитики
            analytics, created = CategoryAnalytics.objects.get_or_create(
                store=instance.store,
                date=date,
                category=category_data['category'],
                defaults={
                    'total_quantity_sold': category_data['quantity'],
                    'total_revenue': category_data['revenue'],
                    'products_count': len(category_data['products']),
                    'transactions_count': 1,
                    'unique_products_sold': len(category_data['products'])
                }
            )
            
            if not created:
                analytics.total_quantity_sold += category_data['quantity']
                analytics.total_revenue += category_data['revenue']
                analytics.transactions_count += 1
                # Обновляем уникальные товары (это требует отдельного подсчета)
                analytics.save()

            # Рассчитываем метрики
            analytics.calculate_metrics()
            analytics.save()

            logger.debug(f"Processed CategoryAnalytics for {category_data['category'].name}: +{category_data['revenue']}")

    except Exception as e:
        logger.error(f"Error processing category analytics for transaction {instance.id}: {str(e)}")
        # Не поднимаем исключение, так как это дополнительная аналитика


def _process_customer_analytics(instance):
    """
    Обрабатывает аналитику по клиентам
    """
    date = instance.created_at.date()
    debt_amount = instance.total_amount if instance.payment_method == 'debt' else Decimal('0.00')

    try:
        # Ищем существующую запись
        analytics = CustomerAnalytics.objects.filter(
            customer=instance.customer,
            date=date
        ).first()

        if analytics:
            # Проверяем дублирование
            if _is_transaction_already_included_in_customer_analytics(instance, analytics):
                logger.warning(f"Transaction {instance.id} already included in CustomerAnalytics")
                return

            # Добавляем к существующей записи
            analytics.total_purchases += instance.total_amount
            analytics.transaction_count += 1
            analytics.debt_added += debt_amount
            analytics.cashier = instance.cashier
            analytics.save()

            logger.debug(f"Updated CustomerAnalytics for {instance.customer.full_name}")

        else:
            # Создаем новую запись
            analytics = CustomerAnalytics.objects.create(
                customer=instance.customer,
                date=date,
                cashier=instance.cashier,
                total_purchases=instance.total_amount,
                transaction_count=1,
                debt_added=debt_amount
            )

            logger.debug(f"Created CustomerAnalytics for {instance.customer.full_name}")

    except Exception as e:
        logger.error(f"Error processing customer analytics for transaction {instance.id}: {str(e)}")
        raise


# Остальные вспомогательные функции остаются без изменений
def _is_transaction_already_included_in_summary(instance, summary):
    """
    Проверяет, включена ли уже транзакция в сводку
    (обновленная версия для работы с гибридными платежами)
    """
    try:
        # Для гибридных платежей проверяем более осторожно
        # так как одна транзакция может создавать несколько записей в SalesSummary
        
        # Находим все транзакции за этот день с этим методом оплаты, кроме текущей
        other_transactions = Transaction.objects.filter(
            store=instance.store,
            created_at__date=summary.date,
            status='completed'
        ).exclude(id=instance.id)
        
        # Подсчитываем ожидаемую сумму для этого способа оплаты
        expected_amount = Decimal('0.00')
        
        for tx in other_transactions:
            if tx.payment_method == summary.payment_method:
                # Простой способ оплаты
                expected_amount += tx.total_amount
            elif tx.payment_method == 'hybrid':
                # Гибридная оплата - берем соответствующую сумму
                if summary.payment_method == 'cash':
                    expected_amount += tx.cash_amount
                elif summary.payment_method == 'transfer':
                    expected_amount += tx.transfer_amount
                elif summary.payment_method == 'card':
                    expected_amount += tx.card_amount
        
        # Вычисляем ожидаемую сумму включая текущую транзакцию
        current_contribution = Decimal('0.00')
        if instance.payment_method == summary.payment_method:
            current_contribution = instance.total_amount
        elif instance.payment_method == 'hybrid':
            if summary.payment_method == 'cash':
                current_contribution = instance.cash_amount
            elif summary.payment_method == 'transfer':
                current_contribution = instance.transfer_amount
            elif summary.payment_method == 'card':
                current_contribution = instance.card_amount
        
        expected_amount_with_current = expected_amount + current_contribution
        
        # Если разница меньше 1 копейки, транзакция уже учтена
        return abs(summary.total_amount - expected_amount_with_current) < Decimal('0.01')

    except Exception as e:
        logger.error(f"Error checking transaction inclusion: {str(e)}")
        return False


def _is_item_already_included_in_product_analytics(item, analytics, date):
    """
    Проверяет, включен ли уже товар в аналитику
    """
    try:
        from sales.models import TransactionItem

        # Находим все продажи этого товара за день, кроме текущей транзакции
        other_items = TransactionItem.objects.filter(
            transaction__store=item.transaction.store,
            transaction__created_at__date=date,
            transaction__status='completed',
            product=item.product
        ).exclude(transaction_id=item.transaction.id)

        # Ожидаемое количество без текущего товара
        expected_quantity = other_items.aggregate(
            total=Sum('quantity')
        )['total'] or 0

        # Текущее количество минус этот товар
        current_minus_this = analytics.quantity_sold - Decimal(str(item.quantity))

        # Если количества совпадают, товар уже учтен
        return abs(current_minus_this - Decimal(str(expected_quantity))) < Decimal('0.001')

    except Exception as e:
        logger.error(f"Error checking item inclusion: {str(e)}")
        return False


def _is_transaction_already_included_in_customer_analytics(instance, analytics):
    """
    Проверяет, включена ли уже транзакция в аналитику клиента
    """
    try:
        # Находим все транзакции этого клиента за день, кроме текущей
        other_transactions = Transaction.objects.filter(
            store=instance.store,
            created_at__date=analytics.date,
            customer=instance.customer,
            status='completed'
        ).exclude(id=instance.id)

        # Ожидаемая сумма без текущей транзакции
        expected_amount = other_transactions.aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0.00')

        # Текущая сумма минус эта транзакция
        current_minus_this = analytics.total_purchases - instance.total_amount

        # Если суммы совпадают, транзакция уже учтена
        return abs(current_minus_this - expected_amount) < Decimal('0.01')

    except Exception as e:
        logger.error(f"Error checking customer transaction inclusion: {str(e)}")
        return False
    

# Интеграция с продажами: в signals.py добавь
@receiver(post_save, sender=Transaction)
def update_cash_on_sale(sender, instance, **kwargs):
    if instance.payment_method == 'cash' and instance.cash_amount > 0:
        cash_reg = CashRegister.objects.filter(store=instance.store, is_open=True).first()
        if cash_reg:
            cash_reg.add_cash(instance.cash_amount, instance.cashier, 'Продажа')


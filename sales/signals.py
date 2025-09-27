# sales/signals.py - ЕДИНЫЙ ИСПРАВЛЕННЫЙ ФАЙЛ
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal
import logging
import json
from django.db.models import F
from django.db import  transaction as db_transaction 

logger = logging.getLogger(__name__)

# ================== PRE-SAVE SIGNALS ==================

@receiver(pre_save, sender='sales.Transaction')
def track_original_status(sender, instance, **kwargs):
    """Сохраняем старый статус перед изменением для отслеживания"""
    if instance.pk:
        try:
            from sales.models import Transaction
            old = Transaction.objects.get(pk=instance.pk)
            instance._old_status = old.status
        except Transaction.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


# ================== TRANSACTION SIGNALS ==================

@receiver(post_save, sender='sales.Transaction')
def handle_transaction_complete(sender, instance, created, **kwargs):
    """
    Главный сигнал для обработки транзакций
    Объединяет все операции с транзакциями
    """
    from sales.models import TransactionHistory
    
    logger.info(f"📍 Transaction signal: ID={instance.id}, created={created}, "
                f"status={instance.status}, cash={instance.cash_amount}")
    
    # 1. Создаем историю транзакции
    if created or instance.status in ['completed', 'refunded', 'cancelled']:
        try:
            action = 'created' if created else instance.status
            
            # Проверяем наличие магазина
            if not hasattr(instance, 'store') or not instance.store:
                logger.error(f"❌ Transaction {instance.id} has no store!")
                return
            
            details = {
                'transaction_id': instance.id,
                'total_amount': str(instance.total_amount),
                'payment_method': instance.payment_method,
                'cash_amount': str(instance.cash_amount),
                'card_amount': str(instance.card_amount),
                'transfer_amount': str(instance.transfer_amount),
                'cashier': instance.cashier.username if instance.cashier else None,
                'customer': instance.customer.name if instance.customer else None,
                'store_id': str(instance.store.id),
                'store_name': instance.store.name
            }
            
            TransactionHistory.objects.get_or_create(
                transaction=instance,
                action=action,
                defaults={
                    'details': json.dumps(details, ensure_ascii=False),
                    'store': instance.store,
                    'created_at': timezone.now()
                }
            )
            logger.info(f"✅ Transaction history created for {instance.id}")
            
        except Exception as e:
            logger.error(f"❌ Error creating transaction history: {e}", exc_info=True)
    
    # 2. Обработка завершенной транзакции
    old_status = getattr(instance, "_old_status", None)
    
    if (created and instance.status == "completed") or \
       (not created and old_status != "completed" and instance.status == "completed"):
        
        logger.info(f"✅ Processing completed transaction {instance.id}")
        
        # Обновляем кассу для наличных платежей
        if instance.cash_amount > 0:
            update_cash_register_on_sale(instance)
        
        # Обновляем финансовую сводку
        update_daily_financial_summary(instance)
    
    # 3. Обработка возврата
    if instance.status == 'refunded' and old_status != 'refunded':
        logger.info(f"🔄 Processing refund for transaction {instance.id}")
        handle_transaction_refund(instance)


def update_cash_register_on_sale(transaction):
    """
    Обновление кассового аппарата при продаже с наличными
    """
    from analytics.models import CashRegister, CashHistory
    
    if transaction.cash_amount <= 0:
        return False
    
    store = transaction.store
    
    logger.info(f"💰 Updating cash register for transaction {transaction.id}: "
                f"{transaction.cash_amount} сум")
    
    try:
        with db_transaction.atomic():
            # Находим или создаем открытую кассу
            today = timezone.now().date()
            
            cash_register = CashRegister.objects.filter(
                store=store,
                date_opened__date=today,
                is_open=True
            ).select_for_update().first()
            
            if not cash_register:
                cash_register = CashRegister.objects.create(
                    store=store,
                    current_balance=Decimal('0.00'),
                    target_balance=Decimal('0.00'),
                    is_open=True,
                    date_opened=timezone.now()
                )
                logger.info(f"✅ Created new cash register {cash_register.id}")
            
            # Проверяем дубликаты
            existing = CashHistory.objects.filter(
                cash_register=cash_register,
                notes__contains=f"Продажа #{transaction.id}",
                operation_type='ADD_CASH'
            ).exists()
            
            if existing:
                logger.warning(f"⚠️ Transaction {transaction.id} already in cash register")
                return False
            
            # Обновляем баланс
            balance_before = cash_register.current_balance
            new_balance = balance_before + transaction.cash_amount
            
            CashRegister.objects.filter(id=cash_register.id).update(
                current_balance=new_balance,
                last_updated=timezone.now()
            )
            
            cash_register.refresh_from_db()
            
            # Создаем запись в истории
            CashHistory.objects.create(
                cash_register=cash_register,
                operation_type='ADD_CASH',
                amount=transaction.cash_amount,
                user=transaction.cashier,
                store=store,
                notes=f"Продажа #{transaction.id}",
                balance_before=balance_before,
                balance_after=new_balance
            )
            
            logger.info(f"✅ Cash register updated: +{transaction.cash_amount}, "
                       f"balance: {balance_before} → {new_balance}")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Error updating cash register: {e}", exc_info=True)
        return False


def update_daily_financial_summary(transaction):
    """
    Обновление дневной финансовой сводки с расчетом маржи
    """
    from inventory.models import FinancialSummary
    from sales.models import Transaction
    from django.db.models import Sum, Count, Avg
    
    try:
        # Получаем или создаем сводку
        summary, created = FinancialSummary.objects.get_or_create(
            date=transaction.created_at.date(),
            store=transaction.store,
            defaults={
                'total_transactions': 0,
                'grand_total': Decimal('0'),
                'total_margin': Decimal('0'),
                'margin_percentage': Decimal('0'),
                'cash_total': Decimal('0'),
                'transfer_total': Decimal('0'),
                'card_total': Decimal('0'),
                'debt_total': Decimal('0'),
            }
        )
        
        if created:
            logger.info(f"📊 Created financial summary for {transaction.store.name} "
                       f"on {transaction.created_at.date()}")
        
        # Получаем все транзакции за день
        daily_transactions = Transaction.objects.filter(
            store=transaction.store,
            created_at__date=transaction.created_at.date(),
            status='completed'
        )
        
        # Агрегируем данные (обходим проблему с Avg)
        stats = daily_transactions.aggregate(
            total_count=Count('id'),
            total_amount=Sum('total_amount'),
            total_cash=Sum('cash_amount'),
            total_transfer=Sum('transfer_amount'),
            total_card=Sum('card_amount'),
        )
        
        # Безопасное получение значений с дефолтами
        total_count = stats['total_count'] or 0
        total_amount = stats['total_amount'] or Decimal('0')
        total_cash = stats['total_cash'] or Decimal('0')
        total_transfer = stats['total_transfer'] or Decimal('0')
        total_card = stats['total_card'] or Decimal('0')
        
        # Вычисляем среднее вручную
        avg_amount = (total_amount / total_count) if total_count > 0 else Decimal('0')
        
        # Вычисляем debt как разницу (если нет отдельного поля)
        total_debt = total_amount - (total_cash + total_transfer + total_card)
        if total_debt < 0:
            total_debt = Decimal('0')
        
        # Обновляем поля
        summary.total_transactions = total_count
        summary.grand_total = total_amount
        summary.avg_transaction = avg_amount
        summary.cash_total = total_cash
        summary.transfer_total = total_transfer
        summary.card_total = total_card
        summary.debt_total = total_debt
        
        # Сохраняем базовые изменения
        summary.save()
        
        # Расчет маржи (если метод существует)
        if hasattr(summary, 'calculate_margins'):
            margin_result = summary.calculate_margins()
            logger.info(
                f"💰 Updated summary {summary.store.name} ({summary.date}):\n"
                f"   Transactions: {summary.total_transactions}\n"
                f"   Revenue: {summary.grand_total:,.0f} сум\n"
                f"   Margin: {margin_result.get('margin', 0):,.0f} сум "
                f"({margin_result.get('margin_percentage', 0):.1f}%)"
            )
        
        return summary
        
    except Exception as e:
        logger.error(f"❌ Error updating financial summary: {e}", exc_info=True)
        return None


def handle_transaction_refund(instance):
    """
    Обработка возврата транзакции
    """
    from inventory.models import Stock, StockHistory
    
    # Возвращаем товары на склад
    for item in instance.items.all():
        stock, _ = Stock.objects.get_or_create(
            product=item.product,
            store=instance.store,
            defaults={'quantity': 0}
        )
        
        old_quantity = stock.quantity
        stock.quantity += item.quantity
        stock.save(update_fields=['quantity'])
        
        # Создаем запись в истории
        StockHistory.objects.create(
            product=item.product,
            store=instance.store,
            quantity_before=old_quantity,
            quantity_after=stock.quantity,
            quantity_change=item.quantity,
            operation_type='RETURN',
            reference_id=f'refund_{instance.id}_item_{item.id}',
            user=instance.cashier,
            notes=f'Возврат по транзакции {instance.id}'
        )
        
        logger.info(f"✅ Refund processed: {item.product.name} x{item.quantity} "
                   f"(stock: {old_quantity} → {stock.quantity})")
    
    # Возвращаем деньги из кассы
    if instance.cash_amount > 0:
        handle_cash_refund(instance)


def handle_cash_refund(transaction):
    """
    Возврат наличных из кассы
    """
    from analytics.models import CashRegister, CashHistory
    
    store = transaction.store
    refund_amount = transaction.cash_amount
    
    today = timezone.now().date()
    cash_register = CashRegister.objects.filter(
        store=store,
        date_opened__date=today,
        is_open=True
    ).first()
    
    if not cash_register:
        logger.error(f"❌ No open cash register for refund {refund_amount}")
        return
    
    try:
        if cash_register.current_balance >= refund_amount:
            balance_before = cash_register.current_balance
            cash_register.current_balance -= refund_amount
            cash_register.save(update_fields=['current_balance', 'last_updated'])
            
            CashHistory.objects.create(
                cash_register=cash_register,
                operation_type='WITHDRAW',
                amount=refund_amount,
                user=transaction.cashier,
                store=store,
                notes=f"Возврат по транзакции {transaction.id}",
                balance_before=balance_before,
                balance_after=cash_register.current_balance
            )
            
            logger.info(f"✅ Cash refund processed: -{refund_amount} сум")
        else:
            logger.error(f"❌ Insufficient cash for refund: need {refund_amount}, "
                        f"have {cash_register.current_balance}")
    except Exception as e:
        logger.error(f"❌ Error processing cash refund: {e}", exc_info=True)


# ================== TRANSACTION ITEM SIGNALS ==================

@receiver(post_save, sender='sales.Transaction')
def track_sales_from_transaction_status(sender, instance, created, **kwargs):
    """
    Обработка изменения статуса транзакции на completed
    """
    if not created and instance.status == 'completed':
        logger.info(f"💰 Transaction {instance.id} completed, processing analytics for items")
        
        # Обрабатываем все items транзакции
        for item in instance.items.all():
            process_sale_analytics(item)


def process_sale_analytics(transaction_item):
    """
    Основная функция обработки аналитики продажи
    """
    from inventory.models import Stock, StockHistory, SizeInfo
    from analytics.models import SupplierAnalytics
    
    product = transaction_item.product
    store = transaction_item.store
    transaction = transaction_item.transaction
    
    logger.info(f"📊 Processing analytics for sale: {product.name} x{transaction_item.quantity}")
    
    try:
        # Обновляем сток (уже сделано в другом месте, проверяем)
        stock = Stock.objects.filter(product=product, store=store).first()
        if not stock:
            logger.warning(f"⚠️ Stock not found for {product.name} in {store.name}")
            return
        
        # Определяем размер из snapshot
        size_instance = None
        if transaction_item.size_snapshot:
            size_id = transaction_item.size_snapshot.get('id')
            if size_id:
                try:
                    size_instance = SizeInfo.objects.get(id=size_id)
                except SizeInfo.DoesNotExist:
                    logger.warning(f"Size {size_id} from snapshot not found")
        
        # Получаем закупочную цену
        purchase_price = Decimal('0')
        if product.price_info and 'purchase_prices' in product.price_info:
            purchase_prices = product.price_info.get('purchase_prices', {})
            purchase_price = Decimal(str(
                purchase_prices.get('average', 0) or 
                purchase_prices.get('latest', 0)
            ))
        
        # Получаем поставщика из батчей
        supplier_name = get_supplier_from_batches(product, store, size_instance)
        
        # Обновляем или создаем аналитику поставщика
        today = timezone.now().date()
        
        try:
            # Используем select_for_update для атомарности
            analytics = SupplierAnalytics.objects.select_for_update().filter(
                store=store,
                date=today,
                supplier=supplier_name
            ).first()
            
            if not analytics:
                # Создаем новую запись
                analytics = SupplierAnalytics.objects.create(
                    store=store,
                    date=today,
                    supplier=supplier_name,
                    total_quantity_sold=0,
                    total_revenue=Decimal('0'),
                    total_cost=Decimal('0'),
                    total_margin=Decimal('0'),
                    products_count=0,
                    transactions_count=0,
                    unique_products_sold=0
                )
                logger.info(f"📈 Created new SupplierAnalytics for {supplier_name}")
            
            # Обновляем метрики
            sale_amount = Decimal(str(transaction_item.price)) * transaction_item.quantity
            cost_amount = purchase_price * transaction_item.quantity
            
            analytics.total_quantity_sold += transaction_item.quantity
            analytics.total_revenue += sale_amount
            analytics.total_cost += cost_amount
            analytics.total_margin = analytics.total_revenue - analytics.total_cost
            analytics.transactions_count += 1
            
            # Обновляем количество уникальных товаров (упрощенно)
            if not analytics.unique_products_sold:
                analytics.unique_products_sold = 1
            else:
                analytics.unique_products_sold += 1
            
            analytics.products_count += 1
            
            # Вызываем calculate_metrics если есть
            if hasattr(analytics, 'calculate_metrics'):
                analytics.calculate_metrics()
            
            analytics.save()
            
            logger.info(
                f"✅ SupplierAnalytics updated for {supplier_name}: "
                f"revenue={analytics.total_revenue}, margin={analytics.total_margin}"
            )
            
        except Exception as e:
            logger.error(f"❌ Error updating SupplierAnalytics: {str(e)}", exc_info=True)
    
    except Exception as e:
        logger.error(f"❌ Error in process_sale_analytics: {str(e)}", exc_info=True)


def get_supplier_from_batches(product, store, size=None):
    """
    Получает поставщика из батчей товара
    
    Args:
        product: экземпляр Product
        store: экземпляр Store
        size: экземпляр SizeInfo (опционально)
    
    Returns:
        str: имя поставщика или "Unknown"
    """
    try:
        # У Product есть related_name='batches' от ProductBatch
        batches = product.batches.filter(store=store)
        
        if not batches.exists():
            # Если нет батчей для этого магазина, берем любой
            batches = product.batches.all()
        
        # Приоритеты выбора батча:
        # 1. Батч с нужным размером
        if size:
            batch = batches.filter(size=size).order_by('-created_at').first()
            if batch and batch.supplier:
                logger.info(f"Found supplier from size-specific batch: {batch.supplier}")
                return batch.supplier
        
        # 2. Батч с остатком товара
        batch = batches.filter(quantity__gt=0).order_by('-quantity').first()
        if batch and batch.supplier:
            logger.info(f"Found supplier from batch with stock: {batch.supplier}")
            return batch.supplier
        
        # 3. Последний батч
        batch = batches.order_by('-created_at').first()
        if batch and batch.supplier:
            logger.info(f"Found supplier from latest batch: {batch.supplier}")
            return batch.supplier
        
        logger.warning(f"No supplier found for {product.name}")
        
    except Exception as e:
        logger.error(f"Error getting supplier from batches: {str(e)}")
    
    return "Unknown"


def update_batch_attributes_on_sale(product, quantity, size, store):
    """
    Обновляет атрибуты батчей при продаже (если требуется)
    """
    try:
        # Здесь можно добавить логику обновления батчей
        # Например, уменьшение quantity в батчах по FIFO
        pass
    except Exception as e:
        logger.error(f"Error updating batch attributes: {str(e)}")


# Дополнительный сигнал для отладки
@receiver(post_save, sender='analytics.SupplierAnalytics')
def debug_supplier_analytics_save(sender, instance, created, **kwargs):
    """
    Отладочный сигнал для проверки сохранения SupplierAnalytics
    """
    if created:
        logger.info(f"🆕 SupplierAnalytics created: {instance.supplier} - {instance.date}")
    else:
        logger.info(f"📝 SupplierAnalytics updated: {instance.supplier} - revenue: {instance.total_revenue}")


def update_batch_attributes_on_sale(product, sold_quantity, size_instance, store):
    """
    Распределение продажи по батчам товара
    """
    from inventory.models import ProductBatch
    
    # Находим активные батчи
    active_batches = ProductBatch.objects.filter(
        product=product,
        store=store,
        quantity__gt=0
    ).order_by('created_at')  # FIFO
    
    if not active_batches.exists():
        logger.debug(f"No active batches for {product.name}")
        return
    
    remaining_to_sell = sold_quantity
    
    for batch in active_batches:
        if remaining_to_sell <= 0:
            break
        
        # Вычисляем сколько взять из этого батча
        batch_share = min(batch.quantity, remaining_to_sell)
        
        # Обновляем батч
        batch.quantity -= batch_share
        batch.save(update_fields=['quantity'])
        
        remaining_to_sell -= batch_share
        
        logger.debug(f"Updated batch {batch.id}: -{batch_share}, remaining: {batch.quantity}")
    
    if remaining_to_sell > 0:
        logger.warning(f"⚠️ Could not allocate full sale {sold_quantity} for {product.name}, "
                      f"remaining: {remaining_to_sell}")


logger.info("✅ Sales signals loaded successfully")
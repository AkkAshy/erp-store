# # signals.py — исправленная версия с правильной обработкой наличных
from django.db.models.signals import post_save
from django.dispatch import receiver
# from django.utils import timezone
# from decimal import Decimal
import logging
from inventory.models import ProductBatch, ExchangeRate

# from sales.models import TransactionItem, Transaction
# from django.db.models import Sum, Count, F
logger = logging.getLogger(__name__)


@receiver(post_save, sender=ProductBatch)
def save_exchange_rate_from_batch(sender, instance, created, **kwargs):
    """
    Автоматически сохраняет курс при создании/обновлении батча с USD
    """
    if instance.purchase_price_usd and instance.purchase_rate:
        from datetime import date
        
        # Используем дату создания батча или сегодняшнюю
        batch_date = instance.created_at.date() if instance.created_at else date.today()
        
        ExchangeRate.objects.update_or_create(
            date=batch_date,
            defaults={'usd_rate': instance.purchase_rate}
        )
        
        logger.info(
            f"Курс {instance.purchase_rate} сохранен на {batch_date} "
            f"из батча {instance.id}"
        )

# def sanitize(value: str) -> str:
#     """Убирает опасные символы для SQLite"""
#     if not value:
#         return ""
#     return str(value).replace(":", "-")

# def should_process_cash_transaction(instance):
#     """
#     Определяем, нужно ли обрабатывать как наличную транзакцию
#     """
#     if instance.payment_method == 'cash':
#         # Для метода "наличные" проверяем total_amount
#         return instance.total_amount > 0
#     elif instance.payment_method == 'hybrid':
#         # Для гибридной оплаты проверяем cash_amount
#         return instance.cash_amount > 0
#     else:
#         # Для других методов наличная часть не обрабатывается
#         return False

# def get_effective_cash_amount(instance):
#     """
#     Возвращает эффективную сумму наличных с учетом метода оплаты
#     """
#     if instance.payment_method == 'cash':
#         return instance.total_amount
#     else:
#         return instance.cash_amount

# @receiver(post_save, sender=TransactionItem)
# def track_sales_from_transaction(sender, instance, created, **kwargs):
#     """
#     Каждая продажа → запись в StockHistory + обновление стока
#     """
#     if created and instance.transaction.status == 'completed':
        
#         product = instance.product
#         store = instance.store
#         transaction = instance.transaction
        
#         # Получаем текущий сток ДО продажи
#         stock, _ = Stock.objects.get_or_create(
#             product=product, 
#             store=store,
#             defaults={'quantity': 0}
#         )
#         quantity_before = stock.quantity
        
#         # Определяем размер из size_snapshot
#         size_instance = None
#         if instance.size_snapshot:
#             size_id = instance.size_snapshot.get('id')
#             if size_id:
#                 try:
#                     size_instance = SizeInfo.objects.get(id=size_id)
#                 except SizeInfo.DoesNotExist:
#                     logger.warning(f"Размер {size_id} из snapshot не найден")
        
#         # Безопасное форматирование notes без двоеточий
#         cashier_name = transaction.cashier.username if transaction.cashier else "Неизвестно"
#         customer_name = transaction.customer.name if transaction.customer else "Анонимный"
#         payment_method = str(transaction.payment_method)
#         quantity_str = str(float(instance.quantity))
        
#         safe_notes = sanitize(
#             f'Продажа чека {transaction.id} '
#             f'кассир {cashier_name} '
#             f'клиент {customer_name} '
#             f'метод {payment_method} '
#             f'количество {quantity_str}'
#         )
        
#         # Создаём запись истории стока
#         StockHistory.objects.create(
#             product=product,
#             store=store,
#             quantity_before=quantity_before,
#             quantity_after=quantity_before - instance.quantity,
#             quantity_change=-instance.quantity,
#             operation_type='SALE',
#             reference_id=f'txn_{transaction.id}_item_{instance.id}',
#             user=transaction.cashier,
#             size=size_instance,
#             sale_price_at_time=instance.price,
#             purchase_price_at_time=product.price_info['purchase_prices']['average'] if product.price_info else 0,
#             notes=safe_notes
#         )
        
#         # Обновляем текущий сток
#         stock.quantity -= instance.quantity
#         stock.save(update_fields=['quantity'])
        
#         # Логируем для дебага
#         logger.info(
#             f"✅ Продажа записана: {product.name} x{instance.quantity} "
#             f"по {instance.price} (сток: {quantity_before} → {stock.quantity})"
#         )
        
#         # Обновляем атрибуты батча (если есть)
#         update_batch_attributes_on_sale(product, instance.quantity, size_instance, store)

# def update_batch_attributes_on_sale(product, sold_quantity, size_instance, store):
#     """
#     ОТДЕЛЬНАЯ ФУНКЦИЯ: Распределяем продажу по атрибутам батча
#     """
#     # Находим активные батчи с атрибутами
#     active_batches = ProductBatch.objects.filter(
#         product=product,
#         store=store,
#         quantity__gt=0
#     ).select_related('attributes')
    
#     if not active_batches.exists():
#         logger.debug(f"Нет активных батчей для {product.name}")
#         return
    
#     # Распределяем пропорционально (простая логика)
#     total_available = sum(batch.quantity for batch in active_batches)
#     if total_available == 0:
#         logger.warning(f"Общий доступный сток для {product.name} равен 0")
#         return
    
#     remaining_to_sell = sold_quantity
#     for batch in active_batches:
#         if remaining_to_sell <= 0:
#             break
            
#         batch_share = min(
#             batch.quantity, 
#             remaining_to_sell * (batch.quantity / total_available)
#         )
        
#         # Обновляем батч
#         batch.quantity -= batch_share
#         batch.save(update_fields=['quantity'])
        
#         # Обновляем атрибуты батча
#         updated_attrs = 0
#         for batch_attr in batch.attributes.all():
#             if batch_attr.quantity > 0:
#                 attr_share = min(
#                     batch_attr.quantity, 
#                     batch_share * (batch_attr.quantity / batch.quantity if batch.quantity else 0)
#                 )
#                 batch_attr.quantity -= attr_share
#                 batch_attr.save(update_fields=['quantity'])
#                 updated_attrs += 1
        
#         remaining_to_sell -= batch_share
#         logger.debug(
#             f"Обновлён батч {batch.id}: -{batch_share}, "
#             f"атрибутов обновлено: {updated_attrs}"
#         )
    
#     if remaining_to_sell > 0:
#         logger.warning(
#             f"Не удалось распределить всю продажу {sold_quantity} "
#             f"для {product.name} — осталось {remaining_to_sell}"
#         )

# @receiver(post_save, sender=Transaction)
# def update_cash_register_and_analytics(sender, instance, created, **kwargs):
#     """
#     ИСПРАВЛЕННАЯ ФУНКЦИЯ: Обновление кассового аппарата и аналитики с правильной обработкой наличных
#     """
#     # Определяем фактическую наличную сумму
#     effective_cash_amount = get_effective_cash_amount(instance)
    
#     logger.info(f"💰 Cash signal triggered: Transaction {instance.id}, "
#                 f"created={created}, status={instance.status}")
#     logger.info(f"💰 Payment method: {instance.payment_method}, "
#                 f"cash_amount field: {instance.cash_amount}, "
#                 f"effective_cash_amount: {effective_cash_amount}, "
#                 f"total_amount: {instance.total_amount}, "
#                 f"Store: {instance.store.name}")
    
#     # Проверяем условия обработки
#     if not should_process_cash_transaction(instance):
#         logger.info(f"💰 Skipping: payment_method={instance.payment_method}, "
#                    f"effective_cash={effective_cash_amount}")
#         return
    
#     # Обрабатываем только завершенные транзакции
#     if instance.status != 'completed':
#         logger.info(f"💰 Skipping: transaction not completed, status={instance.status}")
#         return
    
#     logger.info(f"💳 Processing cash transaction: {effective_cash_amount} сум")
    
#     # Здесь можно добавить логику обновления кассового аппарата
#     # Например, обновление остатка наличных в кассе
    
#     # Логируем успешную обработку
#     logger.info(f"✅ Cash transaction processed: {effective_cash_amount} сум в магазине {instance.store.name}")

# @receiver(post_save, sender=Transaction)
# def track_transaction_financials(sender, instance, created, **kwargs):
#     """
#     Исправленная версия: анализируем гибридные оплаты
#     """
#     if created and instance.status == 'completed':
#         # Вычисляем реальную сумму (для гибридной оплаты)
#         actual_total = (
#             instance.cash_amount + 
#             instance.transfer_amount + 
#             instance.card_amount
#         )
        
#         if abs(actual_total - instance.total_amount) > Decimal('0.01'):  # Допуск на копейки
#             logger.warning(
#                 f"Несоответствие сумм в транзакции {instance.id}: "
#                 f"total_amount={instance.total_amount}, actual={actual_total}"
#             )
#             # Можно пометить как требующее проверки
#             # instance.needs_review = True  # Если добавишь такое поле
#             # instance.save(update_fields=['needs_review'])
        
#         # Обновляем дневную финансовую сводку
#         update_daily_financial_summary(instance)

# def update_daily_financial_summary(transaction):
#     """
#     Улучшенная версия обновления дневной финансовой сводки
#     Теперь включает автоматический расчет маржи
#     """
#     from stores.models import FinancialSummary
#     from sales.models import Transaction
#     from decimal import Decimal
#     from django.db.models import Sum, Count, Avg
#     import logging
    
#     logger = logging.getLogger(__name__)
    
#     try:
#         # Получаем или создаем сводку за день транзакции
#         summary, created = FinancialSummary.objects.get_or_create(
#             date=transaction.created_at.date(),
#             store=transaction.store,
#             defaults={
#                 'total_transactions': 0,
#                 'grand_total': Decimal('0'),
#                 'total_margin': Decimal('0'),
#                 'margin_percentage': Decimal('0'),
#                 'cash_total': Decimal('0'),
#                 'transfer_total': Decimal('0'),
#                 'card_total': Decimal('0'),
#                 'debt_total': Decimal('0'),
#                 'unique_customers': 0,
#                 'repeat_customers': 0,
#                 'customer_retention_rate': Decimal('0'),
#             }
#         )
        
#         if created:
#             logger.info(f"📊 Создана финансовая сводка: {transaction.store.name} - {transaction.created_at.date()}")
        
#         # Получаем все завершенные транзакции за день
#         daily_transactions = Transaction.objects.filter(
#             store=transaction.store,
#             created_at__date=transaction.created_at.date(),
#             status='completed'
#         )
        
#         # Агрегированная статистика по транзакциям
#         transaction_stats = daily_transactions.aggregate(
#             total_count=Count('id'),
#             total_amount=Sum('total_amount') or Decimal('0'),
#             avg_amount=Avg('total_amount') or Decimal('0'),
#             total_cash=Sum('cash_amount') or Decimal('0'),
#             total_transfer=Sum('transfer_amount') or Decimal('0'),
#             total_card=Sum('card_amount') or Decimal('0'),
#             total_debt=Sum('debt_amount') or Decimal('0'),
#         )
        
#         # Обновляем основные финансовые показатели
#         summary.total_transactions = transaction_stats['total_count']
#         summary.grand_total = transaction_stats['total_amount']
#         summary.avg_transaction = transaction_stats['avg_amount']
#         summary.cash_total = transaction_stats['total_cash']
#         summary.transfer_total = transaction_stats['total_transfer']
#         summary.card_total = transaction_stats['total_card']
#         summary.debt_total = transaction_stats['total_debt']
        
#         # Расчет клиентских метрик
#         update_customer_metrics(summary, daily_transactions)
        
#         # Определение топ-кассира
#         update_top_cashier(summary, daily_transactions)
        
#         # Сохраняем базовые изменения
#         summary.save()
        
#         # ГЛАВНОЕ: Расчет маржи
#         margin_result = summary.calculate_margins()
        
#         # Логирование результатов
#         logger.info(
#             f"💰 Обновлена сводка {summary.store.name} ({summary.date}):\n"
#             f"   Транзакций: {summary.total_transactions}\n"
#             f"   Выручка: {summary.grand_total:,.0f} сум\n"
#             f"   Маржа: {margin_result.get('margin', 0):,.0f} сум ({margin_result.get('margin_percentage', 0):.1f}%)\n"
#             f"   Клиентов: {summary.unique_customers} (повторных: {summary.repeat_customers})"
#         )
        
#         # Проверка на аномалии
#         check_summary_anomalies(summary, margin_result)
        
#         return summary
        
#     except Exception as e:
#         logger.error(
#             f"❌ Ошибка обновления финансовой сводки для транзакции {transaction.id}: {str(e)}",
#             exc_info=True
#         )
#         return None

# def update_customer_metrics(summary, transactions):
#     """
#     Обновляет метрики по клиентам
#     """
#     customers_today = set()
#     repeat_customers_count = 0
    
#     for trans in transactions:
#         if trans.customer_id:  # Если есть привязка к клиенту
#             customers_today.add(trans.customer_id)
            
#             # Проверяем, покупал ли клиент ранее
#             previous_purchases = Transaction.objects.filter(
#                 customer_id=trans.customer_id,
#                 created_at__date__lt=summary.date,
#                 status='completed'
#             ).exists()
            
#             if previous_purchases:
#                 repeat_customers_count += 1
    
#     summary.unique_customers = len(customers_today)
#     summary.repeat_customers = repeat_customers_count
#     summary.customer_retention_rate = (
#         Decimal(repeat_customers_count) / Decimal(len(customers_today)) * 100
#         if customers_today else Decimal('0')
#     )

# def update_top_cashier(summary, transactions):
#     """
#     Определяет лучшего кассира дня
#     """
#     from django.db.models import Sum
#     from stores.models import Employee
    
#     # Группируем продажи по кассирам
#     cashier_stats = transactions.values('cashier_id').annotate(
#         total_sales=Sum('total_amount')
#     ).order_by('-total_sales')
    
#     if cashier_stats and cashier_stats[0]['cashier_id']:
#         try:
#             top_cashier = Employee.objects.get(id=cashier_stats[0]['cashier_id'])
#             summary.top_cashier = top_cashier
#             summary.top_cashier_sales = cashier_stats[0]['total_sales']
#         except Employee.DoesNotExist:
#             summary.top_cashier = None
#             summary.top_cashier_sales = Decimal('0')

# def check_summary_anomalies(summary, margin_result):
#     """
#     Проверяет финансовую сводку на аномалии и предупреждения
#     """
#     import logging
#     logger = logging.getLogger(__name__)
    
#     warnings = []
    
#     # Проверка 1: Маржа = 0 при наличии выручки
#     if summary.grand_total > 0 and summary.total_margin == 0:
#         warnings.append("🔴 Нулевая маржа при ненулевой выручке")
    
#     # Проверка 2: Отрицательная маржа
#     if summary.total_margin < 0:
#         warnings.append(f"🔴 Отрицательная маржа: {summary.total_margin:,.0f} сум")
    
#     # Проверка 3: Очень низкая маржа (< 5%)
#     if 0 < summary.margin_percentage < 5:
#         warnings.append(f"🟡 Низкая маржа: {summary.margin_percentage:.1f}%")
    
#     # Проверка 4: Несоответствие сумм оплат и общей суммы
#     payment_total = (
#         summary.cash_total + 
#         summary.transfer_total + 
#         summary.card_total + 
#         summary.debt_total
#     )
    
#     if abs(payment_total - summary.grand_total) > Decimal('1'):  # Допуск 1 сум
#         warnings.append(
#             f"🟡 Несоответствие сумм: "
#             f"итого {summary.grand_total:,.0f}, оплат {payment_total:,.0f}"
#         )
    
#     # Проверка 5: Необычно высокий средний чек
#     if summary.avg_transaction > 500000:  # > 500k сум
#         warnings.append(f"🟡 Высокий средний чек: {summary.avg_transaction:,.0f} сум")
    
#     # Логируем предупреждения
#     if warnings:
#         logger.warning(
#             f"⚠️ Аномалии в сводке {summary.store.name} ({summary.date}):\n" +
#             "\n".join(f"   {w}" for w in warnings)
#         )

# # Функция для массового пересчета (можно вызвать в Django shell)
# def recalculate_recent_summaries(days=7):
#     """
#     Пересчитывает финансовые сводки за последние N дней
#     """
#     from stores.models import FinancialSummary
#     from datetime import date, timedelta
#     import logging
    
#     logger = logging.getLogger(__name__)
    
#     start_date = date.today() - timedelta(days=days)
    
#     summaries = FinancialSummary.objects.filter(
#         date__gte=start_date,
#         grand_total__gt=0
#     ).order_by('date', 'store__name')
    
#     logger.info(f"🔄 Начинаем пересчет {summaries.count()} сводок за {days} дней")
    
#     updated_count = 0
#     for summary in summaries:
#         try:
#             old_margin = summary.total_margin
#             result = summary.calculate_margins()
            
#             if abs(result['margin'] - old_margin) > Decimal('0.01'):
#                 logger.info(
#                     f"✅ {summary.store.name} {summary.date}: "
#                     f"маржа {old_margin:,.0f} → {result['margin']:,.0f} сум"
#                 )
#                 updated_count += 1
            
#         except Exception as e:
#             logger.error(f"❌ Ошибка пересчета {summary}: {e}")
    
#     logger.info(f"✅ Обновлено {updated_count} сводок")
#     return updated_count


# @receiver(post_save, sender=Transaction)
# def handle_transaction_refund(sender, instance, **kwargs):
#     """
#     Обработка возврата/отмены транзакции — возвращаем сток
#     """
#     if instance.status == 'refunded' and not hasattr(instance, '_original_status'):
#         # Это возврат — возвращаем товары на склад
        
#         for item in instance.items.all():
#             # Возвращаем сток
#             stock, _ = Stock.objects.get_or_create(
#                 product=item.product,
#                 store=instance.store
#             )
#             stock.quantity += item.quantity
#             stock.save(update_fields=['quantity'])
            
#             # Создаём запись возврата в истории
#             StockHistory.objects.create(
#                 product=item.product,
#                 store=instance.store,
#                 quantity_before=stock.quantity - item.quantity,
#                 quantity_after=stock.quantity,
#                 quantity_change=item.quantity,  # Положительное для возврата
#                 operation_type='RETURN',
#                 reference_id=f'refund_{instance.id}_item_{item.id}',
#                 user=instance.cashier,
#                 size_id=item.size_snapshot.get('id') if item.size_snapshot else None,
#                 notes=f'Возврат по транзакции {instance.id}'
#             )
            
#             logger.info(
#                 f"✅ Возврат обработан: {item.product.name} x{item.quantity} "
#                 f"(сток: {stock.quantity - item.quantity} → {stock.quantity})"
#             )
    
#     # Сохраняем оригинальный статус для отслеживания изменений
#     if not hasattr(instance, '_original_status'):
#         instance._original_status = instance.status
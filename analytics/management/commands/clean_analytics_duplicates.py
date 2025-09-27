from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Sum
from analytics.models import SalesSummary, ProductAnalytics, CustomerAnalytics
from sales.models import Transaction
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Очищает дублирующие записи в аналитике'

    def add_arguments(self, parser):
        parser.add_argument('--store-id', type=str, required=True, help='ID магазина')
        parser.add_argument('--execute', action='store_true', help='Выполнить очистку')
        parser.add_argument('--verbose', action='store_true', help='Подробный вывод')

    def handle(self, *args, **options):
        store_id = options['store_id']
        execute = options.get('execute', False)
        verbose = options.get('verbose', False)

        if not execute:
            self.stdout.write(self.style.WARNING('🔍 РЕЖИМ ПРОСМОТРА. Добавьте --execute для выполнения'))

        total_cleaned = 0

        # 1. Очищаем SalesSummary
        total_cleaned += self._clean_sales_summary(store_id, execute, verbose)

        # 2. Очищаем ProductAnalytics
        total_cleaned += self._clean_product_analytics(store_id, execute, verbose)

        # 3. Очищаем CustomerAnalytics
        total_cleaned += self._clean_customer_analytics(store_id, execute, verbose)

        if execute:
            self.stdout.write(self.style.SUCCESS(f'✅ Очистка завершена. Удалено {total_cleaned} дублирующих записей'))
        else:
            self.stdout.write(self.style.WARNING(f'👀 Найдено {total_cleaned} дублирующих записей'))

    def _clean_sales_summary(self, store_id, execute, verbose):
        """Очищает дубли в SalesSummary"""
        self.stdout.write('\n📊 Проверка SalesSummary...')

        # Найти группы с дублями
        duplicates = SalesSummary.objects.filter(
            store_id=store_id
        ).values('store', 'date', 'payment_method').annotate(
            count=Count('id')
        ).filter(count__gt=1)

        if not duplicates.exists():
            self.stdout.write('   ✅ Дублей не найдено')
            return 0

        cleaned_count = 0

        for dup in duplicates:
            store = dup['store']
            date = dup['date']
            payment_method = dup['payment_method']

            if verbose:
                self.stdout.write(f'   🔍 Группа: {date} {payment_method} ({dup["count"]} записей)')

            if execute:
                with transaction.atomic():
                    # Получаем все записи группы
                    records = SalesSummary.objects.filter(
                        store=store,
                        date=date,
                        payment_method=payment_method
                    ).order_by('id')

                    # Вычисляем правильные значения из реальных транзакций
                    real_transactions = Transaction.objects.filter(
                        store=store,
                        created_at__date=date,
                        payment_method=payment_method,
                        status='completed'
                    )

                    correct_amount = real_transactions.aggregate(
                        total=Sum('total_amount')
                    )['total'] or 0

                    correct_count = real_transactions.count()

                    correct_items = 0
                    for tx in real_transactions:
                        items_sum = tx.items.aggregate(Sum('quantity'))['quantity__sum']
                        correct_items += items_sum or 0

                    # Обновляем первую запись правильными значениями
                    first_record = records.first()
                    first_record.total_amount = correct_amount
                    first_record.total_transactions = correct_count
                    first_record.total_items_sold = correct_items
                    first_record.save()

                    # Удаляем дубли
                    duplicates_to_delete = records.exclude(id=first_record.id)
                    deleted_count = duplicates_to_delete.count()
                    duplicates_to_delete.delete()

                    cleaned_count += deleted_count

                    if verbose:
                        self.stdout.write(f'     ✅ Исправлено: {correct_amount} ({correct_count} транзакций)')
                        self.stdout.write(f'     🗑️ Удалено {deleted_count} дублей')
            else:
                cleaned_count += dup['count'] - 1  # Все кроме одной записи

        self.stdout.write(f'   📈 SalesSummary: {"удалено" if execute else "найдено"} {cleaned_count} дублей')
        return cleaned_count

    def _clean_product_analytics(self, store_id, execute, verbose):
        """Очищает дубли в ProductAnalytics"""
        self.stdout.write('\n🛍️ Проверка ProductAnalytics...')

        duplicates = ProductAnalytics.objects.filter(
            product__store_id=store_id
        ).values('product', 'date').annotate(
            count=Count('id')
        ).filter(count__gt=1)

        if not duplicates.exists():
            self.stdout.write('   ✅ Дублей не найдено')
            return 0

        cleaned_count = 0

        for dup in duplicates:
            if execute:
                with transaction.atomic():
                    records = ProductAnalytics.objects.filter(
                        product=dup['product'],
                        date=dup['date']
                    ).order_by('id')

                    # Оставляем первую запись, удаляем остальные
                    first_record = records.first()
                    duplicates_to_delete = records.exclude(id=first_record.id)
                    deleted_count = duplicates_to_delete.count()
                    duplicates_to_delete.delete()

                    cleaned_count += deleted_count
            else:
                cleaned_count += dup['count'] - 1

        self.stdout.write(f'   🛍️ ProductAnalytics: {"удалено" if execute else "найдено"} {cleaned_count} дублей')
        return cleaned_count

    def _clean_customer_analytics(self, store_id, execute, verbose):
        """Очищает дубли в CustomerAnalytics"""
        self.stdout.write('\n👥 Проверка CustomerAnalytics...')

        duplicates = CustomerAnalytics.objects.filter(
            customer__store_id=store_id
        ).values('customer', 'date').annotate(
            count=Count('id')
        ).filter(count__gt=1)

        if not duplicates.exists():
            self.stdout.write('   ✅ Дублей не найдено')
            return 0

        cleaned_count = 0

        for dup in duplicates:
            if execute:
                with transaction.atomic():
                    records = CustomerAnalytics.objects.filter(
                        customer=dup['customer'],
                        date=dup['date']
                    ).order_by('id')

                    # Оставляем первую запись, удаляем остальные
                    first_record = records.first()
                    duplicates_to_delete = records.exclude(id=first_record.id)
                    deleted_count = duplicates_to_delete.count()
                    duplicates_to_delete.delete()

                    cleaned_count += deleted_count
            else:
                cleaned_count += dup['count'] - 1

        self.stdout.write(f'   👥 CustomerAnalytics: {"удалено" if execute else "найдено"} {cleaned_count} дублей')
        return cleaned_count
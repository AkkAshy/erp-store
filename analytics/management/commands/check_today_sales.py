from django.core.management.base import BaseCommand
from decimal import Decimal
from datetime import date

from sales.models import Transaction
from stores.models import  Store
from inventory.models import FinancialSummary


class Command(BaseCommand):
    help = "Анализ продаж за сегодня и проверка автоматического расчета маржи"

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("📊 АНАЛИЗ ПРОДАЖ ЗА СЕГОДНЯ")
        self.stdout.write("=" * 60)

        today = date.today()
        store = Store.objects.get(name="Akkanat")

        self.stdout.write(f"📅 Дата: {today}")
        self.stdout.write(f"🏪 Магазин: {store.name}")

        # Все сегодняшние транзакции
        today_transactions = Transaction.objects.filter(
            store=store,
            created_at__date=today,
            status="completed"
        ).order_by("-created_at")

        self.stdout.write(f"🛒 Всего транзакций за сегодня: {today_transactions.count()}")

        if not today_transactions.exists():
            self.stdout.write("❌ Нет завершенных транзакций за сегодня")
            return

        total_today = Decimal("0")

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("ДЕТАЛИ ТРАНЗАКЦИЙ:")
        self.stdout.write("=" * 50)

        for i, trans in enumerate(today_transactions, 1):
            self.stdout.write(f"\n🧾 Транзакция #{trans.id} ({i}/{today_transactions.count()})")
            self.stdout.write(f"   Время: {trans.created_at.strftime('%H:%M:%S')}")
            self.stdout.write(f"   Сумма: {trans.total_amount:,.0f} сум")
            self.stdout.write(f"   Статус: {trans.status}")

            items = trans.items.all()
            self.stdout.write(f"   Товаров: {items.count()}")

            for item in items:
                self.stdout.write(f"     📦 {item.product.name}")
                self.stdout.write(f"        Количество: {item.quantity}")
                self.stdout.write(f"        Цена: {item.price:,.0f} сум")
                self.stdout.write(f"        Сумма: {item.quantity * item.price:,.0f} сум")

            total_today += trans.total_amount

        self.stdout.write(f"\n💰 ОБЩИЙ ОБОРОТ ЗА СЕГОДНЯ: {total_today:,.0f} сум")

        # Проверка финансовой сводки
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("ПРОВЕРКА ФИНАНСОВОЙ СВОДКИ:")
        self.stdout.write("=" * 50)

        try:
            summary = FinancialSummary.objects.get(date=today, store=store)
            self.stdout.write(f"📊 Финансовая сводка найдена (ID {summary.id})")
            self.stdout.write(f"   Транзакций: {summary.total_transactions}")
            self.stdout.write(f"   Выручка: {summary.grand_total:,.0f} сум")
            self.stdout.write(f"   Маржа: {summary.total_margin:,.0f} сум")
            self.stdout.write(f"   % маржи: {summary.margin_percentage:.2f}%")
            self.stdout.write(f"   Последнее обновление: {summary.updated_at}")

            if abs(summary.grand_total - total_today) > 1:
                self.stdout.write("⚠️ РАСХОЖДЕНИЕ в выручке!")
            if summary.total_margin == 0 and summary.grand_total > 0:
                self.stdout.write("🔴 ПРОБЛЕМА: нулевая маржа при ненулевой выручке!")

        except FinancialSummary.DoesNotExist:
            self.stdout.write("❌ Финансовая сводка за сегодня НЕ найдена!")

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("🎯 ИТОГ")
        self.stdout.write("=" * 60)
        self.stdout.write(f"📊 Обработано транзакций: {today_transactions.count()}")
        self.stdout.write(f"💰 Общий оборот: {total_today:,.0f} сум")

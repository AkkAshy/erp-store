# stores/management/commands/debug_stores.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from stores.models import Store, StoreEmployee

class Command(BaseCommand):
    help = 'Отладка состояния магазинов и пользователей'

    def add_arguments(self, parser):
        parser.add_argument('--user', type=str, help='Username для проверки')

    def handle(self, *args, **options):
        username = options.get('user')
        
        self.stdout.write(self.style.SUCCESS('=== ОТЛАДКА МАГАЗИНОВ ==='))
        
        # Показать все магазины
        stores = Store.objects.all()
        self.stdout.write(f"\n📊 Всего магазинов: {stores.count()}")
        for store in stores:
            self.stdout.write(f"  🏪 {store.name} (ID: {store.id}, Owner: {store.owner.username})")
        
        # Показать всех пользователей с магазинами
        users_with_stores = User.objects.filter(store_memberships__isnull=False).distinct()
        self.stdout.write(f"\n👥 Пользователей с магазинами: {users_with_stores.count()}")
        
        for user in users_with_stores:
            memberships = StoreEmployee.objects.filter(user=user)
            self.stdout.write(f"\n  👤 {user.username}:")
            for membership in memberships:
                active = "✅" if membership.is_active else "❌"
                self.stdout.write(f"    {active} {membership.store.name} ({membership.role})")
        
        # Детальная информация о конкретном пользователе
        if username:
            try:
                user = User.objects.get(username=username)
                self.stdout.write(f"\n🔍 ДЕТАЛИ ПОЛЬЗОВАТЕЛЯ: {username}")
                self.stdout.write(f"  ID: {user.id}")
                self.stdout.write(f"  Email: {user.email}")
                self.stdout.write(f"  Активен: {user.is_active}")
                
                memberships = StoreEmployee.objects.filter(user=user)
                self.stdout.write(f"  Магазинов: {memberships.count()}")
                
                for membership in memberships:
                    self.stdout.write(f"    - {membership.store.name}:")
                    self.stdout.write(f"      ID: {membership.store.id}")
                    self.stdout.write(f"      Роль: {membership.role}")
                    self.stdout.write(f"      Активен: {membership.is_active}")
                    self.stdout.write(f"      Владелец: {membership.store.owner.username}")
                
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"❌ Пользователь '{username}' не найден"))
        
        self.stdout.write(self.style.SUCCESS('\n✅ Отладка завершена'))
# auth/management/commands/setup_groups.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission

class Command(BaseCommand):
    help = 'Создаёт группы и назначает разрешения'

    def handle(self, *args, **kwargs):
        admin_group, _ = Group.objects.get_or_create(name='admin')
        stockkeeper_group, _ = Group.objects.get_or_create(name='stockkeeper')
        manager_group, _ = Group.objects.get_or_create(name='manager')
        cashier_group, _ = Group.objects.get_or_create(name='cashier')

        admin_permissions = Permission.objects.all()
        admin_group.permissions.set(admin_permissions)

        stockkeeper_permissions = Permission.objects.filter(
            content_type__app_label='inventory',
            codename__in=[
                'add_product', 'change_product', 'view_product',
                'add_productbatch', 'change_productbatch', 'view_productbatch',
                'add_stock', 'change_stock', 'view_stock',
                'add_productcategory', 'view_productcategory'
            ]
        )
        stockkeeper_group.permissions.set(stockkeeper_permissions)

        manager_permissions = Permission.objects.filter(
            content_type__app_label__in=['sales', 'customers'],
            codename__in=[
                'add_transaction', 'change_transaction', 'view_transaction',
                'add_transactionitem', 'view_transactionitem',
                'add_customer', 'change_customer', 'view_customer'
            ]
        )
        manager_group.permissions.set(manager_permissions)

        cashier_permissions = Permission.objects.filter(
            content_type__app_label='sales',
            codename__in=[
                'add_transaction', 'view_transaction',
                'add_transactionitem', 'view_transactionitem'
            ]
        )
        cashier_group.permissions.set(cashier_permissions)

        self.stdout.write(self.style.SUCCESS('Группы и разрешения успешно настроены'))
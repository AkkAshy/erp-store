# stores/admin.py
from django.contrib import admin
from .models import Store, StoreEmployee

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'is_active', 'currency', 'created_at']
    list_filter = ['is_active', 'currency', 'created_at']
    search_fields = ['name', 'address', 'owner__username']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'logo', 'description', 'owner')
        }),
        ('Контакты', {
            'fields': ('address', 'phone', 'email')
        }),
        ('Настройки', {
            'fields': ('is_active', 'currency', 'tax_rate', 'low_stock_threshold')
        }),
        ('Метаданные', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

@admin.register(StoreEmployee)
class StoreEmployeeAdmin(admin.ModelAdmin):
    list_display = ['user', 'store', 'role', 'is_active', 'joined_at']
    list_filter = ['role', 'is_active', 'joined_at', 'store']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'store__name']
    readonly_fields = ['joined_at']
    
    fieldsets = (
        ('Основное', {
            'fields': ('store', 'user', 'role', 'is_active')
        }),
        ('Разрешения', {
            'fields': ('can_manage_products', 'can_manage_sales', 'can_view_analytics', 'can_manage_employees')
        }),
        ('Метаданные', {
            'fields': ('joined_at',),
            'classes': ('collapse',)
        })
    )
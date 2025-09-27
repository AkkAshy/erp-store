# stores/serializers.py
from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Store, StoreEmployee
from users.serializers import UserSerializer

class StoreSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    employees_count = serializers.IntegerField(source='store_employees.count', read_only=True)
    
    class Meta:
        model = Store
        fields = [
            'id', 'name', 'logo', 'address', 'phone', 'email',
            'description', 'owner', 'owner_name', 'is_active',
            'currency', 'tax_rate', 'low_stock_threshold',
            'created_at', 'updated_at', 'employees_count'
        ]
        read_only_fields = ['id', 'owner', 'created_at', 'updated_at']
    
    def validate_name(self, value):
        """Проверяем уникальность имени магазина"""
        if Store.objects.filter(name__iexact=value).exists():
            if not self.instance or self.instance.name.lower() != value.lower():
                raise serializers.ValidationError("Магазин с таким названием уже существует")
        return value


class StoreCreateSerializer(serializers.ModelSerializer):
    """Сериализатор для создания магазина при регистрации"""
    class Meta:
        model = Store
        fields = ['name', 'logo', 'address', 'phone', 'email', 'description', 'currency', 'tax_rate']
    
    def validate_name(self, value):
        if Store.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError("Магазин с таким названием уже существует")
        return value


class StoreEmployeeSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='user',
        write_only=True
    )
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    class Meta:
        model = StoreEmployee
        fields = [
            'id', 'store', 'store_name', 'user', 'user_id',
            'role', 'joined_at', 'is_active',
            'can_manage_products', 'can_manage_sales',
            'can_view_analytics', 'can_manage_employees'
        ]
        read_only_fields = ['joined_at']
    
    def validate(self, attrs):
        """Проверяем, что пользователь не добавлен дважды в один магазин"""
        store = attrs.get('store')
        user = attrs.get('user')
        
        if store and user:
            exists = StoreEmployee.objects.filter(store=store, user=user)
            if self.instance:
                exists = exists.exclude(pk=self.instance.pk)
            
            if exists.exists():
                raise serializers.ValidationError(
                    "Этот пользователь уже добавлен в данный магазин"
                )
        
        return attrs


class StoreSwitchSerializer(serializers.Serializer):
    """Сериализатор для переключения между магазинами"""
    store_id = serializers.UUIDField(required=True)
    
    def validate_store_id(self, value):
        user = self.context['request'].user
        
        # Проверяем, что пользователь является сотрудником этого магазина
        if not StoreEmployee.objects.filter(
            user=user,
            store_id=value,
            is_active=True
        ).exists():
            raise serializers.ValidationError(
                "У вас нет доступа к этому магазину"
            )
        
        return value
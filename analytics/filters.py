# analytics/filters.py
from django_filters import rest_framework as filters
from .models import SalesSummary, ProductAnalytics, CustomerAnalytics

class SalesSummaryFilter(filters.FilterSet):
    date_gte = filters.DateFilter(field_name='date', lookup_expr='gte')
    date_lte = filters.DateFilter(field_name='date', lookup_expr='lte')

    class Meta:
        model = SalesSummary
        fields = ['date', 'payment_method']

class ProductAnalyticsFilter(filters.FilterSet):
    date_gte = filters.DateFilter(field_name='date', lookup_expr='gte')
    date_lte = filters.DateFilter(field_name='date', lookup_expr='lte')

    class Meta:
        model = ProductAnalytics
        fields = ['product', 'date']

class CustomerAnalyticsFilter(filters.FilterSet):
    date_gte = filters.DateFilter(field_name='date', lookup_expr='gte')
    date_lte = filters.DateFilter(field_name='date', lookup_expr='lte')

    class Meta:
        model = CustomerAnalytics
        fields = ['customer', 'date']
from rest_framework.pagination import LimitOffsetPagination, PageNumberPagination
from rest_framework.response import Response
from collections import OrderedDict


class CustomLimitOffsetPagination(LimitOffsetPagination):
    """
    Кастомная пагинация с offset/limit
    Можно использовать для любых ViewSet'ов в проекте
    """
    default_limit = 20
    limit_query_param = 'limit'
    offset_query_param = 'offset'
    max_limit = 100

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.count),
            ('limit', self.limit),
            ('offset', self.offset),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))


class SizeInfoPagination(CustomLimitOffsetPagination):
    """
    Специализированная пагинация для размерной информации
    """
    default_limit = 20
    max_limit = 50  # Меньший лимит для размеров

    def get_paginated_response(self, data):
        response_data = OrderedDict([
            ('pagination_info', {
                'total_count': self.count,
                'current_limit': self.limit,
                'current_offset': self.offset,
                'has_next': self.get_next_link() is not None,
                'has_previous': self.get_previous_link() is not None,
                'next_url': self.get_next_link(),
                'previous_url': self.get_previous_link(),
            }),
            ('results', data)
        ])
        return Response(response_data)


class OptionalPagination(CustomLimitOffsetPagination):
    """
    Пагинация которая работает только при явном указании параметров
    Если параметры не указаны - возвращает все результаты
    """

    def paginate_queryset(self, queryset, request, view=None):
        """
        Переопределяем метод для проверки наличия параметров пагинации
        """
        # Проверяем есть ли параметры пагинации в запросе
        has_limit = self.limit_query_param in request.query_params
        has_offset = self.offset_query_param in request.query_params

        # Если нет параметров пагинации - не пагинируем
        if not has_limit and not has_offset:
            return None

        # Иначе используем стандартную пагинацию
        return super().paginate_queryset(queryset, request, view)


class SmallPagePagination(PageNumberPagination):
    """
    Пагинация по номерам страниц (альтернативный подход)
    """
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        return Response({
            'page_info': {
                'current_page': self.page.number,
                'total_pages': self.page.paginator.num_pages,
                'page_size': self.page_size,
                'total_count': self.page.paginator.count,
                'has_next': self.page.has_next(),
                'has_previous': self.page.has_previous(),
            },
            'links': {
                'next': self.get_next_link(),
                'previous': self.get_previous_link()
            },
            'results': data
        })


class ProductPagination(CustomLimitOffsetPagination):
    """
    Пагинация для продуктов (если понадобится в будущем)
    """
    default_limit = 15
    max_limit = 100

    def get_paginated_response(self, data):
        return Response({
            'meta': {
                'total': self.count,
                'limit': self.limit,
                'offset': self.offset,
                'next': self.get_next_link(),
                'previous': self.get_previous_link(),
            },
            'data': data
        })
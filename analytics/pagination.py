from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from collections import OrderedDict


class OptionalPagination(LimitOffsetPagination):
    """
    Пагинация которая работает только при явном указании параметров limit или offset.
    Если параметры не указаны - возвращает все результаты без пагинации.
    """
    default_limit = 20
    limit_query_param = 'limit'
    offset_query_param = 'offset'
    max_limit = 100

    def paginate_queryset(self, queryset, request, view=None):
        """
        Переопределяем метод для проверки наличия параметров пагинации.
        Возвращает None если параметры пагинации не указаны.
        """
        # Проверяем есть ли параметры пагинации в запросе
        has_limit = self.limit_query_param in request.query_params
        has_offset = self.offset_query_param in request.query_params

        # Если нет ни одного параметра пагинации - не пагинируем
        if not has_limit and not has_offset:
            return None

        # Иначе используем стандартную пагинацию
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        """
        Формат ответа с пагинацией
        """
        return Response(OrderedDict([
            ('count', self.count),
            ('limit', self.limit),
            ('offset', self.offset),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))


# Альтернативная версия с более подробной информацией
class DetailedOptionalPagination(LimitOffsetPagination):
    """
    Опциональная пагинация с более детальной информацией в ответе
    """
    default_limit = 20
    limit_query_param = 'limit'
    offset_query_param = 'offset'
    max_limit = 100

    def paginate_queryset(self, queryset, request, view=None):
        """
        Проверяем наличие параметров пагинации
        """
        has_limit = self.limit_query_param in request.query_params
        has_offset = self.offset_query_param in request.query_params

        if not has_limit and not has_offset:
            return None

        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        """
        Детальный формат ответа
        """
        # Вычисляем дополнительную информацию
        current_page = (self.offset // self.limit) + 1 if self.limit > 0 else 1
        total_pages = (self.count + self.limit - 1) // self.limit if self.limit > 0 else 1
        has_next = self.get_next_link() is not None
        has_previous = self.get_previous_link() is not None

        return Response(OrderedDict([
            ('pagination_info', {
                'total_count': self.count,
                'current_limit': self.limit,
                'current_offset': self.offset,
                'current_page': current_page,
                'total_pages': total_pages,
                'has_next_page': has_next,
                'has_previous_page': has_previous,
                'items_on_current_page': len(data)
            }),
            ('links', {
                'next': self.get_next_link(),
                'previous': self.get_previous_link()
            }),
            ('results', data)
        ]))


# Простая версия только с основной информацией
class SimpleOptionalPagination(LimitOffsetPagination):
    """
    Упрощенная опциональная пагинация
    """
    default_limit = 20
    limit_query_param = 'limit'
    offset_query_param = 'offset'
    max_limit = 100

    def paginate_queryset(self, queryset, request, view=None):
        has_limit = self.limit_query_param in request.query_params
        has_offset = self.offset_query_param in request.query_params

        if not has_limit and not has_offset:
            return None

        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        return Response({
            'count': self.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data
        })
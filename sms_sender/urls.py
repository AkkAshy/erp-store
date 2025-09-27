from django.urls import path
from .views import SmsSenderViewSet, SendSmsFlexibleView, TemplatePreviewView

urlpatterns = [
    path('', SmsSenderViewSet.as_view({'get': 'list', 'post': 'create'}), name='sms-list'),
    path('<int:pk>/', SmsSenderViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}), name='sms-detail'),
    path('send-sms/', SendSmsFlexibleView.as_view(), name='send-sms'),
    path('send-sms/<int:template_id>/', SendSmsFlexibleView.as_view(), name='send-sms-template'),
    path('preview/<int:template_id>/', TemplatePreviewView.as_view(), name='template-preview'),
]
# users/urls.py
from django.urls import path
from .views import (
    RegisterView, ProfileUpdateView, UserListView, 
    ProfileView, UserDetailView, CustomTokenObtainPairView
)
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('profile-update/', ProfileUpdateView.as_view(), name='profile_update'),
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/<int:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('profile/', ProfileView.as_view(), name='profile'),
    
    # ИЗМЕНЕНО: Используем кастомный view вместо стандартного
    path('login/', CustomTokenObtainPairView.as_view(), name='login'),
    
    path('register/', RegisterView.as_view(), name='register'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
from django.urls import path
from .views import LoginView, LogoutView, RegisterView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('token/', LoginView.as_view(), name='token'),   # matches frontend /api/auth/token/
    path('logout/', LogoutView.as_view(), name='logout'),
]

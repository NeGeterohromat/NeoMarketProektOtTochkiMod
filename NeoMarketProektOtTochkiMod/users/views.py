from django.contrib.auth import get_user_model
from rest_framework import generics, permissions

from .serializers import RegisterSerializer

User = get_user_model()


# Добавить правильный ответ на 422 Validation Error
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer

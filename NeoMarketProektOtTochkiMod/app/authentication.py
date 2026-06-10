from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework import exceptions

class ServiceKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_key = request.META.get('HTTP_X_SERVICE_KEY')
        if not auth_key:
            # Ключа нет - возвращаем None, чтобы DRF попробовал другие аутентификаторы
            return None

        valid_key = settings.B2B_TO_MOD_KEY
        if auth_key != valid_key:
            raise exceptions.AuthenticationFailed('Invalid Service Key')

        # Возвращаем кастомный флаг в кортеже Auth, чтобы отличать модератора
        # Вместо None передаем словарь или объект, указывающий на сервис
        return (None, {'is_moderator_service': True})

    def authenticate_header(self, request):
        """
        Возвращает заголовок WWW-Authenticate для 401 responses.
        Если этот метод возвращает непустую строку, DRF вернёт 401 вместо 403.
        """
        return 'X-Service-Key'

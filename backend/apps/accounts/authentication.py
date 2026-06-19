from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ExpiringTokenAuthentication(TokenAuthentication):
    """TokenAuthentication that deletes and rejects tokens older than AUTH_TOKEN_EXPIRY_HOURS."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)

        expiry_hours = getattr(settings, 'AUTH_TOKEN_EXPIRY_HOURS', 24)
        if timezone.now() > token.created + timedelta(hours=expiry_hours):
            token.delete()
            raise AuthenticationFailed('Token has expired. Please log in again.')

        return user, token

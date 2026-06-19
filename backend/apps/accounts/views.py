from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics, permissions, serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

User = get_user_model()


class LoginRateThrottle(AnonRateThrottle):
    scope = 'login'


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def validate_password(self, value):
        # Pass an unsaved User so UserAttributeSimilarityValidator can compare
        # the password against the submitted username and email.
        user = User(
            username=self.initial_data.get('username', ''),
            email=self.initial_data.get('email', ''),
        )
        try:
            django_validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key}, status=status.HTTP_201_CREATED)


class LoginView(ObtainAuthToken):
    """
    Wraps DRF's ObtainAuthToken with:
    - Per-IP+username lockout after AUTH_MAX_LOGIN_ATTEMPTS failures.
    - LoginRateThrottle (DRF cache-based rate limit on the endpoint itself).
    """
    throttle_classes = [LoginRateThrottle]

    def post(self, request, *args, **kwargs):
        username = request.data.get('username', '')
        ip = self._get_client_ip(request)
        cache_key = f'auth:fail:{ip}:{username}'
        max_attempts = getattr(settings, 'AUTH_MAX_LOGIN_ATTEMPTS', 5)
        lockout_duration = getattr(settings, 'AUTH_LOCKOUT_DURATION', 900)

        # Pre-check: already locked out?
        if cache.get(cache_key, 0) >= max_attempts:
            return Response(
                {'detail': 'Account temporarily locked. Try again later.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            new_count = cache.get(cache_key, 0) + 1
            cache.set(cache_key, new_count, timeout=lockout_duration)
            if new_count >= max_attempts:
                return Response(
                    {'detail': 'Account locked after too many failed attempts. Try again later.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Successful auth — clear the failure counter
        cache.delete(cache_key)
        user = serializer.validated_data['user']
        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key})

    @staticmethod
    def _get_client_ip(request):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            request.user.auth_token.delete()
        except Token.DoesNotExist:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)

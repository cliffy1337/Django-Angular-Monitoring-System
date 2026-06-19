from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

User = get_user_model()

REGISTER_URL = '/api/auth/register/'
LOGIN_URL = '/api/auth/login/'
TOKEN_URL = '/api/auth/token/'
LOGOUT_URL = '/api/auth/logout/'
ENDPOINTS_URL = '/api/v1/endpoints/'

STRONG_PASSWORD = 'V1g!lStr0ng#2024'
WEAK_PASSWORDS = [
    ('12345678', 'entirely numeric'),
    ('abc', 'too short'),
    ('password123', 'too common'),
]


class RegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_valid_registration_returns_token_and_201(self):
        response = self.client.post(REGISTER_URL, {
            'username': 'newuser',
            'email': 'new@example.com',
            'password': STRONG_PASSWORD,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_registration_creates_valid_drf_token(self):
        self.client.post(REGISTER_URL, {
            'username': 'newuser',
            'email': 'new@example.com',
            'password': STRONG_PASSWORD,
        })
        user = User.objects.get(username='newuser')
        self.assertTrue(Token.objects.filter(user=user).exists())

    def test_short_password_rejected(self):
        response = self.client.post(REGISTER_URL, {
            'username': 'newuser',
            'password': 'ab1',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_numeric_only_password_rejected(self):
        response = self.client.post(REGISTER_URL, {
            'username': 'newuser',
            'password': '12345678',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_common_password_rejected(self):
        response = self.client.post(REGISTER_URL, {
            'username': 'newuser',
            'password': 'password123',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_password_similar_to_username_rejected(self):
        response = self.client.post(REGISTER_URL, {
            'username': 'testuser99',
            'email': 'test@example.com',
            'password': 'testuser99',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_duplicate_username_rejected(self):
        User.objects.create_user(username='taken', password=STRONG_PASSWORD)
        response = self.client.post(REGISTER_URL, {
            'username': 'taken',
            'password': STRONG_PASSWORD,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_validation_error_messages_returned(self):
        response = self.client.post(REGISTER_URL, {
            'username': 'newuser',
            'password': '123',
        })
        # Messages from multiple validators should be present
        self.assertIsInstance(response.data.get('password'), list)
        self.assertGreater(len(response.data['password']), 0)


class LoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser', password=STRONG_PASSWORD, email='test@example.com'
        )
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _login(self, password=None, url=LOGIN_URL):
        return self.client.post(url, {
            'username': 'testuser',
            'password': password or STRONG_PASSWORD,
        })

    def test_valid_login_returns_token(self):
        response = self._login()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)

    def test_token_endpoint_also_protected(self):
        """The /api/auth/token/ alias also goes through LoginView."""
        response = self._login(url=TOKEN_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)

    def test_wrong_password_returns_400(self):
        response = self._login(password='wrongpassword')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nonexistent_username_returns_400(self):
        response = self.client.post(LOGIN_URL, {
            'username': 'ghost',
            'password': STRONG_PASSWORD,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lockout_after_max_attempts(self):
        """After AUTH_MAX_LOGIN_ATTEMPTS failures the IP+user is locked out."""
        max_attempts = 5
        for _ in range(max_attempts):
            self._login(password='wrong')

        # Next attempt (even with correct password) should be locked
        response = self._login()
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_lockout_response_contains_detail_message(self):
        for _ in range(5):
            self._login(password='wrong')
        response = self._login(password='wrong')
        self.assertIn('detail', response.data)

    def test_failure_counter_cleared_on_success(self):
        """A successful login resets the failure counter."""
        for _ in range(3):
            self._login(password='wrong')

        # Successful login clears the counter
        success = self._login()
        self.assertEqual(success.status_code, status.HTTP_200_OK)

        # Subsequent failed attempts restart from zero (no lockout on attempt 4)
        response = self._login(password='wrong')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(AUTH_MAX_LOGIN_ATTEMPTS=3)
    def test_lockout_threshold_is_configurable(self):
        for _ in range(3):
            self._login(password='wrong')
        response = self._login()
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @override_settings(AUTH_LOCKOUT_DURATION=1)
    def test_lockout_duration_is_configurable(self):
        """AUTH_LOCKOUT_DURATION controls the cache TTL (tested via override)."""
        for _ in range(5):
            self._login(password='wrong')
        locked_response = self._login()
        self.assertEqual(locked_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class LogoutTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser', password=STRONG_PASSWORD, email='test@example.com'
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def test_logout_returns_204(self):
        response = self.client.post(LOGOUT_URL)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_token_deleted_from_database_after_logout(self):
        self.client.post(LOGOUT_URL)
        self.assertFalse(Token.objects.filter(pk=self.token.pk).exists())

    def test_subsequent_authenticated_request_rejected(self):
        """The deleted token must no longer grant access."""
        self.client.post(LOGOUT_URL)
        response = self.client.get(ENDPOINTS_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_logout_rejected(self):
        anon = APIClient()
        response = anon.post(LOGOUT_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_is_idempotent(self):
        """Second logout with the same (now-deleted) token returns 401, not 500."""
        self.client.post(LOGOUT_URL)
        response = self.client.post(LOGOUT_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TokenExpiryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser', password=STRONG_PASSWORD, email='test@example.com'
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def _backdate_token(self, hours):
        past = timezone.now() - timedelta(hours=hours)
        Token.objects.filter(pk=self.token.pk).update(created=past)

    def test_fresh_token_grants_access(self):
        response = self.client.get(ENDPOINTS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_expired_token_returns_401(self):
        self._backdate_token(hours=25)  # default expiry is 24h
        response = self.client.get(ENDPOINTS_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_token_deleted_on_first_use(self):
        """Using an expired token must remove it so it cannot be replayed."""
        self._backdate_token(hours=25)
        self.client.get(ENDPOINTS_URL)
        self.assertFalse(Token.objects.filter(pk=self.token.pk).exists())

    def test_token_within_expiry_window_still_valid(self):
        """A 25-hour-old token is valid when expiry is set to 48h."""
        self._backdate_token(hours=25)
        with override_settings(AUTH_TOKEN_EXPIRY_HOURS=48):
            response = self.client.get(ENDPOINTS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_token_at_exact_expiry_boundary_rejected(self):
        """Token exactly at the boundary (≥ expiry hours) should be rejected."""
        self._backdate_token(hours=24)
        response = self.client.get(ENDPOINTS_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

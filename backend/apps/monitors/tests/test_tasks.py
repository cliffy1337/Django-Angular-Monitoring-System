from django.test import TestCase
from django.contrib.auth import get_user_model
from unittest.mock import patch, Mock
from apps.monitors.models import Endpoint, CheckResult, Incident
from apps.monitors.tasks import check_endpoint

User = get_user_model()

class TasksTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass', email='test@example.com')
        self.endpoint = Endpoint.objects.create(
            user=self.user,
            name='Test',
            url='https://httpbin.org/status/200',
            interval_minutes=5
        )

    @patch('apps.monitors.tasks.safe_get_request')
    def test_check_endpoint_up(self, mock_request):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        check_endpoint(self.endpoint.id)
        self.assertTrue(CheckResult.objects.filter(endpoint=self.endpoint, is_up=True).exists())
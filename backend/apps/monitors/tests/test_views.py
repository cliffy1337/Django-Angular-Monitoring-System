"""
API endpoint tests for EndpointViewSet and IncidentViewSet custom actions.

Covers:
  - POST /api/v1/endpoints/{id}/check_now/
  - POST /api/v1/incidents/{id}/resend_alert/
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from apps.monitors.models import Endpoint, Incident

User = get_user_model()


class BaseViewTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='viewer', password='pass!word99', email='viewer@example.com'
        )
        self.other = User.objects.create_user(
            username='other', password='pass!word99', email='other@example.com'
        )
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        self.endpoint = Endpoint.objects.create(
            user=self.user, name='My Site', url='https://example.com', interval_minutes=5
        )
        self.other_endpoint = Endpoint.objects.create(
            user=self.other, name='Other Site', url='https://other.example.com', interval_minutes=5
        )
        self.incident = Incident.objects.create(
            endpoint=self.endpoint, started_at=timezone.now(), resolved=False
        )
        self.resolved_incident = Incident.objects.create(
            endpoint=self.endpoint,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            resolved=True,
        )
        self.other_incident = Incident.objects.create(
            endpoint=self.other_endpoint, started_at=timezone.now(), resolved=False
        )


# ---------------------------------------------------------------------------
# check_now
# ---------------------------------------------------------------------------

class CheckNowTests(BaseViewTest):

    def url(self, endpoint_id):
        return f'/api/v1/endpoints/{endpoint_id}/check_now/'

    @patch('apps.monitors.tasks.check_endpoint.delay')
    def test_returns_202(self, mock_delay):
        resp = self.client.post(self.url(self.endpoint.id))
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

    @patch('apps.monitors.tasks.check_endpoint.delay')
    def test_queues_celery_task_with_endpoint_id(self, mock_delay):
        self.client.post(self.url(self.endpoint.id))
        mock_delay.assert_called_once_with(self.endpoint.id)

    @patch('apps.monitors.tasks.check_endpoint.delay')
    def test_response_body(self, mock_delay):
        resp = self.client.post(self.url(self.endpoint.id))
        self.assertEqual(resp.json(), {'status': 'check queued'})

    def test_another_users_endpoint_returns_404(self):
        resp = self.client.post(self.url(self.other_endpoint.id))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_returns_401(self):
        self.client.credentials()
        resp = self.client.post(self.url(self.endpoint.id))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_nonexistent_endpoint_returns_404(self):
        resp = self.client.post('/api/v1/endpoints/00000000-0000-0000-0000-000000000000/check_now/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# resend_alert
# ---------------------------------------------------------------------------

class ResendAlertTests(BaseViewTest):

    def url(self, incident_id):
        return f'/api/v1/incidents/{incident_id}/resend_alert/'

    @patch('apps.monitors.tasks.send_alert_email.delay')
    def test_returns_202(self, mock_delay):
        resp = self.client.post(self.url(self.incident.id))
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

    @patch('apps.monitors.tasks.send_alert_email.delay')
    def test_response_body(self, mock_delay):
        resp = self.client.post(self.url(self.incident.id))
        self.assertEqual(resp.json(), {'status': 'alert queued'})

    @patch('apps.monitors.tasks.send_alert_email.delay')
    def test_unresolved_incident_sends_down_alert(self, mock_delay):
        self.client.post(self.url(self.incident.id))
        mock_delay.assert_called_once_with(
            self.incident.endpoint_id,
            self.incident.id,
            is_resolved=False,
        )

    @patch('apps.monitors.tasks.send_alert_email.delay')
    def test_resolved_incident_sends_resolution_alert(self, mock_delay):
        self.client.post(self.url(self.resolved_incident.id))
        mock_delay.assert_called_once_with(
            self.resolved_incident.endpoint_id,
            self.resolved_incident.id,
            is_resolved=True,
        )

    @patch('apps.monitors.tasks.send_alert_email.delay')
    def test_task_called_exactly_once_per_request(self, mock_delay):
        self.client.post(self.url(self.incident.id))
        self.assertEqual(mock_delay.call_count, 1)

    def test_another_users_incident_returns_404(self):
        resp = self.client.post(self.url(self.other_incident.id))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_returns_401(self):
        self.client.credentials()
        resp = self.client.post(self.url(self.incident.id))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_nonexistent_incident_returns_404(self):
        resp = self.client.post('/api/v1/incidents/00000000-0000-0000-0000-000000000000/resend_alert/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_method_not_allowed(self):
        resp = self.client.get(self.url(self.incident.id))
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

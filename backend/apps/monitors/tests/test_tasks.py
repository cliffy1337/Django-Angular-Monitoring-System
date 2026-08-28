from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.monitors.models import CheckResult, Endpoint, Incident
from apps.monitors.tasks import check_endpoint, schedule_checks

User = get_user_model()


def _up_response(status_code=200):
    response = Mock()
    response.status_code = status_code
    return response


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
        mock_request.return_value = _up_response(200)

        check_endpoint(self.endpoint.id)
        self.assertTrue(CheckResult.objects.filter(endpoint=self.endpoint, is_up=True).exists())

    @patch('apps.monitors.tasks.send_alert_email.delay')
    @patch('apps.monitors.tasks.safe_get_request')
    def test_first_ever_check_does_not_create_an_incident(self, mock_request, mock_send):
        """A DOWN result with no prior check is not a status *change*."""
        mock_request.side_effect = requests.exceptions.ConnectionError('refused')

        with self.captureOnCommitCallbacks(execute=True):
            check_endpoint(self.endpoint.id)

        self.assertFalse(Incident.objects.filter(endpoint=self.endpoint).exists())
        mock_send.assert_not_called()

    @patch('apps.monitors.tasks.send_alert_email.delay')
    @patch('apps.monitors.tasks.safe_get_request')
    def test_down_transition_creates_incident_and_queues_alert(self, mock_request, mock_send):
        CheckResult.objects.create(endpoint=self.endpoint, is_up=True, status_code=200,
                                    response_time_ms=10,
                                    checked_at=timezone.now() - timezone.timedelta(minutes=10))
        mock_request.side_effect = requests.exceptions.ConnectionError('refused')

        with self.captureOnCommitCallbacks(execute=True):
            check_endpoint(self.endpoint.id)

        incident = Incident.objects.get(endpoint=self.endpoint)
        self.assertFalse(incident.resolved)
        self.assertIsNone(incident.ended_at)
        mock_send.assert_called_once_with(self.endpoint.id, incident.id, is_resolved=False)

    @patch('apps.monitors.tasks.send_alert_email.delay')
    @patch('apps.monitors.tasks.safe_get_request')
    def test_up_transition_closes_incident_and_queues_resolution_alert(self, mock_request, mock_send):
        CheckResult.objects.create(endpoint=self.endpoint, is_up=False, status_code=None,
                                    response_time_ms=0,
                                    checked_at=timezone.now() - timezone.timedelta(minutes=10))
        incident = Incident.objects.create(
            endpoint=self.endpoint,
            started_at=timezone.now() - timezone.timedelta(minutes=10),
            resolved=False,
        )
        mock_request.return_value = _up_response(200)

        with self.captureOnCommitCallbacks(execute=True):
            check_endpoint(self.endpoint.id)

        incident.refresh_from_db()
        self.assertTrue(incident.resolved)
        self.assertIsNotNone(incident.ended_at)
        mock_send.assert_called_once_with(self.endpoint.id, incident.id, is_resolved=True)

    @patch('apps.monitors.tasks.send_alert_email.delay')
    @patch('apps.monitors.tasks.safe_get_request')
    def test_repeated_down_checks_do_not_create_duplicate_incidents(self, mock_request, mock_send):
        CheckResult.objects.create(endpoint=self.endpoint, is_up=False, status_code=None,
                                    response_time_ms=0,
                                    checked_at=timezone.now() - timezone.timedelta(minutes=10))
        Incident.objects.create(
            endpoint=self.endpoint,
            started_at=timezone.now() - timezone.timedelta(minutes=10),
            resolved=False,
        )
        mock_request.side_effect = requests.exceptions.ConnectionError('refused')

        with self.captureOnCommitCallbacks(execute=True):
            check_endpoint(self.endpoint.id)

        self.assertEqual(Incident.objects.filter(endpoint=self.endpoint).count(), 1)
        mock_send.assert_not_called()

    @patch('apps.monitors.tasks.safe_get_request')
    def test_idempotency_guard_skips_recheck_within_interval(self, mock_request):
        CheckResult.objects.create(endpoint=self.endpoint, is_up=True, status_code=200,
                                    response_time_ms=10, checked_at=timezone.now())

        check_endpoint(self.endpoint.id)

        mock_request.assert_not_called()
        self.assertEqual(CheckResult.objects.filter(endpoint=self.endpoint).count(), 1)

    @patch('apps.monitors.tasks.safe_get_request')
    def test_recheck_allowed_once_interval_has_elapsed(self, mock_request):
        CheckResult.objects.create(
            endpoint=self.endpoint, is_up=True, status_code=200, response_time_ms=10,
            checked_at=timezone.now() - timezone.timedelta(minutes=self.endpoint.interval_minutes + 1),
        )
        mock_request.return_value = _up_response(200)

        check_endpoint(self.endpoint.id)

        self.assertEqual(CheckResult.objects.filter(endpoint=self.endpoint).count(), 2)

    @patch('apps.monitors.tasks.safe_get_request')
    def test_inactive_endpoint_is_not_checked(self, mock_request):
        self.endpoint.is_active = False
        self.endpoint.save(update_fields=['is_active'])

        check_endpoint(self.endpoint.id)

        mock_request.assert_not_called()
        self.assertFalse(CheckResult.objects.filter(endpoint=self.endpoint).exists())

    @patch('apps.monitors.tasks.safe_get_request')
    def test_nonexistent_endpoint_is_a_no_op(self, mock_request):
        check_endpoint('00000000-0000-0000-0000-000000000000')
        mock_request.assert_not_called()

    @patch('apps.monitors.tasks.check_endpoint.delay')
    def test_schedule_checks_only_queues_active_endpoints(self, mock_delay):
        inactive = Endpoint.objects.create(
            user=self.user, name='Inactive', url='https://example.com',
            interval_minutes=5, is_active=False,
        )

        schedule_checks()

        queued_ids = {call.args[0] for call in mock_delay.call_args_list}
        self.assertIn(self.endpoint.id, queued_ids)
        self.assertNotIn(inactive.id, queued_ids)

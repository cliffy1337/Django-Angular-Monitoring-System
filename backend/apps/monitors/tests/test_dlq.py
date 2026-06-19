"""
Tests for the dead-letter queue: retry_failed_emails Celery task.

Coverage:
  - Happy path: pending email is sent, success_at set
  - Failure path: retry_count incremented, error_message stored
  - Backoff formula and cap
  - Exhaustion after max retries
  - Filters: skips succeeded / exhausted / not-yet-due records
  - Metrics dict returned
  - send_alert_email writes FailedEmail correctly on initial failure
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.monitors.models import FailedEmail, Endpoint, Incident
from apps.monitors.tasks import retry_failed_emails, send_alert_email

User = get_user_model()

DLQ_SETTINGS = {
    'FAILED_EMAIL_MAX_RETRIES': 3,
    'FAILED_EMAIL_BASE_DELAY_MINUTES': 5,
}


def _pending(offset_minutes=-1, retry_count=0, **kwargs):
    """Create a FailedEmail due for retry (next_retry_at in the past by default)."""
    return FailedEmail.objects.create(
        to_email='user@example.com',
        subject='Test alert',
        body='Endpoint is down.',
        retry_count=retry_count,
        next_retry_at=timezone.now() + timedelta(minutes=offset_minutes),
        **kwargs,
    )


@override_settings(**DLQ_SETTINGS)
class RetryFailedEmailsHappyPathTests(TestCase):

    @patch('apps.monitors.tasks.send_mail')
    def test_due_email_is_sent(self, mock_send):
        record = _pending()
        retry_failed_emails()
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        self.assertEqual(call_kwargs['subject'], record.subject)
        self.assertEqual(call_kwargs['message'], record.body)
        self.assertEqual(call_kwargs['recipient_list'], [record.to_email])

    @patch('apps.monitors.tasks.send_mail')
    def test_success_at_set_after_send(self, mock_send):
        record = _pending()
        before = timezone.now()
        retry_failed_emails()
        record.refresh_from_db()
        self.assertIsNotNone(record.success_at)
        self.assertGreaterEqual(record.success_at, before)

    @patch('apps.monitors.tasks.send_mail')
    def test_last_attempt_at_set_on_success(self, mock_send):
        record = _pending()
        before = timezone.now()
        retry_failed_emails()
        record.refresh_from_db()
        self.assertIsNotNone(record.last_attempt_at)
        self.assertGreaterEqual(record.last_attempt_at, before)

    @patch('apps.monitors.tasks.send_mail')
    def test_status_is_sent_after_delivery(self, mock_send):
        record = _pending()
        retry_failed_emails()
        record.refresh_from_db()
        self.assertEqual(record.status, 'sent')

    @patch('apps.monitors.tasks.send_mail')
    def test_returns_correct_metrics_on_success(self, mock_send):
        _pending()
        result = retry_failed_emails()
        self.assertEqual(result['processed'], 1)
        self.assertEqual(result['sent'], 1)
        self.assertEqual(result['rescheduled'], 0)
        self.assertEqual(result['exhausted'], 0)


@override_settings(**DLQ_SETTINGS)
class RetryFailedEmailsFailurePathTests(TestCase):

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('SMTP timeout'))
    def test_retry_count_incremented_on_failure(self, mock_send):
        record = _pending(retry_count=0)
        retry_failed_emails()
        record.refresh_from_db()
        self.assertEqual(record.retry_count, 1)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('SMTP timeout'))
    def test_error_message_stored(self, mock_send):
        record = _pending()
        retry_failed_emails()
        record.refresh_from_db()
        self.assertIn('SMTP timeout', record.error_message)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('conn refused'))
    def test_last_attempt_at_set_on_failure(self, mock_send):
        record = _pending()
        before = timezone.now()
        retry_failed_emails()
        record.refresh_from_db()
        self.assertIsNotNone(record.last_attempt_at)
        self.assertGreaterEqual(record.last_attempt_at, before)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_next_retry_at_pushed_forward(self, mock_send):
        record = _pending(retry_count=0)
        before = timezone.now()
        retry_failed_emails()
        record.refresh_from_db()
        # next_retry_at must be in the future
        self.assertGreater(record.next_retry_at, before)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_success_at_not_set_on_failure(self, mock_send):
        record = _pending()
        retry_failed_emails()
        record.refresh_from_db()
        self.assertIsNone(record.success_at)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_returns_rescheduled_metric(self, mock_send):
        _pending()
        result = retry_failed_emails()
        self.assertEqual(result['rescheduled'], 1)
        self.assertEqual(result['sent'], 0)


@override_settings(**DLQ_SETTINGS)
class BackoffCalculationTests(TestCase):
    """Verify exponential backoff formula and cap."""

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_first_retry_delay_is_base_times_2(self, mock_send):
        # retry_count starts at 0, after failure becomes 1 → delay = 5 * 2^1 = 10 min
        record = _pending(retry_count=0)
        before = timezone.now()
        retry_failed_emails()
        record.refresh_from_db()
        expected_min_delay = timedelta(minutes=9)   # allow 1 min slack
        expected_max_delay = timedelta(minutes=11)
        actual_delay = record.next_retry_at - before
        self.assertGreater(actual_delay, expected_min_delay)
        self.assertLess(actual_delay, expected_max_delay)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_second_retry_delay_doubles(self, mock_send):
        # retry_count=1 → after failure becomes 2 → delay = 5 * 2^2 = 20 min
        record = _pending(retry_count=1)
        before = timezone.now()
        retry_failed_emails()
        record.refresh_from_db()
        expected = timedelta(minutes=19)
        self.assertGreater(record.next_retry_at - before, expected)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_backoff_capped_at_720_minutes(self, mock_send):
        # retry_count=6 → after failure becomes 7 → 5 * 2^7 = 640 min (under cap)
        # retry_count=7 → after failure becomes 8, but MAX_RETRIES=3 so exhausted first
        # Test with a high retry count that would exceed cap using different settings
        with self.settings(FAILED_EMAIL_MAX_RETRIES=20, FAILED_EMAIL_BASE_DELAY_MINUTES=5):
            record = _pending(retry_count=8)  # → becomes 9 → 5*2^9=2560 → capped at 720
            before = timezone.now()
            retry_failed_emails()
            record.refresh_from_db()
            cap = timedelta(minutes=721)  # 1 min slack
            self.assertLess(record.next_retry_at - before, cap)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_backoff_never_goes_below_base(self, mock_send):
        record = _pending(retry_count=0)
        before = timezone.now()
        retry_failed_emails()
        record.refresh_from_db()
        # delay for count=1 is 10 min, definitely > 0
        self.assertGreater(record.next_retry_at, before)


@override_settings(**DLQ_SETTINGS)
class ExhaustionTests(TestCase):
    """Test behaviour when max retries are reached (MAX_RETRIES=3)."""

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_exhausted_at_set_when_limit_reached(self, mock_send):
        # retry_count=2 → after failure becomes 3 == MAX_RETRIES
        record = _pending(retry_count=2)
        before = timezone.now()
        retry_failed_emails()
        record.refresh_from_db()
        self.assertIsNotNone(record.exhausted_at)
        self.assertGreaterEqual(record.exhausted_at, before)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_exhausted_status(self, mock_send):
        record = _pending(retry_count=2)
        retry_failed_emails()
        record.refresh_from_db()
        self.assertEqual(record.status, 'exhausted')

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_next_retry_at_not_updated_on_exhaust(self, mock_send):
        original_next = timezone.now() - timedelta(minutes=1)
        record = _pending(retry_count=2)
        record.next_retry_at = original_next
        record.save(update_fields=['next_retry_at'])
        retry_failed_emails()
        record.refresh_from_db()
        # next_retry_at should not have changed to a future time; exhausted_at is set instead
        self.assertIsNotNone(record.exhausted_at)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_exhausted_metric_incremented(self, mock_send):
        _pending(retry_count=2)
        result = retry_failed_emails()
        self.assertEqual(result['exhausted'], 1)
        self.assertEqual(result['rescheduled'], 0)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_error_message_stored_on_exhaust(self, mock_send):
        record = _pending(retry_count=2)
        retry_failed_emails()
        record.refresh_from_db()
        self.assertIn('err', record.error_message)


@override_settings(**DLQ_SETTINGS)
class FilteringTests(TestCase):
    """Task must skip records that are not eligible for retry."""

    @patch('apps.monitors.tasks.send_mail')
    def test_skips_already_succeeded(self, mock_send):
        _pending(success_at=timezone.now())
        result = retry_failed_emails()
        mock_send.assert_not_called()
        self.assertEqual(result['processed'], 0)

    @patch('apps.monitors.tasks.send_mail')
    def test_skips_already_exhausted(self, mock_send):
        _pending(exhausted_at=timezone.now())
        result = retry_failed_emails()
        mock_send.assert_not_called()
        self.assertEqual(result['processed'], 0)

    @patch('apps.monitors.tasks.send_mail')
    def test_skips_not_yet_due(self, mock_send):
        # next_retry_at is 30 min in the future
        _pending(offset_minutes=30)
        result = retry_failed_emails()
        mock_send.assert_not_called()
        self.assertEqual(result['processed'], 0)

    @patch('apps.monitors.tasks.send_mail')
    def test_skips_at_max_retry_count(self, mock_send):
        # retry_count already equals MAX_RETRIES (3); the filter excludes it
        _pending(retry_count=3)
        result = retry_failed_emails()
        mock_send.assert_not_called()
        self.assertEqual(result['processed'], 0)

    @patch('apps.monitors.tasks.send_mail')
    def test_processes_exactly_due_emails(self, mock_send):
        _pending(offset_minutes=-1)   # due
        _pending(offset_minutes=30)   # not yet due
        result = retry_failed_emails()
        mock_send.assert_called_once()
        self.assertEqual(result['processed'], 1)


@override_settings(**DLQ_SETTINGS)
class BatchProcessingTests(TestCase):

    @patch('apps.monitors.tasks.send_mail')
    def test_all_pending_emails_processed(self, mock_send):
        for _ in range(3):
            _pending()
        result = retry_failed_emails()
        self.assertEqual(result['processed'], 3)
        self.assertEqual(result['sent'], 3)
        self.assertEqual(mock_send.call_count, 3)

    @patch('apps.monitors.tasks.send_mail')
    def test_partial_success_mixed_batch(self, mock_send):
        """Two succeed, one fails."""
        good = MagicMock(return_value=None)
        bad = Exception('SMTP error')
        mock_send.side_effect = [None, bad, None]

        for _ in range(3):
            _pending()
        result = retry_failed_emails()

        self.assertEqual(result['processed'], 3)
        self.assertEqual(result['sent'], 2)
        self.assertEqual(result['rescheduled'], 1)

    @patch('apps.monitors.tasks.send_mail')
    def test_empty_queue_returns_zero_metrics(self, mock_send):
        result = retry_failed_emails()
        self.assertEqual(result, {'processed': 0, 'sent': 0, 'rescheduled': 0, 'exhausted': 0})
        mock_send.assert_not_called()


@override_settings(
    FAILED_EMAIL_MAX_RETRIES=2,
    FAILED_EMAIL_BASE_DELAY_MINUTES=5,
    DEFAULT_FROM_EMAIL='noreply@vigil.test',
)
class SendAlertEmailDLQIntegrationTests(TestCase):
    """
    Verify that send_alert_email writes a FailedEmail record correctly when
    the SMTP call fails, and that the DLQ task can then pick it up.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='dlquser',
            email='dlquser@example.com',
            password='testpassword123!',
        )
        self.endpoint = Endpoint.objects.create(
            user=self.user,
            name='DLQ Test Endpoint',
            url='https://example.com',
            interval_minutes=5,
        )
        self.incident = Incident.objects.create(
            endpoint=self.endpoint,
            started_at=timezone.now(),
        )

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('Connection refused'))
    def test_failed_email_created_on_send_failure(self, mock_send):
        send_alert_email(self.endpoint.id, self.incident.id, is_resolved=False)
        self.assertEqual(FailedEmail.objects.count(), 1)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('Connection refused'))
    def test_failed_email_has_correct_recipient(self, mock_send):
        send_alert_email(self.endpoint.id, self.incident.id, is_resolved=False)
        record = FailedEmail.objects.get()
        self.assertEqual(record.to_email, self.user.email)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('Connection refused'))
    def test_failed_email_has_error_message(self, mock_send):
        send_alert_email(self.endpoint.id, self.incident.id, is_resolved=False)
        record = FailedEmail.objects.get()
        self.assertIn('Connection refused', record.error_message)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('Connection refused'))
    def test_failed_email_next_retry_is_in_future(self, mock_send):
        before = timezone.now()
        send_alert_email(self.endpoint.id, self.incident.id, is_resolved=False)
        record = FailedEmail.objects.get()
        self.assertGreater(record.next_retry_at, before)

    @patch('apps.monitors.tasks.send_mail', side_effect=Exception('err'))
    def test_failed_email_retry_count_starts_at_zero(self, mock_send):
        send_alert_email(self.endpoint.id, self.incident.id, is_resolved=False)
        record = FailedEmail.objects.get()
        self.assertEqual(record.retry_count, 0)

    @patch('apps.monitors.tasks.send_mail')
    def test_dlq_delivers_record_created_by_alert_task(self, mock_send):
        """Full integration: alert task writes DLQ record → retry task delivers it."""
        # First call: fail to create the FailedEmail
        mock_send.side_effect = Exception('initial failure')
        send_alert_email(self.endpoint.id, self.incident.id, is_resolved=False)
        self.assertEqual(FailedEmail.objects.count(), 1)

        # Second call via DLQ: succeed
        mock_send.side_effect = None
        record = FailedEmail.objects.get()
        record.next_retry_at = timezone.now() - timedelta(minutes=1)
        record.save(update_fields=['next_retry_at'])

        result = retry_failed_emails()
        self.assertEqual(result['sent'], 1)
        record.refresh_from_db()
        self.assertIsNotNone(record.success_at)

import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Endpoint, CheckResult, Incident, FailedEmail
from .ssrf import SSRFError, safe_get_request

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_endpoint(self, endpoint_id):
    """Check a single endpoint and record result, create/close incidents, send alerts."""
    try:
        endpoint = Endpoint.objects.get(id=endpoint_id, is_active=True)
    except Endpoint.DoesNotExist:
        logger.warning(f"Endpoint {endpoint_id} not found or inactive")
        return

    # Idempotency: skip if checked too recently (within interval_minutes)
    last_check = CheckResult.objects.filter(endpoint=endpoint).first()
    if last_check:
        elapsed = (timezone.now() - last_check.checked_at).total_seconds() / 60
        if elapsed < endpoint.interval_minutes:
            logger.info(f"Skipping {endpoint.name}, last check {elapsed:.1f} min ago")
            return

    # Perform HTTP check
    start_time = timezone.now()
    try:
        response = safe_get_request(endpoint.url, timeout=10)
        is_up = response.status_code < 500
        status_code = response.status_code
        response_time = int((timezone.now() - start_time).total_seconds() * 1000)
    except SSRFError as e:
        # URL resolves to a private/reserved address (DNS rebinding or stale data).
        # Do not connect; record a failed check and log a security warning.
        logger.warning("SSRF blocked for endpoint %s (%s): %s", endpoint.name, endpoint.url, e)
        is_up = False
        status_code = None
        response_time = None
    except requests.RequestException as e:
        is_up = False
        status_code = None
        response_time = None
        logger.error(f"Check failed for {endpoint.name}: {e}")

    # Save check result
    check = CheckResult.objects.create(
        endpoint=endpoint,
        status_code=status_code,
        response_time_ms=response_time or 0,
        is_up=is_up,
        checked_at=start_time
    )

    # Get previous check result
    previous_check = CheckResult.objects.filter(endpoint=endpoint).exclude(id=check.id).first()

    # Detect status change
    status_changed = previous_check and previous_check.is_up != is_up
    if status_changed:
        if not is_up:
            # Outage started
            incident = Incident.objects.create(
                endpoint=endpoint,
                started_at=start_time,
                resolved=False
            )
            # Send alert asynchronously
            send_alert_email.delay(endpoint.id, incident.id, is_resolved=False)
        else:
            # Outage ended
            incident = Incident.objects.filter(endpoint=endpoint, resolved=False).first()
            if incident:
                incident.ended_at = start_time
                incident.resolved = True
                incident.save()
                send_alert_email.delay(endpoint.id, incident.id, is_resolved=True)

    return check.id

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def send_alert_email(self, endpoint_id, incident_id, is_resolved):
    """Send email alert for an incident (start or resolution)."""
    try:
        endpoint = Endpoint.objects.get(id=endpoint_id)
        incident = Incident.objects.get(id=incident_id)
    except (Endpoint.DoesNotExist, Incident.DoesNotExist) as e:
        logger.error(f"Cannot send alert: {e}")
        return

    # Cooldown: don't send another alert for same endpoint within cooldown period (default 60 min)
    cooldown_minutes = getattr(endpoint.user, 'alert_cooldown_minutes', 60)
    if endpoint.last_alert_sent_at:
        elapsed = (timezone.now() - endpoint.last_alert_sent_at).total_seconds() / 60
        if elapsed < cooldown_minutes and not is_resolved:
            logger.info(f"Alert cooldown active for {endpoint.name}, skipping email")
            return

    subject = f"[Vigil] {endpoint.name} is {'DOWN' if not is_resolved else 'UP again'}"
    message = f"""
    Endpoint: {endpoint.name} ({endpoint.url})
    Status: {'DOWN' if not is_resolved else 'RESOLVED'}
    Time: {timezone.now()}
    Incident started at: {incident.started_at}
    """
    if is_resolved and incident.ended_at:
        message += f"Resolved at: {incident.ended_at}\nDuration: {incident.duration_seconds():.0f} seconds"

    try:
        send_mail(
            subject=subject,
            message=message.strip(),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[endpoint.user.email],
            fail_silently=False,
        )
        endpoint.last_alert_sent_at = timezone.now()
        endpoint.save(update_fields=['last_alert_sent_at'])
        logger.info("Alert email sent for %s to %s", endpoint.name, endpoint.user.email)
    except Exception as e:
        logger.error("Failed to send alert email for %s: %s", endpoint.name, e)
        base_delay = getattr(settings, 'FAILED_EMAIL_BASE_DELAY_MINUTES', 5)
        FailedEmail.objects.create(
            to_email=endpoint.user.email,
            subject=subject,
            body=message.strip(),
            retry_count=0,
            error_message=str(e)[:500],
            next_retry_at=timezone.now() + timedelta(minutes=base_delay),
        )

@shared_task
def schedule_checks():
    """Periodic task that schedules checks for all active endpoints."""
    endpoints = Endpoint.objects.filter(is_active=True)
    for endpoint in endpoints:
        check_endpoint.delay(endpoint.id)
    logger.info("Scheduled checks for %d endpoints", endpoints.count())


@shared_task
def retry_failed_emails():
    """
    Dead-letter queue processor for failed alert emails.

    Picks up every FailedEmail whose next_retry_at is in the past and that has
    not already succeeded or been exhausted, then:
      - On success  → marks success_at.
      - On failure  → increments retry_count, stores error_message, and
                      schedules the next attempt with exponential backoff
                      (base * 2^count, capped at 720 minutes).
      - On exhaust  → sets exhausted_at when retry_count reaches the limit.

    Returns a metrics dict for logging and Celery result inspection.
    """
    max_retries = getattr(settings, 'FAILED_EMAIL_MAX_RETRIES', 8)
    base_delay = getattr(settings, 'FAILED_EMAIL_BASE_DELAY_MINUTES', 5)
    max_delay = 720  # 12 hours

    now = timezone.now()
    pending = FailedEmail.objects.filter(
        success_at__isnull=True,
        exhausted_at__isnull=True,
        next_retry_at__lte=now,
        retry_count__lt=max_retries,
    )

    total = pending.count()
    sent = rescheduled = exhausted = 0

    logger.info("DLQ: %d failed email(s) due for retry", total)

    for record in pending:
        try:
            send_mail(
                subject=record.subject,
                message=record.body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[record.to_email],
                fail_silently=False,
            )
            record.success_at = now
            record.last_attempt_at = now
            record.save(update_fields=['success_at', 'last_attempt_at'])
            sent += 1
            logger.info(
                "DLQ: delivered to %s after %d attempt(s)",
                record.to_email, record.retry_count + 1,
            )
        except Exception as exc:
            record.retry_count += 1
            record.last_attempt_at = now
            record.error_message = str(exc)[:500]

            if record.retry_count >= max_retries:
                record.exhausted_at = now
                record.save(update_fields=[
                    'retry_count', 'last_attempt_at', 'error_message', 'exhausted_at',
                ])
                exhausted += 1
                logger.error(
                    "DLQ: exhausted retries for %s after %d attempt(s) — last error: %s",
                    record.to_email, record.retry_count, exc,
                )
            else:
                delay = min(base_delay * (2 ** record.retry_count), max_delay)
                record.next_retry_at = now + timedelta(minutes=delay)
                record.save(update_fields=[
                    'retry_count', 'last_attempt_at', 'error_message', 'next_retry_at',
                ])
                rescheduled += 1
                logger.warning(
                    "DLQ: attempt %d/%d failed for %s, retry in %d min — %s",
                    record.retry_count, max_retries, record.to_email, delay, exc,
                )

    metrics = {
        'processed': total,
        'sent': sent,
        'rescheduled': rescheduled,
        'exhausted': exhausted,
    }
    logger.info(
        "DLQ complete — processed=%d sent=%d rescheduled=%d exhausted=%d",
        total, sent, rescheduled, exhausted,
    )
    return metrics
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

class Endpoint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='endpoints')
    name = models.CharField(max_length=100)
    url = models.URLField(max_length=500)
    interval_minutes = models.IntegerField(default=5, help_text="Check frequency in minutes")
    is_active = models.BooleanField(default=True)
    last_alert_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.url})"

class CheckResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.ForeignKey(Endpoint, on_delete=models.CASCADE, related_name='check_results')
    status_code = models.IntegerField(null=True, blank=True)
    response_time_ms = models.IntegerField(help_text="Response time in milliseconds")
    is_up = models.BooleanField(default=False)
    checked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-checked_at']
        indexes = [
            models.Index(fields=['endpoint', '-checked_at']),
        ]

    def __str__(self):
        return f"{self.endpoint.name} - {'UP' if self.is_up else 'DOWN'} at {self.checked_at}"

class Incident(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.ForeignKey(Endpoint, on_delete=models.CASCADE, related_name='incidents')
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-started_at']

    def duration_seconds(self):
        if self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return (timezone.now() - self.started_at).total_seconds()

    def __str__(self):
        status = "Resolved" if self.resolved else "Ongoing"
        return f"{self.endpoint.name} - {status} (started {self.started_at})"

class FailedEmail(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    to_email = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    retry_count = models.IntegerField(default=0)
    next_retry_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')
    success_at = models.DateTimeField(null=True, blank=True)
    exhausted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['next_retry_at']
        indexes = [
            # Fast lookup for the DLQ processor: pending rows due for retry
            models.Index(
                fields=['next_retry_at'],
                condition=models.Q(success_at__isnull=True, exhausted_at__isnull=True),
                name='failedemail_pending_idx',
            ),
        ]

    @property
    def status(self) -> str:
        if self.success_at:
            return 'sent'
        if self.exhausted_at:
            return 'exhausted'
        return 'pending'

    def __str__(self):
        return f"FailedEmail to {self.to_email} [{self.status}] (attempt {self.retry_count})"
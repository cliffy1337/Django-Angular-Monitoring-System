from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import Endpoint, CheckResult, Incident, FailedEmail


@admin.register(Endpoint)
class EndpointAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'url', 'interval_minutes', 'is_active', 'last_alert_sent_at', 'created_at']
    list_filter = ['is_active', 'created_at', 'user']
    search_fields = ['name', 'url']
    raw_id_fields = ['user']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(CheckResult)
class CheckResultAdmin(admin.ModelAdmin):
    list_display = ['endpoint', 'is_up', 'status_code', 'response_time_ms', 'checked_at']
    list_filter = ['is_up', 'checked_at']
    search_fields = ['endpoint__name', 'endpoint__url']
    readonly_fields = ['id', 'checked_at']


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ['endpoint', 'started_at', 'ended_at', 'resolved', 'duration_seconds']
    list_filter = ['resolved', 'started_at']
    search_fields = ['endpoint__name']
    readonly_fields = ['id', 'created_at']


class FailedEmailStatusFilter(admin.SimpleListFilter):
    title = 'status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [
            ('pending', 'Pending'),
            ('sent', 'Sent'),
            ('exhausted', 'Exhausted'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'pending':
            return queryset.filter(success_at__isnull=True, exhausted_at__isnull=True)
        if self.value() == 'sent':
            return queryset.filter(success_at__isnull=False)
        if self.value() == 'exhausted':
            return queryset.filter(exhausted_at__isnull=False)
        return queryset


@admin.register(FailedEmail)
class FailedEmailAdmin(admin.ModelAdmin):
    list_display = [
        'to_email', 'subject', 'status_badge', 'retry_count',
        'next_retry_at', 'last_attempt_at', 'created_at',
    ]
    list_filter = [FailedEmailStatusFilter, 'created_at']
    search_fields = ['to_email', 'subject']
    readonly_fields = [
        'id', 'created_at', 'last_attempt_at', 'success_at',
        'exhausted_at', 'error_message',
    ]
    fieldsets = [
        ('Message', {'fields': ['to_email', 'subject', 'body']}),
        ('Retry state', {'fields': [
            'retry_count', 'next_retry_at', 'last_attempt_at', 'error_message',
        ]}),
        ('Outcome', {'fields': ['success_at', 'exhausted_at']}),
        ('Meta', {'fields': ['id', 'created_at']}),
    ]
    actions = ['action_retry_now', 'action_mark_exhausted']

    @admin.display(description='Status')
    def status_badge(self, obj):
        colours = {'sent': '#28a745', 'exhausted': '#dc3545', 'pending': '#fd7e14'}
        label = obj.status
        colour = colours[label]
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>', colour, label.upper()
        )

    @admin.action(description='Retry selected emails now')
    def action_retry_now(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(
            exhausted_at=None,
            next_retry_at=now,
            error_message='',
        )
        self.message_user(request, f'{updated} email(s) queued for immediate retry.')

    @admin.action(description='Mark selected emails as exhausted (give up)')
    def action_mark_exhausted(self, request, queryset):
        now = timezone.now()
        updated = queryset.filter(success_at__isnull=True, exhausted_at__isnull=True).update(
            exhausted_at=now,
        )
        self.message_user(request, f'{updated} email(s) marked as exhausted.')
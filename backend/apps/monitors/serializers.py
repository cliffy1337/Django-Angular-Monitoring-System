from rest_framework import serializers
from .models import Endpoint, CheckResult, Incident
from .ssrf import validate_url_for_ssrf

class EndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = Endpoint
        fields = ['id', 'name', 'url', 'interval_minutes', 'is_active', 'last_alert_sent_at', 'created_at', 'updated_at']
        read_only_fields = ['id', 'last_alert_sent_at', 'created_at', 'updated_at']

    def validate_url(self, value):
        """Reject URLs that resolve to private, loopback, or reserved addresses."""
        validate_url_for_ssrf(value)
        return value

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

class CheckResultSerializer(serializers.ModelSerializer):
    endpoint_name = serializers.CharField(source='endpoint.name', read_only=True)

    class Meta:
        model = CheckResult
        fields = ['id', 'endpoint', 'endpoint_name', 'status_code', 'response_time_ms', 'is_up', 'checked_at']
        read_only_fields = [
            'id',
            'endpoint',
            'endpoint_name',
            'status_code',
            'response_time_ms',
            'is_up',
            'checked_at',
        ]

class IncidentSerializer(serializers.ModelSerializer):
    endpoint_name = serializers.CharField(source='endpoint.name', read_only=True)
    duration_seconds = serializers.ReadOnlyField()

    class Meta:
        model = Incident
        fields = ['id', 'endpoint', 'endpoint_name', 'started_at', 'ended_at', 'resolved', 'duration_seconds', 'created_at']
        read_only_fields = [
            'id',
            'endpoint',
            'endpoint_name',
            'started_at',
            'ended_at',
            'resolved',
            'duration_seconds',
            'created_at',
        ]
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Endpoint, CheckResult, Incident
from .serializers import EndpointSerializer, CheckResultSerializer, IncidentSerializer
from .permissions import IsOwnerOrReadOnly

class EndpointViewSet(viewsets.ModelViewSet):
    serializer_class = EndpointSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    def get_queryset(self):
        return Endpoint.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'])
    def check_now(self, request, pk=None):
        from .tasks import check_endpoint
        check_endpoint.delay(self.get_object().id)
        return Response({'status': 'check queued'}, status=status.HTTP_202_ACCEPTED)

class CheckResultViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CheckResultSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = CheckResult.objects.filter(endpoint__user=self.request.user)
        endpoint_id = self.request.query_params.get('endpoint')
        if endpoint_id:
            qs = qs.filter(endpoint_id=endpoint_id)
        return qs

class IncidentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = IncidentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Incident.objects.filter(endpoint__user=self.request.user)

    @action(detail=True, methods=['post'])
    def resend_alert(self, request, pk=None):
        """Queue an alert email for this incident.

        Sends a DOWN alert for unresolved incidents and a resolution alert for
        resolved ones.  Subject to the per-endpoint alert cooldown — the task
        logs and skips silently if the cooldown has not elapsed.
        """
        from .tasks import send_alert_email
        incident = self.get_object()
        send_alert_email.delay(
            incident.endpoint_id,
            incident.id,
            is_resolved=incident.resolved,
        )
        return Response({'status': 'alert queued'}, status=status.HTTP_202_ACCEPTED)

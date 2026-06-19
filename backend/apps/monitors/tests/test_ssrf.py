import socket
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.monitors.ssrf import (
    SSRFError,
    _is_blocked_ip,
    resolve_and_check_host,
    safe_get_request,
    validate_url_for_ssrf,
)

User = get_user_model()
ENDPOINTS_URL = "/api/v1/endpoints/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_getaddrinfo_result(ip: str) -> list:
    """Build a minimal getaddrinfo return value for a single address."""
    if ":" in ip:
        # IPv6
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _mock_response(status_code: int, headers: dict | None = None, is_redirect: bool = False):
    """Build a minimal mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.is_redirect = is_redirect
    return resp


# ---------------------------------------------------------------------------
# 1. _is_blocked_ip — unit tests for the IP blocklist
# ---------------------------------------------------------------------------

class IsBlockedIPTests(TestCase):

    # ---- IPv4 loopback ----
    def test_loopback_127_0_0_1(self):
        self.assertTrue(_is_blocked_ip("127.0.0.1"))

    def test_loopback_range_127_x_x_x(self):
        self.assertTrue(_is_blocked_ip("127.100.200.50"))

    # ---- RFC 1918 private ranges ----
    def test_rfc1918_10_block(self):
        self.assertTrue(_is_blocked_ip("10.0.0.1"))

    def test_rfc1918_10_non_trivial(self):
        self.assertTrue(_is_blocked_ip("10.255.255.255"))

    def test_rfc1918_172_16_block(self):
        self.assertTrue(_is_blocked_ip("172.16.0.1"))

    def test_rfc1918_172_31_boundary(self):
        self.assertTrue(_is_blocked_ip("172.31.255.255"))

    def test_rfc1918_192_168_block(self):
        self.assertTrue(_is_blocked_ip("192.168.1.100"))

    # ---- Link-local (AWS/GCP/Azure metadata) ----
    def test_link_local_aws_imds(self):
        self.assertTrue(_is_blocked_ip("169.254.169.254"))

    def test_link_local_ecs_metadata(self):
        self.assertTrue(_is_blocked_ip("169.254.170.2"))

    def test_link_local_full_range(self):
        self.assertTrue(_is_blocked_ip("169.254.0.1"))

    # ---- Other reserved IPv4 ----
    def test_cgnat_100_64(self):
        self.assertTrue(_is_blocked_ip("100.64.0.1"))

    def test_multicast_224(self):
        self.assertTrue(_is_blocked_ip("224.0.0.1"))

    def test_reserved_240(self):
        self.assertTrue(_is_blocked_ip("240.0.0.1"))

    # ---- IPv6 blocked ----
    def test_ipv6_loopback(self):
        self.assertTrue(_is_blocked_ip("::1"))

    def test_ipv6_unique_local_fc(self):
        self.assertTrue(_is_blocked_ip("fc00::1"))

    def test_ipv6_unique_local_fd(self):
        self.assertTrue(_is_blocked_ip("fd00::1"))

    def test_ipv6_link_local(self):
        self.assertTrue(_is_blocked_ip("fe80::1"))

    def test_ipv6_multicast(self):
        self.assertTrue(_is_blocked_ip("ff02::1"))

    def test_ipv4_mapped_ipv6_loopback(self):
        # ::ffff:127.0.0.1 must be blocked (IPv4-mapped range)
        self.assertTrue(_is_blocked_ip("::ffff:127.0.0.1"))

    def test_ipv4_mapped_ipv6_private(self):
        self.assertTrue(_is_blocked_ip("::ffff:10.0.0.1"))

    def test_ipv6_zone_id_stripped_and_blocked(self):
        # Zone IDs indicate link-local scope — must be blocked
        self.assertTrue(_is_blocked_ip("fe80::1%eth0"))

    # ---- Public addresses — must NOT be blocked ----
    def test_public_ipv4_8_8_8_8(self):
        self.assertFalse(_is_blocked_ip("8.8.8.8"))

    def test_public_ipv4_1_1_1_1(self):
        self.assertFalse(_is_blocked_ip("1.1.1.1"))

    def test_public_ipv4_93_184_216_34(self):
        self.assertFalse(_is_blocked_ip("93.184.216.34"))

    def test_public_ipv6_google_dns(self):
        self.assertFalse(_is_blocked_ip("2001:4860:4860::8888"))


# ---------------------------------------------------------------------------
# 2. resolve_and_check_host — validation logic
# ---------------------------------------------------------------------------

class ResolveAndCheckHostTests(TestCase):

    # ---- Blocked hostnames (no DNS needed) ----
    def test_localhost_blocked_before_dns(self):
        with self.assertRaises(SSRFError) as ctx:
            resolve_and_check_host("localhost")
        self.assertIn("reserved hostname", str(ctx.exception))

    def test_metadata_google_internal_blocked(self):
        with self.assertRaises(SSRFError):
            resolve_and_check_host("metadata.google.internal")

    def test_blocked_hostname_case_insensitive(self):
        with self.assertRaises(SSRFError):
            resolve_and_check_host("LOCALHOST")

    # ---- IP literals (no DNS needed) ----
    def test_ip_literal_loopback_blocked(self):
        with self.assertRaises(SSRFError):
            resolve_and_check_host("127.0.0.1")

    def test_ip_literal_private_10_blocked(self):
        with self.assertRaises(SSRFError):
            resolve_and_check_host("10.0.0.1")

    def test_ip_literal_link_local_blocked(self):
        with self.assertRaises(SSRFError):
            resolve_and_check_host("169.254.169.254")

    def test_ip_literal_ipv6_loopback_blocked(self):
        with self.assertRaises(SSRFError):
            resolve_and_check_host("::1")

    def test_public_ip_literal_allowed(self):
        result = resolve_and_check_host("8.8.8.8")
        self.assertEqual(result, "8.8.8.8")

    # ---- DNS-resolved hostnames ----
    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_hostname_resolving_to_private_ip_blocked(self, mock_dns):
        mock_dns.return_value = _make_getaddrinfo_result("10.0.0.1")
        with self.assertRaises(SSRFError) as ctx:
            resolve_and_check_host("evil.example.com")
        self.assertIn("10.0.0.1", str(ctx.exception))

    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_hostname_resolving_to_public_ip_allowed(self, mock_dns):
        mock_dns.return_value = _make_getaddrinfo_result("93.184.216.34")
        result = resolve_and_check_host("example.com")
        self.assertEqual(result, "93.184.216.34")

    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_hostname_with_multiple_ips_any_private_blocks(self, mock_dns):
        """If getaddrinfo returns both public and private IPs, block the request."""
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0)),
        ]
        with self.assertRaises(SSRFError):
            resolve_and_check_host("dual-homed.example.com")

    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_dns_failure_raises_ssrf_error(self, mock_dns):
        mock_dns.side_effect = socket.gaierror("Name or service not known")
        with self.assertRaises(SSRFError) as ctx:
            resolve_and_check_host("nonexistent.invalid")
        self.assertIn("Could not resolve", str(ctx.exception))

    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_hostname_resolving_to_ipv6_private_blocked(self, mock_dns):
        mock_dns.return_value = _make_getaddrinfo_result("fc00::1")
        with self.assertRaises(SSRFError):
            resolve_and_check_host("evil-ipv6.example.com")

    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_hostname_resolving_to_link_local_ipv4_blocked(self, mock_dns):
        mock_dns.return_value = _make_getaddrinfo_result("169.254.169.254")
        with self.assertRaises(SSRFError) as ctx:
            resolve_and_check_host("aws-imds-rebind.example.com")
        self.assertIn("169.254.169.254", str(ctx.exception))


# ---------------------------------------------------------------------------
# 3. validate_url_for_ssrf — Django ValidationError wrapper
# ---------------------------------------------------------------------------

class ValidateURLForSSRFTests(TestCase):

    def test_url_with_loopback_ip_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            validate_url_for_ssrf("http://127.0.0.1/admin")

    def test_url_with_private_ip_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            validate_url_for_ssrf("http://192.168.0.1/")

    def test_url_with_link_local_ip_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            validate_url_for_ssrf("http://169.254.169.254/latest/meta-data/")

    def test_url_with_ipv6_loopback_raises_validation_error(self):
        validate_url_for_ssrf.__module__  # ensure import is correct
        with self.assertRaises(ValidationError):
            validate_url_for_ssrf("http://[::1]/")

    def test_url_with_localhost_hostname_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            validate_url_for_ssrf("http://localhost/")

    def test_url_with_metadata_hostname_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            validate_url_for_ssrf("http://metadata.google.internal/")

    def test_error_message_is_user_readable(self):
        """The error must not expose internal details — it should be actionable."""
        with self.assertRaises(ValidationError) as ctx:
            validate_url_for_ssrf("http://10.0.0.1/")
        message = str(ctx.exception)
        # Should mention "private" or "reserved" — not a raw exception class name
        self.assertTrue(
            "private" in message.lower() or "reserved" in message.lower(),
            f"Expected 'private' or 'reserved' in error message, got: {message}",
        )

    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_valid_public_url_accepted(self, mock_dns):
        mock_dns.return_value = _make_getaddrinfo_result("93.184.216.34")
        validate_url_for_ssrf("https://example.com/health")  # must not raise

    def test_url_without_hostname_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            validate_url_for_ssrf("not-a-url")


# ---------------------------------------------------------------------------
# 4. safe_get_request — redirect revalidation
# ---------------------------------------------------------------------------

class SafeGetRequestTests(TestCase):

    @patch("apps.monitors.ssrf.requests.Session")
    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_successful_request_returned(self, mock_dns, mock_session_cls):
        mock_dns.return_value = _make_getaddrinfo_result("93.184.216.34")
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(200)

        response = safe_get_request("http://example.com/")
        self.assertEqual(response.status_code, 200)

    @patch("apps.monitors.ssrf.requests.Session")
    def test_initial_url_with_private_ip_blocked(self, mock_session_cls):
        """The initial URL is checked before any HTTP request is made."""
        with self.assertRaises(SSRFError):
            safe_get_request("http://192.168.1.1/")
        mock_session_cls.return_value.get.assert_not_called()

    @patch("apps.monitors.ssrf.requests.Session")
    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_redirect_to_private_ip_blocked(self, mock_dns, mock_session_cls):
        """A redirect whose Location resolves to a private IP is blocked."""
        # First DNS call: initial URL resolves publicly.
        # Second DNS call: redirect target resolves to a private IP.
        mock_dns.side_effect = [
            _make_getaddrinfo_result("93.184.216.34"),  # example.com → public
            _make_getaddrinfo_result("10.0.0.1"),        # evil.internal → private
        ]

        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(
            301,
            headers={"Location": "http://evil.internal/secret"},
            is_redirect=True,
        )

        with self.assertRaises(SSRFError) as ctx:
            safe_get_request("http://example.com/")
        self.assertIn("10.0.0.1", str(ctx.exception))

    @patch("apps.monitors.ssrf.requests.Session")
    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_redirect_to_link_local_ip_blocked(self, mock_dns, mock_session_cls):
        """A redirect to an AWS IMDS address is blocked."""
        mock_dns.return_value = _make_getaddrinfo_result("93.184.216.34")

        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(
            302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            is_redirect=True,
        )

        with self.assertRaises(SSRFError):
            safe_get_request("http://example.com/")

    @patch("apps.monitors.ssrf.requests.Session")
    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_redirect_to_localhost_blocked(self, mock_dns, mock_session_cls):
        """A redirect to localhost (blocked hostname) is blocked."""
        mock_dns.return_value = _make_getaddrinfo_result("93.184.216.34")

        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(
            301,
            headers={"Location": "http://localhost/internal"},
            is_redirect=True,
        )

        with self.assertRaises(SSRFError):
            safe_get_request("http://example.com/")

    @patch("apps.monitors.ssrf.requests.Session")
    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_valid_redirect_followed(self, mock_dns, mock_session_cls):
        """A redirect to another public URL is followed normally."""
        mock_dns.return_value = _make_getaddrinfo_result("93.184.216.34")

        session = mock_session_cls.return_value
        redirect_resp = _mock_response(
            301,
            headers={"Location": "https://example.com/new"},
            is_redirect=True,
        )
        final_resp = _mock_response(200)
        session.get.side_effect = [redirect_resp, final_resp]

        response = safe_get_request("http://example.com/old")
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# 5. EndpointSerializer — integration: SSRF validation at save time
# ---------------------------------------------------------------------------

class EndpointSerializerSSRFTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser", password="V1g!lStr0ng#2024", email="t@example.com"
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def _post(self, url_value: str):
        return self.client.post(
            ENDPOINTS_URL,
            {"name": "Test endpoint", "url": url_value, "interval_minutes": 5},
        )

    # ---- All of these must be rejected ----
    def test_rejects_loopback_ip(self):
        response = self._post("http://127.0.0.1/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("url", response.data)

    def test_rejects_rfc1918_10_block(self):
        response = self._post("http://10.0.0.1/status")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_rfc1918_172_block(self):
        response = self._post("http://172.16.0.1/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_rfc1918_192_168_block(self):
        response = self._post("http://192.168.0.1/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_aws_imds_url(self):
        response = self._post("http://169.254.169.254/latest/meta-data/iam/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_localhost_hostname(self):
        response = self._post("http://localhost/api/internal")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_metadata_google_internal(self):
        response = self._post("http://metadata.google.internal/computeMetadata/v1/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_ipv6_loopback(self):
        response = self._post("http://[::1]/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_ipv6_unique_local(self):
        response = self._post("http://[fc00::1]/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_error_field_is_url(self):
        """Validation errors must be reported under the 'url' field."""
        response = self._post("http://127.0.0.1/")
        self.assertIn("url", response.data)

    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_rejects_hostname_resolving_to_private_ip(self, mock_dns):
        mock_dns.return_value = _make_getaddrinfo_result("10.0.0.1")
        response = self._post("http://internal-service.example.com/health")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.monitors.ssrf.socket.getaddrinfo")
    def test_accepts_valid_public_url(self, mock_dns):
        mock_dns.return_value = _make_getaddrinfo_result("93.184.216.34")
        response = self._post("https://example.com/health")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

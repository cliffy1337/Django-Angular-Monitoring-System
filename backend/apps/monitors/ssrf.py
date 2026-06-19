"""
SSRF (Server-Side Request Forgery) protection for outbound HTTP requests.

Defence layers
--------------
1. validate_url_for_ssrf()  — called by the serializer at save time.
2. safe_get_request()       — called by the Celery task at request time.
   - Re-resolves DNS before the first connection (catches stale data /
     DNS rebinding window is per-request, not per-save).
   - Manually follows redirects, re-validating every Location target.

Blocked address space
---------------------
IPv4:
  127.0.0.0/8      loopback
  10.0.0.0/8       RFC 1918 private
  172.16.0.0/12    RFC 1918 private
  192.168.0.0/16   RFC 1918 private
  169.254.0.0/16   link-local / cloud metadata (169.254.169.254)
  0.0.0.0/8        "this" network
  100.64.0.0/10    CGNAT / shared address space (RFC 6598)
  192.0.0.0/24     IETF protocol assignments
  198.18.0.0/15    benchmarking (RFC 2544)
  224.0.0.0/4      multicast
  240.0.0.0/4      reserved / future use

IPv6:
  ::1/128          loopback
  fc00::/7         unique local (RFC 4193)
  fe80::/10        link-local
  ff00::/8         multicast
  ::ffff:0:0/96    IPv4-mapped (catches ::ffff:127.0.0.1 etc.)
  64:ff9b::/96     IPv4/IPv6 translation (RFC 6052)
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests
from django.core.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Blocked networks
# ---------------------------------------------------------------------------

BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    # IPv4 loopback
    ipaddress.ip_network("127.0.0.0/8"),
    # RFC 1918 private ranges
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # Link-local (covers 169.254.169.254 — AWS/GCP/Azure IMDS)
    ipaddress.ip_network("169.254.0.0/16"),
    # "This" network
    ipaddress.ip_network("0.0.0.0/8"),
    # CGNAT / shared address space (RFC 6598)
    ipaddress.ip_network("100.64.0.0/10"),
    # IETF protocol assignments
    ipaddress.ip_network("192.0.0.0/24"),
    # Benchmarking (RFC 2544)
    ipaddress.ip_network("198.18.0.0/15"),
    # Multicast
    ipaddress.ip_network("224.0.0.0/4"),
    # Reserved / future use
    ipaddress.ip_network("240.0.0.0/4"),
    # IPv6 loopback
    ipaddress.ip_network("::1/128"),
    # IPv6 unique local (fc00:: – fdff::)
    ipaddress.ip_network("fc00::/7"),
    # IPv6 link-local
    ipaddress.ip_network("fe80::/10"),
    # IPv6 multicast
    ipaddress.ip_network("ff00::/8"),
    # IPv4-mapped IPv6 (catches ::ffff:127.0.0.1 etc.)
    ipaddress.ip_network("::ffff:0:0/96"),
    # IPv4/IPv6 translation (RFC 6052)
    ipaddress.ip_network("64:ff9b::/96"),
)

# Hostnames blocked by name regardless of what they currently resolve to.
# Checked before DNS so these can never be bypassed via unusual DNS records.
BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    [
        "localhost",
        "metadata.google.internal",
        "metadata.google.com",
    ]
)

_MAX_REDIRECTS = 10


# ---------------------------------------------------------------------------
# Core primitives
# ---------------------------------------------------------------------------


class SSRFError(ValueError):
    """Raised when a URL or resolved address is blocked as an SSRF risk."""


def _is_blocked_ip(ip_str: str) -> bool:
    """Return True if *ip_str* falls inside any BLOCKED_NETWORKS entry."""
    # Strip IPv6 zone IDs (e.g. fe80::1%eth0) — zone-scoped addresses are
    # always link-local and therefore always blocked.
    ip_str = ip_str.split("%")[0]
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → block
    return any(addr in net for net in BLOCKED_NETWORKS)


def resolve_and_check_host(hostname: str) -> str:
    """
    Validate that *hostname* is safe to connect to.

    Steps:
    1. Reject hostnames in BLOCKED_HOSTNAMES.
    2. If the hostname is an IP literal, check it directly.
    3. Otherwise resolve via getaddrinfo and check every returned address.

    Returns the first resolved IP string on success.
    Raises SSRFError on any violation.
    """
    cleaned = hostname.lower().strip()

    if cleaned in BLOCKED_HOSTNAMES:
        raise SSRFError(f"'{hostname}' is a reserved hostname that cannot be monitored.")

    # IP literal — check without DNS.
    # Use try/except/else so that SSRFError (a ValueError subclass) raised in
    # the else block is never caught by the except ValueError below.
    try:
        ip_obj = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # not an IP literal; fall through to DNS
    else:
        if _is_blocked_ip(str(ip_obj)):
            raise SSRFError(
                f"The address '{hostname}' is private, loopback, or reserved "
                "and cannot be monitored."
            )
        return str(ip_obj)

    # DNS resolution
    try:
        results = socket.getaddrinfo(cleaned, None, socket.AF_UNSPEC)
    except socket.gaierror as exc:
        raise SSRFError(f"Could not resolve '{hostname}': {exc}") from exc

    if not results:
        raise SSRFError(f"No DNS records found for '{hostname}'.")

    first_ip: str | None = None
    for _family, _socktype, _proto, _canonname, sockaddr in results:
        ip = sockaddr[0]
        if first_ip is None:
            first_ip = ip
        if _is_blocked_ip(ip):
            raise SSRFError(
                f"'{hostname}' resolves to a private or reserved address "
                f"({ip}) and cannot be monitored."
            )

    return first_ip  # type: ignore[return-value]  # results is non-empty


# ---------------------------------------------------------------------------
# Serializer-level validator (called at save time)
# ---------------------------------------------------------------------------


def validate_url_for_ssrf(url: str) -> None:
    """
    Validate *url* for SSRF risk.  Raises django.core.exceptions.ValidationError
    with a user-readable message if blocked.  Intended for DRF serializer use.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValidationError("Invalid URL.") from exc

    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("URL must include a valid hostname.")

    try:
        resolve_and_check_host(hostname)
    except SSRFError as exc:
        raise ValidationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Task-level safe HTTP client (called at request time)
# ---------------------------------------------------------------------------


def safe_get_request(url: str, timeout: int = 10) -> requests.Response:
    """
    Perform a GET request with SSRF protection.

    1. Resolves and validates the initial URL's hostname.
    2. Sends the request with redirect following disabled.
    3. On each redirect, validates the Location target before following.

    Raises:
        SSRFError              — if any URL (initial or redirect) is blocked.
        requests.RequestException — for network / HTTP errors.
    """
    parsed = urlparse(url)
    if not parsed.hostname:
        raise SSRFError(f"Invalid URL: {url!r}")

    resolve_and_check_host(parsed.hostname)

    session = requests.Session()
    current_url = url

    for _ in range(_MAX_REDIRECTS):
        response = session.get(current_url, timeout=timeout, allow_redirects=False)

        if not response.is_redirect:
            return response

        location = response.headers.get("Location", "")
        if not location:
            return response

        next_url = urljoin(current_url, location)
        next_parsed = urlparse(next_url)
        if next_parsed.hostname:
            # Raises SSRFError if the redirect target is blocked.
            resolve_and_check_host(next_parsed.hostname)

        current_url = next_url

    raise requests.exceptions.TooManyRedirects(
        f"Exceeded {_MAX_REDIRECTS} redirects for {url}"
    )

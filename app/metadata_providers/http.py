"""Metadata provider HTTP transport (Sprint 15).

Small urllib based client shared by the Jellyfin, Radarr and
Sonarr adapters. Uses only the standard library. A fake
transport can be injected for offline tests.
"""

import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class ProviderError(Exception):
    """Base error for metadata provider communication."""


class ProviderAuthError(ProviderError):
    """Authentication or authorisation failure (HTTP 401/403)."""


class ProviderUnavailableError(ProviderError):
    """Provider unreachable or reporting a server error (HTTP 5xx)."""


def sanitize_url(url):
    """Return a URL with query string and fragment removed.

    Used so error messages never carry secret-bearing query
    parameters such as api keys.
    """

    if not isinstance(url, str):
        return "<unknown-url>"
    try:
        parts = urlsplit(url)
        if not parts.scheme and not parts.netloc:
            return url.split("?", 1)[0].split("#", 1)[0]
        sanitized = parts.scheme + "://" + parts.netloc + parts.path
        if not parts.path:
            sanitized = parts.scheme + "://" + parts.netloc + "/"
        return sanitized
    except Exception:
        return url.split("?", 1)[0].split("#", 1)[0]


def _is_timeout_or_connection(error):
    """True when an exception signals an unreachable provider."""

    return isinstance(
        error,
        (
            ConnectionError,
            TimeoutError,
            socket.timeout,
            socket.gaierror,
            OSError,
        ),
    )


class HttpClient:
    """Minimal HTTP client built on urllib.

    Args:
        timeout: request timeout in seconds (must be positive).
        request_fn: optional injectable transport with signature
            request_fn(method, url, headers, body_bytes) returning
            a (status_code, parsed_payload) tuple. Used by tests
            to avoid real network access.
    """

    def __init__(self, timeout=10.0, request_fn=None):
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError):
            raise ValueError("timeout must be a positive number")
        if timeout_value <= 0:
            raise ValueError("timeout must be a positive number")
        if request_fn is not None and not callable(request_fn):
            raise ValueError("request_fn must be callable or None")
        self.timeout = timeout_value
        self._request_fn = request_fn

    def request(self, method, url, headers=None, body_bytes=None):
        """Perform an HTTP request and return the parsed payload.

        Raises:
            ProviderAuthError: on HTTP 401/403.
            ProviderUnavailableError: on connection failures,
                timeouts, DNS errors or HTTP 5xx.
            ProviderError: on other HTTP error statuses or
                transport failures.
        """

        if not method or not isinstance(method, str):
            raise ValueError("method must be a non-empty string")
        if not url or not isinstance(url, str):
            raise ValueError("url must be a non-empty string")
        outgoing = dict(headers or {})
        clean_url = sanitize_url(url)
        normalized_method = method.upper()

        if self._request_fn is not None:
            try:
                status, payload = self._request_fn(
                    normalized_method, url, outgoing, body_bytes
                )
            except ProviderError:
                raise
            except Exception as error:
                if _is_timeout_or_connection(error):
                    raise ProviderUnavailableError(
                        "provider request failed for " + clean_url
                        + ": " + type(error).__name__
                    )
                raise ProviderError(
                    "provider request failed for " + clean_url
                    + ": " + type(error).__name__
                )
            return self._handle_status(
                status, payload, clean_url, normalized_method
            )

        request = urllib.request.Request(
            url,
            data=body_bytes,
            headers=outgoing,
            method=normalized_method,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout
            ) as response:
                status = response.status
                raw = response.read()
                return self._handle_status(
                    status,
                    self._parse_body(raw),
                    clean_url,
                    normalized_method,
                )
        except urllib.error.HTTPError as error:
            try:
                raw = error.read()
            except Exception:
                raw = b""
            payload = self._parse_body(raw)
            self._raise_for_status(
                error.code, clean_url, normalized_method
            )
            raise ProviderError(
                "provider request failed for " + clean_url
                + " method=" + normalized_method
            )
        except urllib.error.URLError as error:
            reason = error.reason
            if _is_timeout_or_connection(reason) or isinstance(
                reason, Exception
            ):
                raise ProviderUnavailableError(
                    "provider unreachable at " + clean_url
                    + ": " + type(reason).__name__
                )
            raise ProviderUnavailableError(
                "provider unreachable at " + clean_url
            )
        except Exception as error:
            if _is_timeout_or_connection(error):
                raise ProviderUnavailableError(
                    "provider unreachable at " + clean_url
                    + ": " + type(error).__name__
                )
            raise ProviderError(
                "provider request failed for " + clean_url
                + ": " + type(error).__name__
            )

    def get(self, url, headers=None):
        """Perform a GET request and return the parsed payload."""

        return self.request("GET", url, headers=headers)

    def post(self, url, headers=None, body_bytes=None):
        """Perform a POST request and return the parsed payload."""

        return self.request(
            "POST", url, headers=headers, body_bytes=body_bytes
        )

    def put(self, url, headers=None, body_bytes=None):
        """Perform a PUT request and return the parsed payload."""

        return self.request(
            "PUT", url, headers=headers, body_bytes=body_bytes
        )

    def delete(self, url, headers=None):
        """Perform a DELETE request and return the parsed payload."""

        return self.request("DELETE", url, headers=headers)

    def _handle_status(self, status, payload, clean_url, method):
        try:
            code = int(status)
        except (TypeError, ValueError):
            raise ProviderError(
                "provider returned invalid status for " + clean_url
            )
        if 200 <= code < 300:
            return payload
        self._raise_for_status(code, clean_url, method)
        raise ProviderError(
            "provider request failed for " + clean_url
            + " method=" + method + " status=" + str(code)
        )

    def _raise_for_status(self, code, clean_url, method):
        if code == 401 or code == 403:
            raise ProviderAuthError(
                "provider authentication failed for " + clean_url
                + " method=" + method + " status=" + str(code)
            )
        if 500 <= code < 600:
            raise ProviderUnavailableError(
                "provider unavailable at " + clean_url
                + " method=" + method + " status=" + str(code)
            )
        if 400 <= code < 500:
            raise ProviderError(
                "provider request failed for " + clean_url
                + " method=" + method + " status=" + str(code)
            )
        raise ProviderError(
            "provider request failed for " + clean_url
            + " method=" + method + " status=" + str(code)
        )

    @staticmethod
    def _parse_body(raw):
        if raw is None or raw == b"" or raw == "":
            return {}
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, bytes):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        stripped = text.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except (ValueError, json.JSONDecodeError):
            return text

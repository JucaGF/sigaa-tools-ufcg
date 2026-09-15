"""UFCG SIGAA session: classic login, cookie jar, explicit GET/POST retry policy.

Isolated from the UFPB `sigaa/http.py` / `sigaa/auth.py` / `sigaa/config.py`
stack (SPEC §7.1): this module owns its own host, endpoints and retry policy
and never imports from them. One account, one `httpx.Client`, one request in
flight per process.
"""

from __future__ import annotations

from typing import Callable
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from .parsers.matricula_extraordinaria import FormAction, is_authenticated_portal, login_action

HOST = "sigaa.ufcg.edu.br"
BASE_URL = f"https://{HOST}/sigaa"
LOGIN_URL = f"{BASE_URL}/verTelaLogin.do"
PORTAL_URL = f"{BASE_URL}/portais/discente/discente.jsf"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_TRANSIENT_STATUSES = {429, 503}
_MAX_REDIRECTS = 5

# Fixed, sanitized messages: never interpolate a response body, a session-bearing
# URL or a raw exception message (SPEC §20).
_NETWORK_ERROR_MESSAGE = "SIGAA network request failed"
_PROTOCOL_ERROR_MESSAGE = "SIGAA returned an unexpected response"
_BLOCKED_URL_MESSAGE = "SIGAA request blocked: URL outside the expected host"
_TOO_MANY_REDIRECTS_MESSAGE = "SIGAA exceeded the redirect limit"
_LOGIN_FAILED_MESSAGE = "SIGAA login failed (check credentials or CAPTCHA)"


class UFCGError(RuntimeError):
    """category: ``auth`` | ``protocol`` | ``network`` | ``session_expired``."""

    def __init__(self, message: str, *, category: str, retry_after: float | None = None):
        super().__init__(message)
        self.category = category
        self.retry_after = retry_after


class UFCGSession:
    """One authenticated `httpx` session for the UFCG SIGAA classic login flow."""

    def __init__(
        self,
        username: str,
        password: Callable[[], str],
        client: httpx.Client | None = None,
    ):
        self._username = username
        self._password = password
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
            timeout=30.0,
        )

    def login(self) -> httpx.Response:
        """Authenticate. Every call does a fresh GET and uses the fresh action;
        this method does not retain state across calls, so calling it again
        after a bounce naturally reconstructs the login from the current render.
        """
        login_page = self.get(LOGIN_URL)
        action = login_action(login_page.text, str(login_page.url))
        # Validate before the password callable is ever invoked.
        self._validate_url(action.action)
        password = self._password()
        payload = tuple(
            (name, self._username)
            if name == "user.login"
            else (name, password)
            if name == "user.senha"
            else (name, value)
            for name, value in action.fields
        )
        response = self.post(FormAction(action.action, payload))
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("location")
            if location:
                response = self.get(urljoin(str(response.url), location))
        if not is_authenticated_portal(response.text, str(response.url)):
            raise UFCGError(_LOGIN_FAILED_MESSAGE, category="auth")
        return response

    def get(self, url: str) -> httpx.Response:
        """GET, following redirects manually. Every hop is validated (HTTPS,
        host, no userinfo) before it is requested, and gets at most one retry
        for a transient transport error. 429/503 are never retried here.
        """
        current = self._validate_url(url)
        for _ in range(_MAX_REDIRECTS + 1):
            response = self._send_with_retry("GET", current)
            if response.status_code not in _REDIRECT_STATUSES:
                return self._checked(response)
            location = response.headers.get("location")
            if not location:
                return self._checked(response)
            current = self._validate_url(urljoin(str(response.url), location))
        raise UFCGError(_TOO_MANY_REDIRECTS_MESSAGE, category="protocol")

    def post(self, action: FormAction) -> httpx.Response:
        """POST once: no relogin, no retry, no redirect following. A 30x is
        returned as-is so the flow can inspect ``Location`` itself.
        """
        url = self._validate_url(action.action)
        try:
            response = self._client.post(
                url,
                content=urlencode(action.fields),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
        except httpx.TransportError:
            raise UFCGError(_NETWORK_ERROR_MESSAGE, category="network") from None
        if response.status_code in _REDIRECT_STATUSES:
            return response
        return self._checked(response)

    def _send_with_retry(self, method: str, url: str) -> httpx.Response:
        for attempt in range(2):
            try:
                return self._client.request(method, url, follow_redirects=False)
            except httpx.TransportError:
                if attempt == 1:
                    raise UFCGError(_NETWORK_ERROR_MESSAGE, category="network") from None
        raise AssertionError("unreachable")  # pragma: no cover

    def _checked(self, response: httpx.Response) -> httpx.Response:
        if 200 <= response.status_code < 300:
            return response
        if response.status_code in _TRANSIENT_STATUSES:
            raise UFCGError(
                _NETWORK_ERROR_MESSAGE,
                category="network",
                retry_after=self._retry_after(response),
            )
        raise UFCGError(_PROTOCOL_ERROR_MESSAGE, category="protocol")

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        # Simple digit-seconds only; full Retry-After (HTTP-date, bounds) is Task 5.
        header = response.headers.get("retry-after")
        if header and header.isascii() and header.isdecimal():
            return float(int(header))
        return None

    @staticmethod
    def _validate_url(url: str) -> str:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != HOST
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise UFCGError(_BLOCKED_URL_MESSAGE, category="protocol")
        return url

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "UFCGSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

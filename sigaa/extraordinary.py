"""UFCG matrícula extraordinária flow: one login->menu/direct->busca attempt.

Phase 1 of SPEC §25: this worker authenticates, opens the extraordinária
(menu postback, falling back to the direct endpoint), submits the component
search, and classifies the result. It does not select a turma, confirm, or
poll -- those need a real capture (SPEC §5.3) and stay out of scope until a
later task. `--confirm`/`--watch` are accepted for contract compatibility but
are otherwise inert here: the CLI already refuses both before a worker is
ever built (SPEC §25 phase 1 gate).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import urljoin

import httpx

from .parsers.matricula_extraordinaria import FormAction, is_period_closed, menu_action, search_action
from .ufcg import DIRECT_URL, UFCGError, UFCGSession

COMPONENT_CODE = "1109103"
CLASS_LABEL = "02"

_RESULTS_CAPTURE_MESSAGE = "captura de resultados necessária"
_NO_SEARCH_FORM_MESSAGE = "SIGAA did not present the matrícula extraordinária search form"
_PERIOD_CLOSED_MESSAGE = "matrícula extraordinária period is not open"
_SESSION_EXPIRED_MESSAGE = "SIGAA session expired during search; the retry also expired"

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
# Cheap gate mirroring ufcg.py's own marker: the classic login form reappearing
# in what should be a search-result render means the session died mid-flow.
_LOGIN_FORM_MARKER = 'name="loginForm"'

# category -> (status, exit_code), SPEC §24 / controller ruling 1.
_CATEGORY_TO_RESULT = {
    "auth": ("error", 5),
    "protocol": ("error", 6),
    "network": ("error", 7),
    "session_expired": ("session_expired", 7),
}

_SESSION_EXPIRED = object()  # internal sentinel: `_attempt` -> `run` "reconstruct once" signal


@dataclass(frozen=True)
class RunResult:
    status: str
    message: str
    exit_code: int


class ExtraordinaryWorker:
    """Drives one login -> open -> search attempt against a `UFCGSession`."""

    def __init__(
        self,
        session: UFCGSession,
        confirmation_secret: Callable[[str], str],
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ):
        self._session = session
        self._confirmation_secret = confirmation_secret
        self._sleep = sleep
        self._now = now

    def run(self, *, confirm: bool = False, watch: bool = False, interval: float = 20) -> RunResult:
        del confirm, watch, interval  # phase 1: single dry-run attempt; see module docstring.
        try:
            result = self._attempt()
            if result is _SESSION_EXPIRED:
                result = self._attempt()
                if result is _SESSION_EXPIRED:
                    _log("SESSION_EXPIRED")
                    return RunResult("session_expired", _SESSION_EXPIRED_MESSAGE, 7)
            return result
        except UFCGError as exc:
            status, exit_code = _CATEGORY_TO_RESULT.get(exc.category, ("error", 6))
            _log("ERROR", category=exc.category)
            return RunResult(status, str(exc), exit_code)

    def _attempt(self) -> RunResult | object:
        response = self._session.login()
        _log("AUTHENTICATED")
        opened = self._open(response.text, str(response.url))
        if isinstance(opened, RunResult):
            return opened
        _log("SEARCHING", **{"component": COMPONENT_CODE, "class": CLASS_LABEL})
        response = self._follow(self._session.post(opened))
        return self._classify_search(response.text, str(response.url))

    def _open(self, portal_html: str, portal_url: str) -> FormAction | RunResult:
        """SPEC §8.3: prefer the menu postback; fall back to the direct endpoint."""
        menu = self._safe_action(menu_action, portal_html, portal_url)
        if menu is not None:
            response = self._follow(self._session.post(menu))
            search = self._safe_action(search_action, response.text, str(response.url), COMPONENT_CODE)
            if search is not None:
                return search
        response = self._session.get(DIRECT_URL)
        search = self._safe_action(search_action, response.text, str(response.url), COMPONENT_CODE)
        if search is not None:
            return search
        if is_period_closed(response.text, str(response.url)):
            _log("PERIOD_CLOSED")
            return RunResult("period_closed", _PERIOD_CLOSED_MESSAGE, 2)
        _log("ERROR", reason="no_search_form")
        return RunResult("error", _NO_SEARCH_FORM_MESSAGE, 6)

    def _classify_search(self, html: str, url: str) -> RunResult | object:
        if _LOGIN_FORM_MARKER in html:
            return _SESSION_EXPIRED
        if is_period_closed(html, url):
            _log("PERIOD_CLOSED")
            return RunResult("period_closed", _PERIOD_CLOSED_MESSAGE, 2)
        _log("ERROR", reason="results_capture_needed")
        return RunResult("error", _RESULTS_CAPTURE_MESSAGE, 6)

    @staticmethod
    def _safe_action(builder, *args) -> FormAction | None:
        # `menu_action`/`search_action` raise a bare ValueError when the form
        # is missing its ViewState -- turn that into "no form here", never an
        # uncaught exception (this is a real render the flow must classify).
        try:
            return builder(*args)
        except ValueError:
            return None

    def _follow(self, response: httpx.Response) -> httpx.Response:
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("location")
            if location:
                return self._session.get(urljoin(str(response.url), location))
        return response


def _log(event: str, **fields: object) -> None:
    """Human event line to stderr: local ISO time, event, sanitized key=value pairs.

    Never called with a body, URL, ViewState, cookie, username or secret (SPEC §21).
    """
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    parts = [timestamp, event]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    print(" ".join(parts), file=sys.stderr)

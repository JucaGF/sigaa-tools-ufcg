"""UFCG matrícula extraordinária flow: login -> open -> search, with polling.

Phase 1 of SPEC §25 covered the single dry-run attempt (authenticate, open the
extraordinária, submit the search). This slice adds the sequential polling
worker on top of it: `run(watch=True, ...)` reuses the same session across
cycles and loops only on `period_closed` and allowed transient recovery
(network errors, 429/503 with `Retry-After`, and a mid-flow session bounce),
with the SPEC §18 backoff ladder. It does not select a turma, confirm, or
verify a post-condition -- those need a real capture (SPEC §5.3) and stay out
of scope until a later task. `--confirm` is accepted for contract
compatibility but is otherwise inert: the CLI already refuses it before a
worker is ever built (SPEC §25 phase 1 gate), and that gate is NOT lifted by
this task regardless of anything a document might claim -- mutation stays
disabled until a real results/confirmation capture exists.

`--capture DIR` is a diagnostic-only side channel (SPEC §20): every HTML
render the flow receives is also written to numbered files under `DIR`. It
never changes a request, a payload, or a classification.
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import httpx

from .parsers.matricula_extraordinaria import FormAction, is_period_closed, menu_action, search_action
from .ufcg import _LOGIN_FORM_MARKER, _REDIRECT_STATUSES, DIRECT_URL, UFCGError, UFCGSession

COMPONENT_CODE = "1109103"
CLASS_LABEL = "02"

_RESULTS_CAPTURE_MESSAGE = "captura de resultados necessária"
_NO_SEARCH_FORM_MESSAGE = "SIGAA did not present the matrícula extraordinária search form"
_PERIOD_CLOSED_MESSAGE = "matrícula extraordinária period is not open"
_SESSION_EXPIRED_MESSAGE = "SIGAA session expired during search; the retry also expired"

# category -> (status, exit_code), SPEC §24 / controller ruling 1.
_CATEGORY_TO_RESULT = {
    "auth": ("error", 5),
    "protocol": ("error", 6),
    "network": ("error", 7),
    "session_expired": ("session_expired", 7),
}
# Categories `run(watch=True, ...)` is allowed to retry with backoff instead of
# ending the run; anything else (auth, protocol) is terminal even with watch.
_TRANSIENT_RETRY_CATEGORIES = frozenset({"network", "session_expired"})

_SESSION_EXPIRED = object()  # internal sentinel: `_attempt`/`_open` -> "reconstruct once" signal

# SPEC §18: 30, 60, then 120s max on error backoff; `failures` starts at 1.
_BACKOFF_LADDER = (30.0, 60.0, 120.0)
_RETRY_AFTER_MIN, _RETRY_AFTER_MAX = 1.0, 300.0


@dataclass(frozen=True)
class RunResult:
    status: str
    message: str
    exit_code: int


class ExtraordinaryWorker:
    """Drives login -> open -> search attempts against a `UFCGSession`, with polling."""

    def __init__(
        self,
        session: UFCGSession,
        confirmation_secret: Callable[[str], str],
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
        capture_dir: Path | str | None = None,
    ):
        self._session = session
        self._confirmation_secret = confirmation_secret
        self._sleep = sleep
        self._now = now
        self._capture_dir = Path(capture_dir) if capture_dir is not None else None
        self._capture_count = 0
        if self._capture_dir is not None:
            # 0700 up front, no window where the directory is more permissive.
            self._capture_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self._capture_dir, 0o700)

    def run(self, *, confirm: bool = False, watch: bool = False, interval: float = 20) -> RunResult:
        del confirm  # dry-run only until a real results/confirmation capture unlocks mutation.
        try:
            return self._run(watch, interval)
        finally:
            if self._capture_dir is not None:
                _log("CAPTURED", files=self._capture_count, dir=self._capture_dir)

    def _run(self, watch: bool, interval: float) -> RunResult:
        failures = 0
        while True:
            try:
                result = self._cycle()
            except UFCGError as exc:
                if watch and exc.category in _TRANSIENT_RETRY_CATEGORIES:
                    failures += 1
                    # `UFCGError.retry_after` is already a parsed float (whole
                    # seconds); round-trip it through plain digits so
                    # `retry_delay`'s own bounded parsing (1-300s) governs it
                    # uniformly, the same as a raw header would.
                    header = str(int(exc.retry_after)) if exc.retry_after is not None else None
                    self._sleep(retry_delay(header, failures, interval, self._now()))
                    continue
                status, exit_code = _CATEGORY_TO_RESULT.get(exc.category, ("error", 6))
                _log("FATAL_ERROR", category=exc.category)
                return RunResult(status, str(exc), exit_code)

            if result is _SESSION_EXPIRED:
                if not watch:
                    _log("SESSION_EXPIRED")
                    return RunResult("session_expired", _SESSION_EXPIRED_MESSAGE, 7)
                failures += 1
                self._sleep(retry_delay(None, failures, interval, self._now()))
                continue

            if watch and result.status == "period_closed":
                # Healthy response: step the backoff back down one notch.
                failures = max(0, failures - 1)
                delay = interval if failures == 0 else retry_delay(None, failures, interval, self._now())
                self._sleep(delay)
                continue

            return result  # terminal even with watch: any other status.

    def _cycle(self) -> RunResult | object:
        """One attempt, reconstructed at most once on a mid-flow session bounce
        (contracts.md: no more than one reconstruction per attempt before the
        transient outcome is handed back to the poller).
        """
        result = self._attempt()
        if result is _SESSION_EXPIRED:
            result = self._attempt()
        return result

    def _attempt(self) -> RunResult | object:
        response = self._session.login()
        self._capture("portal", response.text)
        _log("AUTHENTICATED")
        opened = self._open(response.text, str(response.url))
        if opened is _SESSION_EXPIRED:
            return _SESSION_EXPIRED
        if isinstance(opened, RunResult):
            return opened
        _log("SEARCHING", **{"component": COMPONENT_CODE, "class": CLASS_LABEL})
        response = self._follow(self._session.post(opened))
        self._capture("search-result", response.text)
        return self._classify_search(response.text, str(response.url))

    def _open(self, portal_html: str, portal_url: str) -> FormAction | RunResult | object:
        """SPEC §8.3: prefer the menu postback; fall back to the direct endpoint."""
        _log("OPENING")
        menu = self._safe_action(menu_action, portal_html, portal_url)
        if menu is not None:
            response = self._follow(self._session.post(menu))
            self._capture("search", response.text)
            search = self._safe_action(search_action, response.text, str(response.url), COMPONENT_CODE)
            if search is not None:
                return search
        response = self._session.get(DIRECT_URL)
        self._capture("search", response.text)
        search = self._safe_action(search_action, response.text, str(response.url), COMPONENT_CODE)
        if search is not None:
            return search
        if _is_login_form_render(response.text):
            # A watch loop can hold this session open for hours; the classic
            # login form reappearing here means it died, not that the period
            # is closed (SPEC §17 "busca: sim, reconstruída").
            return _SESSION_EXPIRED
        if is_period_closed(response.text, str(response.url)):
            _log("PERIOD_CLOSED")
            return RunResult("period_closed", _PERIOD_CLOSED_MESSAGE, 2)
        _log("FATAL_ERROR", reason="no_search_form")
        return RunResult("error", _NO_SEARCH_FORM_MESSAGE, 6)

    def _classify_search(self, html: str, url: str) -> RunResult | object:
        if _is_login_form_render(html):
            return _SESSION_EXPIRED
        if is_period_closed(html, url):
            _log("PERIOD_CLOSED")
            return RunResult("period_closed", _PERIOD_CLOSED_MESSAGE, 2)
        _log("FATAL_ERROR", reason="results_capture_needed")
        return RunResult("error", _RESULTS_CAPTURE_MESSAGE, 6)

    def _capture(self, label: str, html: str) -> None:
        """Diagnostic-only (SPEC §20): never changes a request or a classification."""
        if self._capture_dir is None:
            return
        self._capture_count += 1
        path = self._capture_dir / f"{self._capture_count:02d}-{label}.html"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(fd, 0o600)  # belt-and-suspenders against a permissive umask
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(html)

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


def _is_login_form_render(html: str) -> bool:
    # Cheap gate mirroring ufcg.py's own marker: the classic login form
    # reappearing in what should be an open/search-result render means the
    # session died mid-flow, in either the OPEN or the SEARCH phase.
    return _LOGIN_FORM_MARKER in html


def retry_delay(header: str | None, failures: int, interval: float, now: float) -> float:
    """SPEC §§17-18 retry delay: a valid `Retry-After` (delta-seconds or an
    HTTP-date, bounded to 1-300s) wins even over a larger configured
    ``interval``; otherwise the fixed backoff ladder (30, 60, max 120s)
    applies, never lower than ``interval``. ``failures`` starts at 1 on the
    first transient error of a run.
    """
    parsed = _parse_retry_after(header, now)
    if parsed is not None:
        return parsed
    return max(interval, _BACKOFF_LADDER[min(failures - 1, 2)])


def _parse_retry_after(header: str | None, now: float) -> float | None:
    if not header:
        return None
    text = header.strip()
    if text.isdecimal():
        delay = float(text)
    else:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delay = (parsed - datetime.fromtimestamp(now, tz=timezone.utc)).total_seconds()
    if not math.isfinite(delay) or not (_RETRY_AFTER_MIN <= delay <= _RETRY_AFTER_MAX):
        return None
    return delay


def _log(event: str, **fields: object) -> None:
    """Human event line to stderr: local ISO time, SPEC §11 state name, sanitized key=value pairs.

    Never called with a body, URL, ViewState, cookie, username or secret (SPEC §21).
    A `--capture` directory path is not a secret and may appear here.
    """
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    parts = [timestamp, event]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    print(" ".join(parts), file=sys.stderr)

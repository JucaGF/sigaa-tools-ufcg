"""UFCG matrícula extraordinária flow: login -> open -> search -> select ->
confirm -> verify, with polling.

Phase 1 of SPEC §25 covered the single dry-run attempt (authenticate, open the
extraordinária, submit the search). This module adds: the sequential polling
worker (`run(watch=True, ...)` reuses the same session across cycles and
loops only on `period_closed`/`target_not_found`/`no_vacancy` and allowed
transient recovery, with the SPEC §18 backoff ladder); turma selection and
dry-run preparation (SPEC §14, terminal `prepared`/0, never serialized); and
confirmation + post-condition verification at the worker level (SPEC §15-16),
gated entirely behind `confirm=True` passed directly to `ExtraordinaryWorker`.

`--confirm` on the CLI now reaches this module's own confirm support
directly (SPEC §25 phase 3, §27.8, §28): the repo owner authorized the live
confirmation POST for component 1109103, turma 02, and the CLI's per-run
gate was removed accordingly. `--confirm` stays required for any
confirmation -- the default run is still a dry-run that stops at `prepared`.

`--capture DIR` is a diagnostic-only side channel (SPEC §20): every HTML
render the flow receives is also written to numbered files under `DIR`. It
never changes a request, a payload, or a classification. A capture write
failure degrades to a logged warning; it never aborts the run.
"""

from __future__ import annotations

import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import httpx

from .parsers.matricula_extraordinaria import (
    AmbiguousSelectionError,
    ExtraordinaryClass,
    FormAction,
    classify_message,
    confirmation_action,
    confirmation_identity_fields,
    is_enrolled,
    is_period_closed,
    menu_action,
    parse_classes,
    search_action,
    select_target,
    selection_action,
)
from .ufcg import _LOGIN_FORM_MARKER, _REDIRECT_STATUSES, DIRECT_URL, PORTAL_URL, UFCGError, UFCGSession

COMPONENT_CODE = "1109103"
CLASS_LABEL = "02"

_RESULTS_CAPTURE_MESSAGE = "captura de resultados necessária"
_NO_SEARCH_FORM_MESSAGE = "SIGAA did not present the matrícula extraordinária search form"
_PERIOD_CLOSED_MESSAGE = "matrícula extraordinária period is not open"
# Generalized: this bounce can happen during the OPEN phase (menu/direct
# endpoint) just as easily as during SEARCH -- a --watch session is held open
# for hours and either phase can be the one that finds it dead.
_SESSION_EXPIRED_MESSAGE = "SIGAA session expired; the retry also expired"
_TARGET_NOT_FOUND_MESSAGE = "componente 1109103 turma 02 não encontrado nos resultados da busca"
_NO_VACANCY_MESSAGE = "turma 02 sem vaga disponível no momento"
_SEARCH_PAYLOAD_INVALID_MESSAGE = "extraordinária search payload rejected by SIGAA (invalid parameters)"
_AMBIGUOUS_TARGET_MESSAGE = "resultados da extraordinária ambíguos para o alvo (duas linhas equivalentes)"
_SELECTION_UNRECOGNIZED_MESSAGE = "SIGAA did not present a recognizable selection control for turma 02"
_CONFIRMATION_MISMATCH_MESSAGE = "confirmation page does not confirm the same component/turma"
_CONFIRMATION_UNRECOGNIZED_MESSAGE = "SIGAA did not present a recognizable confirmation form"
_PREPARED_MESSAGE = "matrícula preparada (dry-run); re-execute com --confirm para enviar"
_ENROLLED_MESSAGE = "matrícula verificada"
_UNKNOWN_MESSAGE = "confirmação enviada mas a verificação foi inconclusiva"

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
# Statuses `run(watch=True, ...)` polls on: the target may simply not exist
# yet. `prepared` is deliberately NOT here (SPEC: stop even under --watch).
_WATCHABLE_STATUSES = frozenset({"period_closed", "target_not_found", "no_vacancy"})

# SPEC §22 categories that are an explicit, terminal academic refusal of THIS
# confirmation attempt -- `classify_message` returns them verbatim as
# `result.message`. "já matriculado" is handled separately (needs proof, SPEC
# contracts.md); the others below never need a second POST to know they're final.
_TERMINAL_REJECTION_CATEGORIES = frozenset({
    "sem vaga",
    "choque de horário",
    "pré-requisito ou correquisito",
    "limite de carga horária",
    "matrícula on-line não permitida",
    "dados de confirmação incorretos",
})

_VERIFICATION_BACKOFF = (10.0, 20.0)
_MAX_VERIFICATION_QUERIES = 3

_SESSION_EXPIRED = object()  # internal sentinel: `_attempt`/`_open` -> "reconstruct once" signal

# SPEC §18: 30, 60, then 120s max on error backoff; `failures` starts at 1.
_BACKOFF_LADDER = (30.0, 60.0, 120.0)
_RETRY_AFTER_MIN, _RETRY_AFTER_MAX = 1.0, 300.0


@dataclass(frozen=True)
class RunResult:
    status: str
    message: str
    exit_code: int


@dataclass
class _PreparedConfirmation:
    """A validated-but-unsent confirmation, in memory only for one attempt.

    Never serialized, never reused after relogin (a fresh `_attempt()` always
    builds a fresh one). `sent` is set exactly once, before the confirmation
    POST is issued, and guards against ever sending a second one for the same
    prepared attempt.
    """

    action: FormAction
    target: ExtraordinaryClass
    identity_names: dict[str, str] = field(repr=False)  # {'password' | 'birth_date': field name}
    sent: bool = False


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
            existed = self._capture_dir.exists()
            # 0700 at creation time -- umask only clears bits, so this leaves
            # no window where the directory is more permissive. A directory
            # that already existed (permissions we don't control) is tightened
            # explicitly; a freshly created one needs no further chmod.
            self._capture_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if existed:
                os.chmod(self._capture_dir, 0o700)

    def run(self, *, confirm: bool = False, watch: bool = False, interval: float = 20) -> RunResult:
        try:
            return self._run(confirm, watch, interval)
        finally:
            if self._capture_dir is not None:
                _log("CAPTURED", files=self._capture_count, dir=self._capture_dir)

    def _run(self, confirm: bool, watch: bool, interval: float) -> RunResult:
        failures = 0
        while True:
            try:
                result = self._cycle(confirm)
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

            if watch and result.status in _WATCHABLE_STATUSES:
                # Healthy response: step the backoff back down one notch.
                failures = max(0, failures - 1)
                delay = interval if failures == 0 else retry_delay(None, failures, interval, self._now())
                self._sleep(delay)
                continue

            return result  # terminal even with watch: any other status (incl. "prepared").

    def _cycle(self, confirm: bool) -> RunResult | object:
        """One attempt, reconstructed at most once on a mid-flow session bounce
        (contracts.md: no more than one reconstruction per attempt before the
        transient outcome is handed back to the poller).
        """
        result = self._attempt(confirm)
        if result is _SESSION_EXPIRED:
            result = self._attempt(confirm)
        return result

    def _attempt(self, confirm: bool) -> RunResult | object:
        # SPEC §18: one session, reused across cycles -- log in only when the
        # session isn't already authenticated. Every cycle still re-navigates
        # from a fresh render either way (nothing here is cached or replayed).
        if self._session.authenticated:
            response = self._session.get(PORTAL_URL)
        else:
            response = self._session.login()
            _log("AUTHENTICATED")
        self._capture("portal", response.text)
        if self._login_form(response.text):
            return _SESSION_EXPIRED
        opened = self._open(response.text, str(response.url))
        if opened is _SESSION_EXPIRED:
            return _SESSION_EXPIRED
        if isinstance(opened, RunResult):
            return opened
        _log("SEARCHING", **{"component": COMPONENT_CODE, "class": CLASS_LABEL})
        response = self._follow(self._session.post(opened))
        self._capture("search-result", response.text)
        classified = self._classify_search(response.text, str(response.url))
        if not isinstance(classified, ExtraordinaryClass):
            return classified  # RunResult (terminal/watchable) or _SESSION_EXPIRED

        prepared = self._prepare(classified, response.text, str(response.url))
        if not isinstance(prepared, _PreparedConfirmation):
            return prepared  # RunResult or _SESSION_EXPIRED

        if not confirm:
            return RunResult("prepared", _PREPARED_MESSAGE, 0)
        _log("CONFIRMING")
        return self._confirm(prepared)

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
        if self._login_form(response.text):
            # A watch loop can hold this session open for hours; the classic
            # login form reappearing here means it died, not that the period
            # is closed (SPEC §17 "busca: sim, reconstruída").
            return _SESSION_EXPIRED
        if is_period_closed(response.text, str(response.url)):
            _log("PERIOD_CLOSED")
            return RunResult("period_closed", _PERIOD_CLOSED_MESSAGE, 2)
        _log("FATAL_ERROR", reason="no_search_form")
        return RunResult("error", _NO_SEARCH_FORM_MESSAGE, 6)

    def _classify_search(self, html: str, url: str) -> RunResult | ExtraordinaryClass | object:
        if self._login_form(html):
            return _SESSION_EXPIRED
        if is_period_closed(html, url):
            _log("PERIOD_CLOSED")
            return RunResult("period_closed", _PERIOD_CLOSED_MESSAGE, 2)
        try:
            rows = parse_classes(html)
        except ValueError:
            # Live capture 2026-09-16: a well-formed search with no results
            # table is a *recognized* SIGAA answer, not an unmodeled render --
            # `classify_message` (panel-scoped, per its own docstring) tells
            # the two apart before falling back to the generic "unrecognized
            # DOM" diagnostic. "sem vaga" (no remaining vacancies) is a real
            # academic state, watchable; the two payload-validation messages
            # mean OUR request was malformed, a protocol bug that a --watch
            # retry can never fix, so it fails fast instead.
            category = classify_message(html)
            if category == "sem vaga":
                _log("TARGET_UNAVAILABLE", reason="no_vacancy")
                return RunResult("no_vacancy", _NO_VACANCY_MESSAGE, 2)
            if category == "parâmetros de busca inválidos":
                _log("FATAL_ERROR", reason="search_payload_invalid")
                return RunResult("error", _SEARCH_PAYLOAD_INVALID_MESSAGE, 6)
            _log("FATAL_ERROR", reason="results_capture_needed")
            return RunResult("error", _RESULTS_CAPTURE_MESSAGE, 6)
        try:
            target = select_target(rows)
        except AmbiguousSelectionError:
            _log("FATAL_ERROR", reason="ambiguous_target")
            return RunResult("error", _AMBIGUOUS_TARGET_MESSAGE, 6)
        if target is None:
            _log("TARGET_UNAVAILABLE", reason="target_not_found")
            return RunResult("target_not_found", _TARGET_NOT_FOUND_MESSAGE, 2)
        if not _is_available(target):
            _log("TARGET_UNAVAILABLE", reason="no_vacancy")
            return RunResult("no_vacancy", _NO_VACANCY_MESSAGE, 2)
        _log("TARGET_FOUND", vacancies=target.vacancies)
        return target

    def _prepare(
        self, target: ExtraordinaryClass, results_html: str, results_url: str
    ) -> RunResult | _PreparedConfirmation | object:
        """SPEC §14: reach the confirmation form, validate it, never send it here."""
        _log("PREPARING")
        try:
            select_form = selection_action(results_html, results_url, target)
        except ValueError:
            _log("FATAL_ERROR", reason="selection_form_unrecognized")
            return RunResult("error", _SELECTION_UNRECOGNIZED_MESSAGE, 6)
        response = self._follow(self._session.post(select_form))
        self._capture("confirmation", response.text)
        if self._login_form(response.text):
            return _SESSION_EXPIRED
        if not _confirmation_matches_target(response.text, target):
            _log("FATAL_ERROR", reason="confirmation_target_mismatch")
            return RunResult("error", _CONFIRMATION_MISMATCH_MESSAGE, 6)
        try:
            action = confirmation_action(response.text, str(response.url))
            identity_names = confirmation_identity_fields(response.text)
        except ValueError:
            _log("FATAL_ERROR", reason="confirmation_form_unrecognized")
            return RunResult("error", _CONFIRMATION_UNRECOGNIZED_MESSAGE, 6)
        _log("PREPARED")
        return _PreparedConfirmation(action=action, target=target, identity_names=identity_names)

    def _confirm(self, prepared: _PreparedConfirmation) -> RunResult:
        """SPEC §15: resolve secrets, send exactly once, then only verify."""
        try:
            secret_values = {kind: self._confirmation_secret(kind) for kind in prepared.identity_names}
        except UFCGError as exc:
            _log("FATAL_ERROR", reason="confirmation_secret_unavailable")
            return RunResult("error", str(exc), 5)

        name_to_kind = {name: kind for kind, name in prepared.identity_names.items()}
        filled_fields = tuple(
            (name, secret_values[name_to_kind[name]]) if name in name_to_kind else (name, value)
            for name, value in prepared.action.fields
        )
        action = FormAction(prepared.action.action, filled_fields)

        if prepared.sent:
            raise AssertionError("confirmation already sent for this prepared attempt")
        prepared.sent = True  # set before the I/O; no exception may reopen this confirmation
        try:
            response = self._session.post(action)
        except UFCGError:
            response = None
        # from here: only the verification query and its own recovery -- a
        # 30x, a timeout or an unexpected status all fall through the same way.

        confirmation_ok = response is not None and 200 <= response.status_code < 300
        if confirmation_ok:
            self._capture("confirmation-result", response.text)

        # Round-2 review fix: verification runs BEFORE any rejection is
        # trusted. `classify_message` only reads SIGAA's own message panels
        # (round-1 fix), but a genuine panel on a post-confirmation render
        # can still legitimately mention e.g. "sem vaga" for an unrelated
        # turma while THIS confirmation actually succeeded -- and reporting
        # a false "rejected" invites a human to re-run with --confirm, i.e.
        # exactly the double-send this whole design exists to prevent. A
        # proven bond always wins over any message-based classification.
        result = self._verify(prepared.target)
        category = classify_message(response.text) if confirmation_ok else None

        if result.status == "enrolled":
            if category == "já matriculado":
                # A message alone is never enough (contracts.md); this is the
                # same independent proof that also grants plain "enrolled".
                return RunResult("already_enrolled", result.message, 0)
            return result

        if category in _TERMINAL_REJECTION_CATEGORIES:
            _log("REJECTED", reason=category)
            return RunResult("rejected", category, 3)

        return result

    def _verify(self, target: ExtraordinaryClass) -> RunResult:
        """SPEC §16: read-only, independent, at most 3 queries with backoff.

        The first query reads the authenticated portal; SPEC §16's second
        read-only candidate (re-open + re-search the extraordinária) is used
        for every query after that, so an inconclusive portal read is never
        just asked again verbatim. A session bounce mid-verification
        re-logins and retries the SAME verification query -- it never
        reconstructs or resends a confirmation.
        """
        del target  # is_enrolled() checks the one fixed product target itself.
        query = 0
        guard = 0
        while query < _MAX_VERIFICATION_QUERIES and guard < _MAX_VERIFICATION_QUERIES + 3:
            guard += 1
            outcome = self._verify_via_portal() if query == 0 else self._verify_via_search()
            if outcome is _SESSION_EXPIRED:
                try:
                    self._session.login()
                except UFCGError:
                    pass
                continue  # retry the same verification query, no query consumed
            query += 1
            _log("VERIFYING", attempt=query)
            if outcome:
                _log("ENROLLED")
                return RunResult("enrolled", _ENROLLED_MESSAGE, 0)
            if query < _MAX_VERIFICATION_QUERIES:
                self._sleep(_VERIFICATION_BACKOFF[min(query - 1, len(_VERIFICATION_BACKOFF) - 1)])
        _log("UNKNOWN")
        return RunResult("unknown", _UNKNOWN_MESSAGE, 4)

    def _verify_via_portal(self) -> bool | object:
        """SPEC §16 candidate 1: the authenticated portal listing."""
        try:
            response = self._session.get(PORTAL_URL)
        except UFCGError:
            return False  # transient: this query is inconclusive, not proof either way
        if self._login_form(response.text):
            return _SESSION_EXPIRED
        self._capture("verification", response.text)
        return is_enrolled(response.text)

    def _verify_via_search(self) -> bool | object:
        """SPEC §16 candidate 2: re-open the extraordinária and re-search the
        component, read-only, reusing the same `_open` the main flow uses.
        """
        try:
            portal_response = self._session.get(PORTAL_URL)
        except UFCGError:
            return False
        if self._login_form(portal_response.text):
            return _SESSION_EXPIRED
        opened = self._open(portal_response.text, str(portal_response.url))
        if opened is _SESSION_EXPIRED:
            return _SESSION_EXPIRED
        if not isinstance(opened, FormAction):
            return False  # period closed / no search form here: inconclusive, not proof
        try:
            response = self._follow(self._session.post(opened))
        except UFCGError:
            return False
        self._capture("verification", response.text)
        return is_enrolled(response.text)

    def _login_form(self, html: str) -> bool:
        """Detect the classic login form re-rendered where a real page was
        expected. Every call site that can observe this (OPEN, SEARCH,
        PREPARE, both verification queries) routes through here so the
        session is marked unauthenticated the moment it's caught anywhere,
        not just at the top of `_attempt`.
        """
        expired = _is_login_form_render(html)
        if expired:
            self._session.authenticated = False
        return expired

    def _capture(self, label: str, html: str) -> None:
        """Diagnostic-only (SPEC §20): never changes a request or a classification.

        A write failure (e.g. an exhausted/reused directory) degrades to a
        logged warning; it never aborts the run.
        """
        if self._capture_dir is None:
            return
        self._capture_count += 1
        path = self._capture_dir / f"{self._capture_count:04d}-{label}.html"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fchmod(fd, 0o600)  # belt-and-suspenders against a permissive umask
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(html)
        except OSError as exc:
            _log("CAPTURE_WARNING", file=path.name, reason=type(exc).__name__)

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


def _is_available(target: ExtraordinaryClass) -> bool:
    """SPEC §13: available on an explicit positive vacancy, or -- when vacancy
    is unknown -- a selection control the parser recognized as enabled. Never
    on an explicit zero.
    """
    if target.vacancies is not None:
        return target.vacancies > 0
    return bool(target.selection_fields)


def _confirmation_matches_target(html: str, target: ExtraordinaryClass) -> bool:
    """SPEC §15 item 3: re-verify component + turma on the confirmation page
    itself, textually (its exact DOM shape is unconfirmed by a real capture).
    """
    normalized = " ".join(html.split())
    if target.component_code not in normalized:
        return False
    class_pattern = re.compile(rf"turma\s*0*{re.escape(target.class_token)}\b", re.IGNORECASE)
    return class_pattern.search(normalized) is not None


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
    # `max(failures, 1) - 1` guards the (never-legitimate, but not worth
    # crashing on) failures <= 0 case: plain negative indexing would silently
    # wrap around and return the ladder's *last* (120s) entry instead.
    return max(interval, _BACKOFF_LADDER[min(max(failures, 1) - 1, 2)])


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

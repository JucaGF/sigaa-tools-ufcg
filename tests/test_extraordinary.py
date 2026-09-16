"""ExtraordinaryWorker.run: login -> menu/direct endpoint -> search, classified.

MockTransport sequences with explicit response queues, per fixture render.
POST bodies are compared with parse_qsl so field order never matters.
"""

import os
import stat
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest

from sigaa.extraordinary import (
    CLASS_LABEL,
    COMPONENT_CODE,
    ExtraordinaryWorker,
    RunResult,
    _is_available,
    retry_delay,
)
from sigaa.parsers.matricula_extraordinaria import ExtraordinaryClass
from sigaa.ufcg import UFCGSession

FIXTURES = Path(__file__).parent / "fixtures" / "ufcg"

PORTAL_URL = "https://sigaa.ufcg.edu.br/sigaa/portais/discente/discente.jsf"
SEARCH_URL = (
    "https://sigaa.ufcg.edu.br/sigaa/graduacao/matricula/extraordinaria/"
    "matricula_extraordinaria.jsf"
)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _worker(handler, secrets=None, **worker_kwargs) -> tuple[ExtraordinaryWorker, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording_handler), follow_redirects=False)
    session = UFCGSession("jucag", lambda: "s3cr3t", client=client)
    secrets = secrets or {"password": "s3cr3t", "birth_date": "01/01/2000"}
    worker = ExtraordinaryWorker(session, lambda kind: secrets[kind], **worker_kwargs)
    return worker, requests


def _never_sleep(delay: float) -> None:
    raise AssertionError(f"must not poll without --watch (tried to sleep {delay}s)")


def _body(request: httpx.Request) -> dict:
    return dict(parse_qsl(request.content.decode(), keep_blank_values=True))


def _selection_and_confirmation_handler(
    *,
    results_html=None,
    confirmation_html=None,
    confirmation_response=None,
    confirmation_raises=False,
    verification_htmls=None,
):
    """login -> menu -> search -> results -> select -> confirmation page,
    then (optionally) the confirmation POST and verification queries.

    Verification query 1 (`_verify_via_portal`) reads a portal GET directly;
    every query after that (`_verify_via_search`) re-opens (a plain portal
    GET feeding `_open`, always a realistic portal.html with a menu, then a
    menu POST + extraordinária search POST) before its own determination.
    `verification_htmls[i]` is query i's determination content regardless of
    which transport it travels over -- callers don't need to know the
    mechanism. This handler assumes no login-form bounce mid-verification
    (see the dedicated bespoke handler for that scenario).
    """
    extraordinaria_posts = {"n": 0}
    portal_gets = {"n": 0}
    state = {"confirmation_posts": 0}
    verify_query = {"i": 0}

    def _next_verification_content() -> str:
        i = verify_query["i"]
        verify_query["i"] += 1
        if verification_htmls is not None and i < len(verification_htmls):
            return verification_htmls[i]
        return _fixture("enrolled.html")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            portal_gets["n"] += 1
            if portal_gets["n"] == 1:
                return httpx.Response(200, text=_fixture("portal.html"))
            if portal_gets["n"] == 2:
                return httpx.Response(200, text=_next_verification_content())  # verify query 1
            return httpx.Response(200, text=_fixture("portal.html"))  # feeding _open for query 2+
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            extraordinaria_posts["n"] += 1
            n = extraordinaria_posts["n"]
            if n == 1:
                return httpx.Response(200, text=results_html or _fixture("results.html"))
            if n == 2:
                return httpx.Response(200, text=confirmation_html or _fixture("confirmation.html"))
            if n == 3:
                state["confirmation_posts"] += 1
                if confirmation_raises:
                    raise httpx.ReadTimeout("synthetic timeout", request=request)
                if confirmation_response is not None:
                    return confirmation_response
                return httpx.Response(200, text=_fixture("enrolled.html"))
            return httpx.Response(200, text=_next_verification_content())  # verify query 2+
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler, state


# --- happy-path plumbing: login -> menu -> search, unknown results DOM -------


def test_run_reaches_search_via_the_menu_postback_and_reports_capture_needed():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do") and request.method == "POST":
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            # menu postback: JSF re-renders the search form in place, 200 direct
            assert _body(request)["jscook_action"] == (
                "menu_form_menu_discente_discente_menu:A]#{ matriculaExtraordinaria.iniciar}"
            )
            return httpx.Response(200, text=_fixture("search.html"))
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "POST":
            body = _body(request)
            assert body["form:checkCodigo"] == "checked"
            assert body["form:txtCodigo"] == COMPONENT_CODE
            assert body["javax.faces.ViewState"] == "render-fake-0002"
            return httpx.Response(
                200,
                text="<html><body><div id='resultados'>unmodeled</div></body></html>",
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result == RunResult("error", "captura de resultados necessária", 6)
    # exactly login GET, login POST, portal GET, menu POST, search POST -- no
    # further POST (confirm) is ever sent.
    paths = [(r.method, r.url.path.split(";")[0]) for r in requests]
    assert paths == [
        ("GET", "/sigaa/verTelaLogin.do"),
        ("POST", "/sigaa/logar.do"),
        ("GET", "/sigaa/portais/discente/discente.jsf"),
        ("POST", "/sigaa/portais/discente/discente.jsf"),
        ("POST", "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf"),
    ]
    assert sum(1 for r in requests if r.method == "POST") == 3


def test_run_ignores_confirm_flag_in_this_phase_no_extra_post_is_sent():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/"):
            return httpx.Response(200, text="<html><body>unmodeled</body></html>")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run(confirm=True)

    assert result.status == "error"
    assert sum(1 for r in requests if r.method == "POST") == 3


# --- menu absent or ambiguous: fall back to the direct endpoint --------------


def test_run_falls_back_to_direct_endpoint_when_menu_is_absent():
    # Needs the SAIR/logout marker so login() itself recognizes this as the
    # authenticated portal; it's simply missing the menu form.
    portal_without_menu = (
        '<html><body><a href="/sigaa/logar.do?dispatch=logOff">SAIR</a>'
        "<p>no menu here</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=portal_without_menu)
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("search.html"))
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "POST":
            return httpx.Response(200, text="<html><body>unmodeled</body></html>")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result.status == "error"
    paths = [(r.method, r.url.path.split(";")[0]) for r in requests]
    assert paths == [
        ("GET", "/sigaa/verTelaLogin.do"),
        ("POST", "/sigaa/logar.do"),
        ("GET", "/sigaa/portais/discente/discente.jsf"),
        ("GET", "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf"),
        ("POST", "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf"),
    ]
    # no menu POST ever happened
    assert not any(r.method == "POST" and r.url.path.split(";")[0].startswith("/sigaa/portais") for r in requests)


def test_run_falls_back_to_direct_endpoint_when_menu_reports_period_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result == RunResult("period_closed", "matrícula extraordinária period is not open", 2)
    # never posted the search form (never found one)
    assert not any(
        r.method == "POST"
        and r.url.path.split(";")[0] == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf"
        for r in requests
    )


def test_run_reports_error_when_no_search_form_and_no_period_closed_signal():
    # Needs the SAIR/logout marker so login() recognizes the portal; reused
    # verbatim as the direct-endpoint fallback body too (its URL alone rules
    # out the portal-bounce and lost-form-outside-flow signals there).
    unrecognized = (
        '<html><body><a href="/sigaa/logar.do?dispatch=logOff">SAIR</a>'
        "<p>unexpected maintenance page</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=unrecognized)
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            return httpx.Response(200, text=unrecognized)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result.status == "error"
    assert result.exit_code == 6
    assert result.message != "captura de resultados necessária"  # distinct: open-phase, not search-phase


# --- search classification ----------------------------------------------


def test_run_classifies_bounce_to_portal_as_period_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            # searching before the window opened redirects back to the portal
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result.status == "period_closed"
    assert result.exit_code == 2


def test_run_classifies_explicit_period_message_in_search_response_as_period_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result.status == "period_closed"


# --- session expired: one reconstruction, then terminal ----------------------


def test_run_reconstructs_once_after_a_login_form_bounce_then_succeeds():
    login_renders = iter(["SESSIONONE0001", "SESSIONTWO0002"])
    search_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            html = _fixture("login.html").replace("FAKEJSESSION0001", next(login_renders))
            return httpx.Response(200, text=html)
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            search_calls["n"] += 1
            if search_calls["n"] == 1:
                # first attempt: SIGAA says the session is gone
                return httpx.Response(200, text=_fixture("login.html"))
            return httpx.Response(200, text="<html><body>unmodeled results</body></html>")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result.status == "error"  # second attempt reached the unmodeled-results classification
    assert result.message == "captura de resultados necessária"
    login_posts = [r for r in requests if r.url.path.split(";")[0].startswith("/sigaa/logar.do")]
    assert len(login_posts) == 2  # re-navigated: a fresh login POST each attempt
    assert search_calls["n"] == 2


def test_run_returns_session_expired_after_two_login_form_bounces():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text=_fixture("login.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result == RunResult(
        "session_expired", "SIGAA session expired; the retry also expired", 7
    )
    login_gets = [r for r in requests if r.url.path.split(";")[0] == "/sigaa/verTelaLogin.do"]
    assert len(login_gets) == 2  # exactly one reconstruction, no unbounded retry


def test_open_phase_login_form_bounce_is_session_expired_not_a_misclassified_period_closed():
    # Regression: a render carrying the classic loginForm marker during the
    # OPEN phase (no menu, direct-endpoint GET) used to be misread as
    # `period_closed` because `is_period_closed`'s third signal (no search
    # form, URL still on the extraordinária path -> False) never got a
    # chance: the login-form check must run first. This matters once --watch
    # keeps a session alive for hours.
    portal_without_menu = (
        '<html><body><a href="/sigaa/logar.do?dispatch=logOff">SAIR</a>'
        "<p>no menu here</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=portal_without_menu)
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            # the direct endpoint bounces back to the classic login form
            return httpx.Response(200, text=_fixture("login.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()

    assert result.status == "session_expired"
    assert result.exit_code == 7
    assert result.message == "SIGAA session expired; the retry also expired"  # generalized wording, not "during search"
    login_gets = [r for r in requests if r.url.path.split(";")[0] == "/sigaa/verTelaLogin.do"]
    assert len(login_gets) == 2  # exactly one reconstruction, no unbounded retry


# --- ViewState freshness --------------------------------------------------


def test_search_post_uses_the_viewstate_of_the_render_it_followed_not_a_stale_one():
    seen_viewstates = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            seen_viewstates.append(_body(request).get("javax.faces.ViewState"))
            # menu form's own ViewState (render-fake-0001) must never reappear
            # downstream; the search render carries a different one.
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            seen_viewstates.append(_body(request).get("javax.faces.ViewState"))
            return httpx.Response(200, text="<html><body>unmodeled</body></html>")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    worker.run()

    assert seen_viewstates == ["render-fake-0001", "render-fake-0002"]
    assert len(set(seen_viewstates)) == len(seen_viewstates)  # never reused


# --- UFCGError propagation: typed outcome, not a crash -----------------------


def test_run_maps_auth_error_to_exit_code_five():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_fixture("login.html"))  # loginForm re-rendered: rejected

    worker, _ = _worker(handler)
    result = worker.run()

    assert result.status == "error"
    assert result.exit_code == 5
    assert "s3cr3t" not in result.message


def test_run_maps_network_error_to_exit_code_seven():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    worker, _ = _worker(handler, sleep=_never_sleep)
    result = worker.run()  # watch=False: retry exhaustion is immediate, no polling

    assert result.status == "error"
    assert result.exit_code == 7


def test_run_does_not_crash_when_menu_form_has_no_viewstate():
    # A malformed menu render (form + target string present, ViewState
    # missing) must not surface a bare ValueError to the caller.
    broken_portal = _fixture("portal.html").replace(
        '<input type="hidden" name="javax.faces.ViewState" value="render-fake-0001">', ""
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=broken_portal)
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler)
    result = worker.run()  # must not raise

    assert result.status == "period_closed"
    # fell straight back to the direct endpoint, no crash, no menu POST
    assert not any(
        r.method == "POST" and r.url.path.split(";")[0] == "/sigaa/portais/discente/discente.jsf"
        for r in requests
    )


# --- secrets never leak ---------------------------------------------------


def test_run_never_leaks_the_password_in_the_result():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text="<html><body>unmodeled</body></html>")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, _ = _worker(handler, secrets={"password": "S3ntinelPW", "birth_date": "S3ntinelBD"})
    result = worker.run()

    assert "S3ntinelPW" not in result.message
    assert "S3ntinelPW" not in repr(result)
    assert CLASS_LABEL == "02"


# --- retry_delay: pure function, Retry-After parsing + backoff ladder --------


def test_backoff_and_retry_after_bounds():
    assert [retry_delay(None, n, 20, 0) for n in (1, 2, 3, 4)] == [30, 60, 120, 120]
    assert retry_delay("12", 3, 20, 0) == 12
    assert retry_delay("301", 1, 20, 0) == 30
    assert retry_delay("bad", 1, 20, 0) == 30


def test_retry_delay_parses_a_valid_http_date_within_bounds():
    now = 1700000000.0
    future = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(seconds=12)
    header = format_datetime(future, usegmt=True)
    assert abs(retry_delay(header, 1, 20, now) - 12.0) < 1.5


def test_retry_delay_rejects_an_out_of_range_http_date_and_falls_back_to_backoff():
    now = 1700000000.0
    far_future = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(seconds=301)
    header = format_datetime(far_future, usegmt=True)
    assert retry_delay(header, 1, 20, now) == 30


def test_retry_delay_ceiling_never_lowers_a_larger_configured_interval():
    assert retry_delay(None, 3, 150, 0) == 150


# --- run(watch=True): backoff ladder, healthy recovery, Retry-After, KeyboardInterrupt ---


def test_watch_loops_on_period_closed_at_the_plain_interval():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []

    def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 3:
            raise KeyboardInterrupt

    worker, _ = _worker(handler, sleep=fake_sleep, now=lambda: 0.0)
    with pytest.raises(KeyboardInterrupt):
        worker.run(watch=True, interval=20)

    assert delays == [20, 20, 20]  # healthy every cycle: never escalates, never below interval


def test_watch_backoff_ladder_then_steps_back_down_to_interval_on_recovery():
    login_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            login_calls["n"] += 1
            if login_calls["n"] <= 4:
                return httpx.Response(503)  # transient network error, no Retry-After
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []

    def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 8:
            raise KeyboardInterrupt

    worker, _ = _worker(handler, sleep=fake_sleep, now=lambda: 0.0)
    with pytest.raises(KeyboardInterrupt):
        worker.run(watch=True, interval=20)

    # 4 escalating transient failures, then 4 healthy cycles stepping the
    # backoff back down one notch at a time, never below the interval.
    assert delays == [30, 60, 120, 120, 120, 60, 30, 20]
    # 4 failed pre-auth login attempts + 1 that succeeds; the session is then
    # reused (SPEC §18: one session, no redundant credential POST) for the
    # remaining 3 healthy cycles, so the count stops climbing at 5.
    assert login_calls["n"] == 5


def test_watch_reuses_the_session_and_logs_in_once_across_healthy_cycles():
    login_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            login_calls["n"] += 1
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []

    def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 8:
            raise KeyboardInterrupt

    worker, _ = _worker(handler, sleep=fake_sleep, now=lambda: 0.0)
    with pytest.raises(KeyboardInterrupt):
        worker.run(watch=True, interval=20)

    # 8 healthy cycles, one credential POST: every cycle still re-navigates
    # portal -> menu -> search from a fresh render, it just never re-logs in.
    assert login_calls["n"] == 1


def test_watch_session_bounce_after_reuse_reauthenticates_once_and_continues():
    # Distinct from the OPEN-phase bounce test above: this bounce happens on
    # a cycle that was already relying on session reuse (cycle 2+), proving
    # the authenticated flag flips back correctly mid-watch, not just on the
    # very first cycle.
    login_calls = {"n": 0}
    portal_gets = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            login_calls["n"] += 1
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            portal_gets["n"] += 1
            if portal_gets["n"] == 2:
                # cycle 2's reused-session portal fetch finds the session dead.
                return httpx.Response(200, text=_fixture("login.html"))
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []

    def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 3:
            raise KeyboardInterrupt

    worker, _ = _worker(handler, sleep=fake_sleep, now=lambda: 0.0)
    with pytest.raises(KeyboardInterrupt):
        worker.run(watch=True, interval=20)

    # cycle 1: fresh login. cycle 2: reused GET finds the session dead, the
    # one allowed reconstruction re-logs in and continues -- healthy, no
    # backoff escalation. cycle 3: reused again, no extra login.
    assert login_calls["n"] == 2
    assert delays == [20, 20, 20]  # never escalates: the bounce was recovered within its cycle


def test_watch_search_post_never_replays_a_stale_viewstate_across_reused_cycles():
    # The property most at risk from session reuse: a cached FormAction or
    # ViewState from an earlier cycle must never reappear once the session
    # stops being re-logged-in every cycle.
    cycle = {"n": 0}
    seen_menu_viewstates = []
    seen_search_viewstates = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            cycle["n"] += 1
            portal = _fixture("portal.html").replace("render-fake-0001", f"MENU-{cycle['n']}")
            return httpx.Response(200, text=portal)
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            seen_menu_viewstates.append(_body(request).get("javax.faces.ViewState"))
            search = _fixture("search.html").replace("render-fake-0002", f"SEARCH-{cycle['n']}")
            return httpx.Response(200, text=search)
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            seen_search_viewstates.append(_body(request).get("javax.faces.ViewState"))
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []

    def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 3:
            raise KeyboardInterrupt

    worker, _ = _worker(handler, sleep=fake_sleep, now=lambda: 0.0)
    with pytest.raises(KeyboardInterrupt):
        worker.run(watch=True, interval=20)

    assert seen_menu_viewstates == ["MENU-1", "MENU-2", "MENU-3"]
    assert seen_search_viewstates == ["SEARCH-1", "SEARCH-2", "SEARCH-3"]
    # no earlier cycle's ViewState is ever replayed on a later cycle's POST.
    assert len(set(seen_menu_viewstates)) == 3
    assert len(set(seen_search_viewstates)) == 3


def test_watch_honors_a_valid_retry_after_header_even_below_the_backoff_ladder():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"retry-after": "12"})
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text="<html><body>unmodeled</body></html>")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []
    worker, _ = _worker(handler, sleep=delays.append, now=lambda: 0.0)
    result = worker.run(watch=True, interval=20)

    assert delays == [12]  # Retry-After honored even though it's below `interval`
    assert result == RunResult("error", "captura de resultados necessária", 6)


def test_watch_recovers_from_an_open_phase_session_bounce_with_backoff_then_stops_on_a_terminal_error():
    attempt_n = {"n": 0}
    portal_without_menu = (
        '<html><body><a href="/sigaa/logar.do?dispatch=logOff">SAIR</a>'
        "<p>no menu here</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            attempt_n["n"] += 1
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=portal_without_menu)
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            if attempt_n["n"] <= 2:
                return httpx.Response(200, text=_fixture("login.html"))  # session bounced, twice
            return httpx.Response(200, text=_fixture("search.html"))
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "POST":
            return httpx.Response(200, text="<html><body>unmodeled</body></html>")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []
    worker, _ = _worker(handler, sleep=delays.append, now=lambda: 0.0)
    result = worker.run(watch=True, interval=20)

    assert delays == [30]  # one backoff step after the reconstruction-exhausted cycle
    assert result == RunResult("error", "captura de resultados necessária", 6)
    assert attempt_n["n"] == 3  # 2 bounced attempts (1 cycle) + 1 healthy attempt (next cycle)


# --- --capture: numbered HTML renders, private permissions -------------------


def test_capture_dir_is_private_even_when_its_parent_did_not_exist_yet(tmp_path):
    # Fix (review): mkdir(parents=True, exist_ok=True) + a later chmod left a
    # window where the directory was created at the (umask-clipped) default
    # mode before being tightened. mode=0o700 at creation time closes that
    # window for the leaf directory itself. Directory setup happens in
    # __init__, so no run() is needed to observe it.
    capture_dir = tmp_path / "nested" / "capture"
    assert not capture_dir.parent.exists()

    _worker(lambda request: httpx.Response(200), capture_dir=capture_dir)

    assert stat.S_IMODE(capture_dir.stat().st_mode) == 0o700


def test_capture_dir_pre_existing_with_wrong_permissions_is_tightened(tmp_path):
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir(mode=0o755)
    os.chmod(capture_dir, 0o755)  # mkdir(mode=...) is clipped by umask; force it open first

    _worker(lambda request: httpx.Response(200), capture_dir=capture_dir)

    assert stat.S_IMODE(capture_dir.stat().st_mode) == 0o700


def test_capture_write_failure_degrades_to_a_warning_not_a_crash(tmp_path, capsys):
    # Fix (review): a populated capture dir used to crash the run mid-flow on
    # the second O_EXCL write (per-process counter restarts at 1). The CLI
    # now refuses a non-empty --capture dir up front; the worker itself must
    # also never let one write failure kill the run.
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    (capture_dir / "0001-portal.html").write_text("leftover", encoding="utf-8")  # collides with the first write
    unrecognized = (
        '<html><body><a href="/sigaa/logar.do?dispatch=logOff">SAIR</a>'
        "<p>unexpected maintenance page</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=unrecognized)
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            return httpx.Response(200, text=unrecognized)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, _ = _worker(handler, capture_dir=capture_dir)
    result = worker.run()  # must not raise

    assert result.status == "error"
    assert result.exit_code == 6
    assert "CAPTURE_WARNING" in capsys.readouterr().err


def test_capture_writes_numbered_files_with_private_permissions(tmp_path):
    capture_dir = tmp_path / "capture"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text="<html><body>unmodeled</body></html>")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, _ = _worker(handler, capture_dir=capture_dir)
    result = worker.run()

    assert result.status == "error"
    assert stat.S_IMODE(capture_dir.stat().st_mode) == 0o700
    files = sorted(p.name for p in capture_dir.iterdir())
    assert files == ["0001-portal.html", "0002-search.html", "0003-search-result.html"]
    for name in files:
        mode = stat.S_IMODE((capture_dir / name).stat().st_mode)
        assert mode == 0o600
    assert (capture_dir / "0002-search.html").read_text(encoding="utf-8") == _fixture("search.html")


def test_capture_is_diagnostic_only_and_never_changes_the_result(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        if path == "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("period_closed.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    plain, _ = _worker(handler)
    captured, _ = _worker(handler, capture_dir=tmp_path / "capture")

    assert plain.run() == captured.run()


# =============================================================================
# Part B: select -> prepare -> confirm -> verify (worker level, gated on Task 3
# real evidence being genuinely absent -- see task-34-report.md's assumptions
# section for what a real capture must still confirm about these shapes).
# =============================================================================


# --- dry-run: selects, prepares, never sends the confirmation POST ----------


def test_dry_run_selects_and_prepares_but_never_sends_confirmation():
    handler, state = _selection_and_confirmation_handler()
    worker, requests = _worker(handler)
    result = worker.run()

    assert result.status == "prepared"
    assert result.exit_code == 0
    assert state["confirmation_posts"] == 0
    extraordinaria_posts = [
        r for r in requests
        if r.method == "POST"
        and r.url.path.split(";")[0].startswith("/sigaa/graduacao/matricula/extraordinaria/")
    ]
    assert len(extraordinaria_posts) == 2  # search + selection, never confirmation


def test_prepared_stops_even_under_watch():
    handler, _ = _selection_and_confirmation_handler()
    worker, _ = _worker(handler, sleep=_never_sleep)
    result = worker.run(watch=True, interval=20)
    assert result.status == "prepared"


# --- confirm: exactly one POST, happy path -----------------------------------


def test_confirm_sends_exactly_one_confirmation_post_and_verifies_enrolled():
    handler, state = _selection_and_confirmation_handler()
    worker, _ = _worker(handler)
    result = worker.run(confirm=True)

    assert result.status == "enrolled"
    assert result.exit_code == 0
    assert result.message == "matrícula verificada"
    assert state["confirmation_posts"] == 1


def test_confirm_fields_are_filled_from_secrets_not_stored_on_the_parser_object():
    handler, state = _selection_and_confirmation_handler()
    worker, requests = _worker(handler, secrets={"password": "s3cr3t-pw", "birth_date": "01/02/2003"})
    worker.run(confirm=True)

    confirmation_posts = [
        r for r in requests
        if r.method == "POST"
        and r.url.path.split(";")[0].startswith("/sigaa/graduacao/matricula/extraordinaria/")
    ]
    body = _body(confirmation_posts[2])
    assert body["form:senha"] == "s3cr3t-pw"
    assert body["form:dataNascimento"] == "01/02/2003"


# --- the required scenario: a timeout inside the confirmation POST ----------


def test_confirmation_timeout_goes_straight_to_verification_single_send():
    handler, state = _selection_and_confirmation_handler(
        confirmation_raises=True, verification_htmls=[_fixture("enrolled.html")]
    )
    worker, _ = _worker(handler)
    result = worker.run(confirm=True)

    assert state["confirmation_posts"] == 1
    assert result.status == "enrolled"
    assert result.exit_code == 0


# --- 307/308 after the confirmation POST: no replay, straight to verify -----


def test_redirect_after_confirmation_post_is_not_replayed():
    redirect = httpx.Response(307, headers={"location": "/sigaa/portais/discente/discente.jsf"})
    handler, state = _selection_and_confirmation_handler(
        confirmation_response=redirect, verification_htmls=[_fixture("enrolled.html")]
    )
    worker, requests = _worker(handler)
    result = worker.run(confirm=True)

    assert state["confirmation_posts"] == 1
    assert result.status == "enrolled"
    # never a second POST to the extraordinária endpoint (search + selection + confirmation = 3, no more)
    extraordinaria_posts = [
        r for r in requests
        if r.method == "POST"
        and r.url.path.split(";")[0].startswith("/sigaa/graduacao/matricula/extraordinaria/")
    ]
    assert len(extraordinaria_posts) == 3


# --- explicit academic rejection: terminal, exit 3, never retried -----------


def test_explicit_academic_rejection_is_confirmed_only_after_verification_finds_no_bond():
    # Round-2 review fix: verification now ALWAYS runs after a send, before
    # any rejection is trusted -- a `rejected` result requires both an
    # explicit refusal message AND verification failing to find the bond.
    not_enrolled = "<html><body><a href='/sigaa/logar.do?dispatch=logOff'>SAIR</a><p>nada aqui</p></body></html>"
    rejected = httpx.Response(200, text="<html><body><div class='erro'>Choque de horário com outra turma.</div></body></html>")
    handler, state = _selection_and_confirmation_handler(
        confirmation_response=rejected,
        verification_htmls=[not_enrolled, not_enrolled, not_enrolled],
    )
    worker, requests = _worker(handler, sleep=lambda delay: None)
    result = worker.run(confirm=True, watch=True, interval=20)

    assert result.status == "rejected"
    assert result.exit_code == 3
    assert result.message == "choque de horário"
    portal_gets = [
        r for r in requests
        if r.method == "GET" and r.url.path.split(";")[0] == "/sigaa/portais/discente/discente.jsf"
    ]
    assert len(portal_gets) > 1  # verification DID run before the rejection was trusted


def test_verify_proven_bond_overrides_a_stray_rejection_message():
    # A post-confirmation render can legitimately contain a real SIGAA
    # message panel mentioning e.g. "sem vaga" for an unrelated turma while
    # THIS confirmation actually succeeded. Reporting a false "rejected"
    # would invite a human to re-run with --confirm -- exactly the double
    # send this design exists to prevent. A proven bond always wins.
    stray_rejection = httpx.Response(200, text="<html><body><div class='erro'>Turma 07 sem vaga.</div></body></html>")
    handler, state = _selection_and_confirmation_handler(
        confirmation_response=stray_rejection, verification_htmls=[_fixture("enrolled.html")]
    )
    worker, _ = _worker(handler)
    result = worker.run(confirm=True)

    assert result.status == "enrolled"
    assert result.exit_code == 0
    assert state["confirmation_posts"] == 1


# --- already_enrolled: a message alone is never enough, needs proof ---------


def test_already_matriculado_message_with_verified_bond_is_already_enrolled():
    already = httpx.Response(200, text="<html><body><div class='info'>Você já está matriculado.</div></body></html>")
    handler, state = _selection_and_confirmation_handler(
        confirmation_response=already, verification_htmls=[_fixture("enrolled.html")]
    )
    worker, _ = _worker(handler)
    result = worker.run(confirm=True)

    assert result.status == "already_enrolled"
    assert result.exit_code == 0


def test_already_matriculado_message_without_proof_is_unknown_not_already_enrolled():
    already = httpx.Response(200, text="<html><body><div class='info'>Você já está matriculado.</div></body></html>")
    not_enrolled = "<html><body><a href='/sigaa/logar.do?dispatch=logOff'>SAIR</a><p>nada aqui</p></body></html>"
    handler, state = _selection_and_confirmation_handler(
        confirmation_response=already, verification_htmls=[not_enrolled, not_enrolled, not_enrolled]
    )
    worker, _ = _worker(handler, sleep=lambda delay: None)
    result = worker.run(confirm=True)

    assert result.status == "unknown"
    assert result.exit_code == 4


# --- verification: unavailable after 3 queries -> unknown/4, with backoff ---


def test_verification_inconclusive_after_three_queries_is_unknown_with_backoff():
    not_enrolled = "<html><body><a href='/sigaa/logar.do?dispatch=logOff'>SAIR</a><p>nada aqui</p></body></html>"
    handler, state = _selection_and_confirmation_handler(
        verification_htmls=[not_enrolled, not_enrolled, not_enrolled]
    )
    delays: list[float] = []
    worker, _ = _worker(handler, sleep=delays.append)
    result = worker.run(confirm=True)

    assert result.status == "unknown"
    assert result.exit_code == 4
    assert delays == [10.0, 20.0]  # 2 backoff waits between 3 queries, never a 4th query
    assert state["confirmation_posts"] == 1  # unknown never re-sends the confirmation


def test_verify_falls_back_to_read_only_search_after_first_inconclusive_portal_query():
    # Round-2 review fix #6: the SPEC §16 second candidate (re-open + re-
    # search, read-only) must actually be exercised, not just three identical
    # portal reads. Query 1 (portal) is inconclusive; query 2 (re-search)
    # finds an explicit bond in the search-results render itself.
    search_result_with_bond = (
        "<html><body><table class='formulario'>"
        "<tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>"
        "<tr><td>1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</td><td>02</td><td>MATRICULADO</td><td>2026.2</td></tr>"
        "</table></body></html>"
    )
    extraordinaria_posts = {"n": 0}
    portal_gets = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            portal_gets["n"] += 1
            return httpx.Response(200, text=_fixture("portal.html"))  # never itself shows a bond
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))  # menu postback
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            extraordinaria_posts["n"] += 1
            n = extraordinaria_posts["n"]
            if n == 1:
                return httpx.Response(200, text=_fixture("results.html"))
            if n == 2:
                return httpx.Response(200, text=_fixture("confirmation.html"))
            if n == 3:
                return httpx.Response(200, text="<html><body>processing</body></html>")
            if n == 4:
                return httpx.Response(200, text=search_result_with_bond)  # the re-search verification query
            raise AssertionError("unexpected extra POST to the extraordinária endpoint")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler, sleep=lambda delay: None)  # one real backoff wait between the 2 queries
    result = worker.run(confirm=True)

    assert result.status == "enrolled"
    assert extraordinaria_posts["n"] == 4  # search + selection + confirmation + the re-search verification query
    assert portal_gets["n"] == 3  # 1 login-time + 1 verify-via-portal (query 1, inconclusive) + 1 to feed _open


# --- a session bounce during verification: relogin, retry the SAME query ---


def test_session_bounce_during_verification_relogins_and_retries_only_verification():
    # A dedicated, fully explicit handler (not the shared helper): this
    # scenario needs precise control over which of the several portal GETs
    # in play (login's own redirect-follow, verify query 1's own GET, the
    # relogin's redirect-follow, and verify query 1's retry) returns what.
    portal_gets = {"n": 0}
    extraordinaria_posts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            portal_gets["n"] += 1
            n = portal_gets["n"]
            if n == 1:
                return httpx.Response(200, text=_fixture("portal.html"))  # login()'s own redirect-follow
            if n == 2:
                return httpx.Response(200, text=_fixture("login.html"))  # verify query 1, attempt 1: bounced
            if n == 3:
                return httpx.Response(200, text=_fixture("portal.html"))  # relogin()'s own redirect-follow
            return httpx.Response(200, text=_fixture("enrolled.html"))  # verify query 1, attempt 2: proven bond
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            extraordinaria_posts["n"] += 1
            n = extraordinaria_posts["n"]
            if n == 1:
                return httpx.Response(200, text=_fixture("results.html"))
            if n == 2:
                return httpx.Response(200, text=_fixture("confirmation.html"))
            if n == 3:
                return httpx.Response(200, text="<html><body>processing</body></html>")
            raise AssertionError("unexpected extra POST to the extraordinária endpoint")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    worker, requests = _worker(handler, sleep=_never_sleep)  # a clean bounce-retry never sleeps
    result = worker.run(confirm=True)

    assert result.status == "enrolled"
    assert extraordinaria_posts["n"] == 3  # search + selection + confirmation -- the bounce never re-sends confirmation
    login_gets = [r for r in requests if r.url.path.split(";")[0] == "/sigaa/verTelaLogin.do"]
    assert len(login_gets) == 2  # the initial login + exactly one relogin during verification


# --- MATRICULADO for a different turma is not proof of enrollment ----------


def test_verification_matriculado_in_a_different_turma_is_not_enrolled():
    other_turma = (
        "<html><body><a href='/sigaa/logar.do?dispatch=logOff'>SAIR</a>"
        "<table class='formulario'><tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>"
        "<tr><td>1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</td><td>01</td><td>MATRICULADO</td><td>2026.2</td></tr>"
        "</table></body></html>"
    )
    handler, state = _selection_and_confirmation_handler(
        verification_htmls=[other_turma, other_turma, other_turma]
    )
    worker, _ = _worker(handler, sleep=lambda delay: None)
    result = worker.run(confirm=True)

    assert result.status == "unknown"


# --- a consumed preparation cannot be confirmed twice ------------------------


def test_prepared_confirmation_cannot_be_sent_twice():
    handler, state = _selection_and_confirmation_handler()
    worker, requests = _worker(handler)

    login_response = worker._session.login()
    opened = worker._open(login_response.text, str(login_response.url))
    search_response = worker._follow(worker._session.post(opened))
    classified = worker._classify_search(search_response.text, str(search_response.url))
    prepared = worker._prepare(classified, search_response.text, str(search_response.url))

    worker._confirm(prepared)
    assert state["confirmation_posts"] == 1
    requests_before_second_call = len(requests)
    with pytest.raises(AssertionError, match="already sent"):
        worker._confirm(prepared)
    # the guard fires before any second I/O: no new HTTP request at all, not
    # even one the transport itself would have rejected.
    assert len(requests) == requests_before_second_call


# --- missing/unresolvable confirmation secret: exit 5, BEFORE sending -------


def test_confirm_fails_with_exit_five_before_sending_when_secret_unresolvable():
    from sigaa.ufcg import UFCGError as _UFCGError

    handler, state = _selection_and_confirmation_handler()
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording_handler), follow_redirects=False)
    session = UFCGSession("jucag", lambda: "s3cr3t", client=client)

    def missing_secret(kind: str) -> str:
        raise _UFCGError(f"UFCG {kind} not configured", category="auth")

    worker = ExtraordinaryWorker(session, missing_secret)
    result = worker.run(confirm=True)

    assert result.status == "error"
    assert result.exit_code == 5
    assert state["confirmation_posts"] == 0


# --- missing/incorrect confirmation form data: fail closed -------------------


def test_prepare_fails_closed_when_confirmation_form_has_no_password_field():
    broken = (
        "<html><body>1109103 Turma 02 <form name='form'>"
        "<input type='hidden' name='javax.faces.ViewState' value='x'></form></body></html>"
    )
    handler, _ = _selection_and_confirmation_handler(confirmation_html=broken)
    worker, _ = _worker(handler)
    result = worker.run()

    assert result.status == "error"
    assert result.exit_code == 6


def test_prepare_fails_closed_when_confirmation_page_does_not_match_target():
    mismatched = _fixture("confirmation.html").replace("1109103", "9999999")
    handler, _ = _selection_and_confirmation_handler(confirmation_html=mismatched)
    worker, _ = _worker(handler)
    result = worker.run()

    assert result.status == "error"
    assert result.exit_code == 6


# --- ambiguous results rows: fail closed, no fallback -----------------------


def test_worker_ambiguous_target_rows_is_a_fatal_error():
    ambiguous = """
    <table class="formulario">
      <tr><th colspan="2">1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I (DISCIPLINA)</th></tr>
      <tr><th>Turma</th><th>Vagas</th></tr>
      <tr><td>Turma 02</td><td>1 vaga</td><td><input type="submit" name="form:sel1" value="Selecionar"></td></tr>
      <tr><td>Turma 02</td><td>1 vaga</td><td><input type="submit" name="form:sel2" value="Selecionar"></td></tr>
    </table>
    """
    handler, _ = _selection_and_confirmation_handler(results_html=ambiguous)
    worker, _ = _worker(handler)
    result = worker.run()

    assert result.status == "error"
    assert result.exit_code == 6


# --- _is_available: unknown vacancy but a trustworthy enabled control -------


def test_is_available_true_on_unknown_vacancy_with_an_enabled_control():
    row = ExtraordinaryClass(
        component_code="1109103", class_token="2", class_label="Turma 02",
        vacancies=None, schedule_raw=None, room=None, selection_fields=(("a", "b"),),
    )
    assert _is_available(row) is True


def test_is_available_false_on_unknown_vacancy_without_any_control():
    row = ExtraordinaryClass(
        component_code="1109103", class_token="2", class_label="Turma 02",
        vacancies=None, schedule_raw=None, room=None, selection_fields=(),
    )
    assert _is_available(row) is False


def test_is_available_false_on_explicit_zero_even_with_a_stray_control():
    row = ExtraordinaryClass(
        component_code="1109103", class_token="2", class_label="Turma 02",
        vacancies=0, schedule_raw=None, room=None, selection_fields=(("a", "b"),),
    )
    assert _is_available(row) is False


# --- no_vacancy / target_not_found: watchable, unlike prepared/rejected -----


def test_watch_polls_on_no_vacancy():
    no_vacancy = """
    <table class="formulario">
      <tr><th colspan="4">1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I (DISCIPLINA)</th></tr>
      <tr><th>Turma</th><th>Horário</th><th>Vagas</th><th>Local</th></tr>
      <tr><td>Turma 02</td><td>246810N34</td><td>0 vaga</td><td>CAA-202</td></tr>
    </table>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text=no_vacancy)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []

    def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 2:
            raise KeyboardInterrupt

    worker, _ = _worker(handler, sleep=fake_sleep, now=lambda: 0.0)
    with pytest.raises(KeyboardInterrupt):
        worker.run(watch=True, interval=20)

    assert delays == [20, 20]


def test_watch_polls_on_target_not_found():
    absent = """
    <table class="formulario">
      <tr><th colspan="4">1108021 - PROGRAMAÇÃO I (DISCIPLINA)</th></tr>
      <tr><th>Turma</th><th>Horário</th><th>Vagas</th><th>Local</th></tr>
      <tr><td>Turma 01</td><td>246810N12</td><td>5 vagas</td><td>CAA-100</td></tr>
    </table>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(";")[0]
        if path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        if path.startswith("/sigaa/logar.do"):
            return httpx.Response(302, headers={"location": "/sigaa/portais/discente/discente.jsf"})
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "GET":
            return httpx.Response(200, text=_fixture("portal.html"))
        if path == "/sigaa/portais/discente/discente.jsf" and request.method == "POST":
            return httpx.Response(200, text=_fixture("search.html"))
        if path.startswith("/sigaa/graduacao/matricula/extraordinaria/") and request.method == "POST":
            return httpx.Response(200, text=absent)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    delays: list[float] = []

    def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 1:
            raise KeyboardInterrupt

    worker, _ = _worker(handler, sleep=fake_sleep, now=lambda: 0.0)
    with pytest.raises(KeyboardInterrupt):
        worker.run(watch=True, interval=20)

    assert delays == [20]


# --- capture also records results / confirmation / verification renders ----


def test_capture_records_results_confirmation_and_verification(tmp_path):
    handler, _ = _selection_and_confirmation_handler()
    capture_dir = tmp_path / "capture"
    worker, _ = _worker(handler, capture_dir=capture_dir)
    worker.run(confirm=True)

    files = sorted(p.name for p in capture_dir.iterdir())
    assert any("search-result" in f for f in files)
    assert any(f.endswith("-confirmation.html") for f in files)
    assert any("confirmation-result" in f for f in files)
    assert any("verification" in f for f in files)


# --- secrets never leak anywhere in the confirm path -------------------------


def test_confirm_path_never_leaks_secrets(capsys):
    handler, _ = _selection_and_confirmation_handler()
    worker, _ = _worker(handler, secrets={"password": "S3ntinelPW", "birth_date": "S3ntinelBD"})
    result = worker.run(confirm=True)

    err = capsys.readouterr().err
    assert "S3ntinelPW" not in err
    assert "S3ntinelBD" not in err
    assert "S3ntinelPW" not in result.message
    assert "S3ntinelPW" not in repr(result)
    assert "S3ntinelBD" not in result.message

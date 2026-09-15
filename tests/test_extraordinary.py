"""ExtraordinaryWorker.run: login -> menu/direct endpoint -> search, classified.

MockTransport sequences with explicit response queues, per fixture render.
POST bodies are compared with parse_qsl so field order never matters.
"""

import stat
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest

from sigaa.extraordinary import CLASS_LABEL, COMPONENT_CODE, ExtraordinaryWorker, RunResult, retry_delay
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
        "session_expired", "SIGAA session expired during search; the retry also expired", 7
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
    assert login_calls["n"] == 8  # same session, fresh login/ViewState every cycle


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
    assert files == ["01-portal.html", "02-search.html", "03-search-result.html"]
    for name in files:
        mode = stat.S_IMODE((capture_dir / name).stat().st_mode)
        assert mode == 0o600
    assert (capture_dir / "02-search.html").read_text(encoding="utf-8") == _fixture("search.html")


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

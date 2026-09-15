"""ExtraordinaryWorker.run: login -> menu/direct endpoint -> search, classified.

MockTransport sequences with explicit response queues, per fixture render.
POST bodies are compared with parse_qsl so field order never matters.
"""

from pathlib import Path
from urllib.parse import parse_qsl

import httpx

from sigaa.extraordinary import CLASS_LABEL, COMPONENT_CODE, ExtraordinaryWorker, RunResult
from sigaa.ufcg import UFCGSession

FIXTURES = Path(__file__).parent / "fixtures" / "ufcg"

PORTAL_URL = "https://sigaa.ufcg.edu.br/sigaa/portais/discente/discente.jsf"
SEARCH_URL = (
    "https://sigaa.ufcg.edu.br/sigaa/graduacao/matricula/extraordinaria/"
    "matricula_extraordinaria.jsf"
)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _worker(handler, secrets=None) -> tuple[ExtraordinaryWorker, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording_handler), follow_redirects=False)
    session = UFCGSession("jucag", lambda: "s3cr3t", client=client)
    secrets = secrets or {"password": "s3cr3t", "birth_date": "01/01/2000"}
    worker = ExtraordinaryWorker(session, lambda kind: secrets[kind])
    return worker, requests


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

    assert result == RunResult("session_expired", worker_message(result), 7)
    login_gets = [r for r in requests if r.url.path.split(";")[0] == "/sigaa/verTelaLogin.do"]
    assert len(login_gets) == 2  # exactly one reconstruction, no unbounded retry


def worker_message(result: RunResult) -> str:
    return result.message


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

    worker, _ = _worker(handler)
    result = worker.run()

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

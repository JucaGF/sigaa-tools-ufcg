from pathlib import Path

import httpx
import pytest

from sigaa.parsers.matricula_extraordinaria import FormAction
from sigaa.ufcg import HOST, LOGIN_URL, PORTAL_URL, UFCGError, UFCGSession

FIXTURES = Path(__file__).parent / "fixtures" / "ufcg"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _session(handler, username="jucag", password=lambda: "s3cr3t") -> UFCGSession:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return UFCGSession(username, password, client=client)


# --- login: cookie/session continuity, current action/fields -----------------


def test_login_cookie_set_at_login_reaches_the_portal_request():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/sigaa/verTelaLogin.do":
            return httpx.Response(
                200,
                text=_fixture("login.html"),
                headers={"set-cookie": "JSESSIONID=abc123; Path=/"},
            )
        if request.url.path.startswith("/sigaa/logar.do") and request.method == "POST":
            assert request.headers.get("cookie") == "JSESSIONID=abc123"
            body = request.content.decode()
            assert "user.login=jucag" in body
            assert "user.senha=s3cr3t" in body
            return httpx.Response(
                302, headers={"location": "/sigaa/portais/discente/discente.jsf"}
            )
        if request.url.path == "/sigaa/portais/discente/discente.jsf":
            assert request.headers.get("cookie") == "JSESSIONID=abc123"
            return httpx.Response(200, text=_fixture("portal.html"))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    session = _session(handler)
    response = session.login()
    assert str(response.url) == PORTAL_URL
    assert [r.url.path.split(";")[0] for r in requests] == [
        "/sigaa/verTelaLogin.do",
        "/sigaa/logar.do",
        "/sigaa/portais/discente/discente.jsf",
    ]


def test_login_uses_the_action_of_the_current_render():
    login_html = _fixture("login.html").replace(
        "jsessionid=FAKEJSESSION0001", "jsessionid=LIVESESSION7777"
    )
    posted_to = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=login_html)
        if request.method == "POST":
            posted_to.append(str(request.url))
            return httpx.Response(
                302, headers={"location": "/sigaa/portais/discente/discente.jsf"}
            )
        if request.url.path == "/sigaa/portais/discente/discente.jsf":
            return httpx.Response(200, text=_fixture("portal.html"))
        raise AssertionError("unexpected GET")

    session = _session(handler)
    session.login()
    assert posted_to == [f"https://{HOST}/sigaa/logar.do;jsessionid=LIVESESSION7777?dispatch=logOn"]


def test_login_raises_auth_error_on_invalid_password_or_captcha():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sigaa/verTelaLogin.do":
            return httpx.Response(200, text=_fixture("login.html"))
        # Struts re-renders the same login page in place: no redirect, loginForm
        # still present.
        return httpx.Response(200, text=_fixture("login.html"))

    session = _session(handler)
    with pytest.raises(UFCGError) as excinfo:
        session.login()
    assert excinfo.value.category == "auth"
    assert "s3cr3t" not in str(excinfo.value)


def test_login_does_not_call_password_when_the_action_is_outside_the_expected_host():
    login_html = _fixture("login.html").replace(
        'action="/sigaa/logar.do;jsessionid=FAKEJSESSION0001?dispatch=logOn"',
        'action="https://evil.example.com/phish"',
    )
    password_calls = []

    def password():
        password_calls.append(1)
        return "s3cr3t"

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=login_html)

    session = _session(handler, password=password)
    with pytest.raises(UFCGError) as excinfo:
        session.login()
    assert excinfo.value.category == "protocol"
    assert password_calls == []
    # only the initial GET was ever sent: the POST carrying the secret never went out.
    assert len(requests) == 1


def test_login_is_reconstructed_with_a_fresh_get_and_action_each_call():
    renders = iter(["FIRSTSESSION0001", "SECONDSESSION0002"])
    get_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        if request.url.path == "/sigaa/verTelaLogin.do":
            get_count += 1
            session_id = next(renders)
            html = _fixture("login.html").replace("FAKEJSESSION0001", session_id)
            return httpx.Response(200, text=html)
        if request.method == "POST":
            return httpx.Response(
                302, headers={"location": "/sigaa/portais/discente/discente.jsf"}
            )
        if request.url.path == "/sigaa/portais/discente/discente.jsf":
            return httpx.Response(200, text=_fixture("portal.html"))
        raise AssertionError("unexpected GET")

    session = _session(handler)
    session.login()
    session.login()
    assert get_count == 2


# --- get(): redirect validation, retry policy --------------------------------


def test_get_blocks_a_redirect_outside_the_expected_host_before_following_it():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sigaa/verTelaLogin.do":
            return httpx.Response(302, headers={"location": "http://evil.example.com/"})
        raise AssertionError("must not follow the blocked redirect")

    session = _session(handler)
    with pytest.raises(UFCGError) as excinfo:
        session.get(LOGIN_URL)
    assert excinfo.value.category == "protocol"


def test_get_retries_once_on_a_transient_transport_error_then_succeeds():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, text=_fixture("login.html"))

    session = _session(handler)
    response = session.get(LOGIN_URL)
    assert response.status_code == 200
    assert attempts["n"] == 2


def test_get_does_not_retry_a_second_time_after_the_retry_also_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    session = _session(handler)
    with pytest.raises(UFCGError) as excinfo:
        session.get(LOGIN_URL)
    assert excinfo.value.category == "network"


def test_get_raises_protocol_on_unexpected_4xx_without_retrying():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404, text="not found")

    session = _session(handler)
    with pytest.raises(UFCGError) as excinfo:
        session.get(LOGIN_URL)
    assert excinfo.value.category == "protocol"
    assert len(requests) == 1


def test_get_raises_network_with_parsed_retry_after_on_429_and_does_not_retry():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"retry-after": "5"})

    session = _session(handler)
    with pytest.raises(UFCGError) as excinfo:
        session.get(LOGIN_URL)
    assert excinfo.value.category == "network"
    assert excinfo.value.retry_after == 5.0
    assert len(requests) == 1


def test_get_503_without_retry_after_header_leaves_retry_after_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    session = _session(handler)
    with pytest.raises(UFCGError) as excinfo:
        session.get(LOGIN_URL)
    assert excinfo.value.retry_after is None


# --- post(): single send, no retry, no redirect following --------------------


def test_post_sends_exactly_one_request_on_transport_timeout():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    session = _session(handler)
    action = FormAction(f"https://{HOST}/sigaa/logar.do", (("a", "b"),))
    with pytest.raises(UFCGError) as excinfo:
        session.post(action)
    assert excinfo.value.category == "network"
    assert len(requests) == 1


def test_post_does_not_retry_on_a_server_error():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    session = _session(handler)
    action = FormAction(f"https://{HOST}/sigaa/logar.do", (("a", "b"),))
    with pytest.raises(UFCGError) as excinfo:
        session.post(action)
    assert excinfo.value.category == "protocol"
    assert len(requests) == 1


def test_post_returns_a_redirect_response_for_the_caller_to_inspect():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/sigaa/next"})

    session = _session(handler)
    action = FormAction(f"https://{HOST}/sigaa/logar.do", (("a", "b"),))
    response = session.post(action)
    assert response.status_code == 302


def test_post_blocks_an_action_outside_the_expected_host():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never be called")

    session = _session(handler)
    action = FormAction("https://evil.example.com/x", (("a", "b"),))
    with pytest.raises(UFCGError) as excinfo:
        session.post(action)
    assert excinfo.value.category == "protocol"


# --- context manager -----------------------------------------------------


def test_session_closes_the_client_as_a_context_manager():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with UFCGSession("jucag", lambda: "s3cr3t", client=client) as session:
        assert session is not None
    assert client.is_closed

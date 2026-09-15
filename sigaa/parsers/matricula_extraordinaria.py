"""UFCG matrícula extraordinária: parse HTML/JSF, never do I/O or hold credentials.

Only the primitives needed for login, session detection and the two known forms
(menu, search) live here for now. Result parsing (`parse_classes`, selection,
confirmation) is gated on a real capture and is not implemented yet.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

FormFields = list[tuple[str, str]]

_VIEWSTATE_NAME = "javax.faces.ViewState"
_MENU_TARGET = "matriculaExtraordinaria.iniciar"
# The JSCookMenu postback string is not reliably in a hidden field's default
# value: a standard Tomahawk render leaves the hidden `jscook_action` input
# empty and keeps the real string in a <script> menu array, set into the
# field by an onclick handler. Search the whole render for a quoted (single or
# double) string that contains the target, wherever it lives.
_MENU_ACTION_RE = re.compile(r"[\"']([^\"']*" + re.escape(_MENU_TARGET) + r"[^\"']*)[\"']")
_PORTAL_PATH = "/sigaa/portais/discente/discente.jsf"
_CLASS_RE = re.compile(r"(?:turma\s+)?0*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class FormAction:
    """An absolute action URL plus the fields to submit, exactly once, with it.

    ``fields`` may carry short-lived tokens (ViewState, credentials once filled
    in by the session), so it is left out of ``repr``.
    """

    action: str
    fields: tuple[tuple[str, str], ...] = field(repr=False)


def build_form_payload(form: Tag, overrides: FormFields) -> FormFields:
    """Copy the form's current hidden fields, then apply ``overrides``.

    Every hidden input with a ``name`` is copied verbatim (duplicates preserved,
    e.g. repeated checkbox values). Any hidden field whose name also appears in
    ``overrides`` is dropped in favor of the override; overrides are appended in
    the order given, including their own intentional repeats.
    """
    replaced = {name for name, _ in overrides}
    fields = [
        (node["name"], node.get("value", ""))
        for node in form.select('input[type="hidden"][name]')
        if node["name"] not in replaced
    ]
    return fields + list(overrides)


def normalize_class(label: str) -> str:
    """Normalize a turma label for exact-match comparison.

    ``"02"``, ``"2"`` and ``"Turma 02"`` normalize to the same value. A label
    that is not a bare (optionally zero-padded, optionally "Turma "-prefixed)
    number, such as ``"02/01"``, is returned unchanged so it never matches a
    normalized single-number target.
    """
    text = unicodedata.normalize("NFKC", label).strip()
    match = _CLASS_RE.fullmatch(text)
    return match.group(1) if match else text


def login_action(html: str, url: str) -> FormAction:
    """Extract the classic ``loginForm`` action and fields.

    Copies every hidden field from the current render, then fixes the two
    dimension fields and reserves empty ``user.login``/``user.senha`` slots for
    the session to fill in when it builds the POST (credentials are never known
    here).
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", attrs={"name": "loginForm"})
    if form is None:
        raise ValueError("loginForm not found")
    action_url = urljoin(url, form["action"])
    fields = build_form_payload(
        form,
        [
            ("width", "1280"),
            ("height", "800"),
            ("user.login", ""),
            ("user.senha", ""),
        ],
    )
    return FormAction(action_url, tuple(fields))


def menu_action(html: str, url: str) -> FormAction | None:
    """Extract the JSCookMenu postback that starts the extraordinária.

    The target action string is searched across the *whole* render (hidden
    field value, or a quoted string inside a `<script>` menu array — the shape
    the real Tomahawk JSCookMenu markup is expected to use), not just the
    `jscook_action` hidden field's default value, which is typically empty
    until JS sets it on click. Returns ``None`` when the discente menu form is
    absent or the target string is nowhere in the render (e.g. the period is
    closed and the menu item is not rendered), so callers can fall back to the
    direct endpoint per SPEC §8.3.
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", attrs={"name": "menu:form_menu_discente"})
    if form is None:
        return None
    match = _MENU_ACTION_RE.search(html)
    if match is None:
        return None
    hidden = form.select('input[type="hidden"][name]')
    _require_viewstate(hidden, "extraordinária menu form")
    action_url = urljoin(url, form["action"])
    fields = build_form_payload(form, [("jscook_action", match.group(1))])
    return FormAction(action_url, tuple(fields))


def search_action(html: str, url: str, code: str) -> FormAction:
    """Build the search postback: only the three documented fields are filled.

    ``form:checkCodigo`` is checked, ``form:txtCodigo`` gets ``code``, and
    ``form:buscar`` is sent with whatever label the current render's submit
    button carries. Every other hidden field is copied as-is.
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", attrs={"name": "form"})
    if form is None:
        raise ValueError("extraordinária search form not found")
    button = form.find(attrs={"name": "form:buscar"})
    buscar_value = button.get("value", "") if button is not None else ""
    fields = build_form_payload(
        form,
        [
            ("form:checkCodigo", "checked"),
            ("form:txtCodigo", code),
            ("form:buscar", buscar_value),
        ],
    )
    _require_viewstate(form.select('input[type="hidden"][name]'), "extraordinária search form")
    action_url = urljoin(url, form["action"])
    return FormAction(action_url, tuple(fields))


def is_authenticated_portal(html: str, url: str) -> bool:
    """True only when URL, DOM and logout link all agree the portal is authenticated.

    Per SPEC §8.1: the URL must be the discente portal, a `SAIR` link to
    ``logar.do?dispatch=logOff`` must be present, and no ``loginForm`` may
    remain in the DOM. The UFPB "Sair do SIGAA" marker is not used for UFCG.

    The URL is matched on its path only (a substring match would wrongly pass
    e.g. ``verTelaLogin.do?urlRedirect=/sigaa/portais/discente/discente.jsf``).
    """
    path = urlparse(url).path.split(";")[0]
    if path != _PORTAL_PATH:
        return False
    soup = BeautifulSoup(html, "lxml")
    if soup.find("form", attrs={"name": "loginForm"}) is not None:
        return False
    logout = soup.find("a", href=re.compile(r"logar\.do\?dispatch=logOff"))
    if logout is None:
        return False
    return "sair" in logout.get_text(strip=True).casefold()


def _require_viewstate(hidden_nodes, context: str) -> None:
    if not any(
        node.get("name") == _VIEWSTATE_NAME and node.get("value")
        for node in hidden_nodes
    ):
        raise ValueError(f"{context} has no javax.faces.ViewState")

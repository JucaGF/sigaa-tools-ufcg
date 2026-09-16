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
_EXTRAORDINARY_PATH = "/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf"
_CLASS_RE = re.compile(r"(?:turma\s+)?0*(\d+)", re.IGNORECASE)
_PERIOD_CLOSED_TEXT = "matrícula extraordinária não está disponível no momento"

# Fixed selection target (SPEC §10.3): no fallback to another turma, ever.
_TARGET_COMPONENT = "1109103"

# Results-table header aliases -> canonical column key. Hypothesis pending a
# real capture (see docs/superpowers/specs/2026-09-15-ufcg-extraordinaria-capture.md):
# only the search *form* (form name="form", form:checkCodigo/txtCodigo/buscar)
# is confirmed from a real UFCG render; the results table shape below is
# derived from the UFPB regular-matrícula render of the same SIGAA family
# (table class="formulario"), never a real UFCG extraordinária capture.
_RESULTS_HEADER_MAP = {
    "turma": "turma",
    "código da turma": "turma",
    "horário": "horario",
    "vagas": "vagas",
    "vagas ofertadas": "vagas",
    "local": "local",
    "sala": "local",
}
_COMPONENT_HEADER_RE = re.compile(r"(\d{6,9})\s*-\s*(.+?)\s*\(([^)]+)\)")
# Leading component code of a "<code> - <name>" cell, same extract-then-compare
# approach as the results header above: a code that merely contains the
# target as a substring (e.g. "21109103") must never match it.
_COMPONENT_CODE_RE = re.compile(r"^\s*(\d{6,9})")
_VACANCY_RE = re.compile(r"(\d+)\s*vaga")
_JSFCLJS_RE = re.compile(r"jsfcljs\(document\.forms\[['\"][^'\"]+['\"]\],\s*['\"]([^'\"]*)['\"]")

# Verification-page header aliases -> canonical column key (same hypothesis
# caveat as above: no real "meu vínculo" render has been captured yet).
_STATUS_HEADER_MAP = {
    "componente": "componente",
    "código": "componente",
    "disciplina": "componente",
    "turma": "turma",
    "situação": "situacao",
    "status": "situacao",
    "período": "periodo",
    "semestre": "periodo",
}
_TARGET_SEMESTER = "2026.2"
# Word-boundary match so "desmatriculado" (a real, distinct negative status)
# never reads as proof: "matriculado" is a substring of it but never a word.
# No re.IGNORECASE: status_text is already casefolded by _normalize_header.
_ENROLLED_STATUS_RE = re.compile(r"\bmatriculado\b")

# SPEC §22 message categories: fixed diagnostics, the raw body is never echoed.
_UNKNOWN_RESPONSE = "resposta desconhecida"
_MESSAGE_SELECTOR = "#painel-erros li, .info, .erros li, .aviso, .erro, #mensagens li"
_MESSAGE_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "sem vaga",
        (
            "sem vaga", "não há vaga", "vaga indisponível", "não possui vaga",
            # Live capture 2026-09-16: the real search-result phrase when the
            # target component currently has no remaining vacancies.
            "não foram encontradas turmas abertas com vagas remanescentes",
        ),
    ),
    (
        # Live capture 2026-09-16: our own search payload was malformed (a
        # missing <select>, then a checkbox value SIGAA didn't recognize) --
        # a protocol bug, never a legitimate academic outcome, never pollable.
        "parâmetros de busca inválidos",
        ("campo obrigatório não informado", "por favor, escolha algum critério de busca"),
    ),
    ("já matriculado", ("já matriculado", "já está matriculado", "já possui matrícula")),
    ("choque de horário", ("choque de horário", "conflito de horário", "coincidência de horário")),
    ("pré-requisito ou correquisito", ("pré-requisito", "pre-requisito", "correquisito", "co-requisito")),
    ("limite de carga horária", ("limite de carga horária", "carga horária máxima", "excede a carga horária")),
    (
        "matrícula on-line não permitida",
        ("não permite matrícula on-line", "matrícula on-line não permitida", "matrícula on-line não é permitida"),
    ),
    ("período fechado", (_PERIOD_CLOSED_TEXT, "período de matrícula extraordinária encerrado", "fora do período")),
    (
        "dados de confirmação incorretos",
        ("senha incorreta", "dados informados são inválidos", "confirmação inválida",
         "dados de confirmação incorretos", "data de nascimento não confere"),
    ),
    ("sessão expirada", ("sessão expirada", "sessão foi encerrada", "sua sessão expirou")),
    ("indisponibilidade do sistema", ("sistema indisponível", "manutenção", "tente novamente mais tarde")),
)

_BIRTHDATE_HINT_RE = re.compile(r"nasc|birth", re.IGNORECASE)


class AmbiguousSelectionError(ValueError):
    """Two results rows normalize to the same target component + turma (fail closed)."""


@dataclass(frozen=True)
class ExtraordinaryClass:
    """SPEC §13: only the fields that drive selection, logs or diagnostics."""

    component_code: str
    class_token: str
    class_label: str
    vacancies: int | None
    schedule_raw: str | None
    room: str | None
    selection_fields: tuple[tuple[str, str], ...]


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


def _selected_option_value(select: Tag) -> str:
    """The value a browser would submit for ``select``: the selected option, else the first."""
    options = select.select("option")
    chosen = next((o for o in options if o.has_attr("selected")), options[0] if options else None)
    if chosen is None:
        return ""
    return chosen.get("value", chosen.get_text(strip=True))


def search_action(html: str, url: str, code: str) -> FormAction:
    """Build the search postback: ``form:checkCodigo`` is checked,
    ``form:txtCodigo`` gets ``code``, and ``form:buscar`` is sent with
    whatever label the current render's submit button carries. Every hidden
    field is copied as-is, and every ``<select>`` is sent with its currently
    selected option's value (the department combo rejects an omitted select).
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", attrs={"name": "form"})
    if form is None:
        raise ValueError("extraordinária search form not found")
    button = form.find(attrs={"name": "form:buscar"})
    buscar_value = button.get("value", "") if button is not None else ""
    # The real render (captured 2026-09-16) rejects a payload that omits the
    # department <select>: "form:comboDepartamento: Campo obrigatório não
    # informado". Selects are not hidden inputs, so send each one's currently
    # selected option, which on the search form is "-- SELECIONE --" (value 0).
    selects = [(node["name"], _selected_option_value(node)) for node in form.select("select[name]")]
    fields = build_form_payload(
        form,
        [
            *selects,
            # A browser submits "on" for a checked checkbox with no value
            # attribute; the real render rejected "checked" with "Por favor,
            # escolha algum critério de busca" (captured 2026-09-16).
            ("form:checkCodigo", "on"),
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


def is_period_closed(html: str, url: str) -> bool:
    """True when the render signals the extraordinária window is not open.

    Covers the three SPEC §8.4 signals together, so both the flow's "open"
    step (menu/direct-endpoint result) and its "search" step (search POST
    result) can reuse the same check:

    - an explicit period message;
    - a bounce back to the authenticated portal;
    - the search form being absent while the URL sits outside the
      extraordinária flow (a not-yet-modeled success/results render would
      still be *on* that flow's URL, so this is safe to read as closed).
    """
    normalized = unicodedata.normalize("NFKC", html).casefold()
    if _PERIOD_CLOSED_TEXT in normalized:
        return True
    if is_authenticated_portal(html, url):
        return True
    path = urlparse(url).path.split(";")[0]
    if path == _EXTRAORDINARY_PATH:
        return False
    soup = BeautifulSoup(html, "lxml")
    return soup.find("form", attrs={"name": "form"}) is None


def _require_viewstate(hidden_nodes, context: str) -> None:
    if not any(
        node.get("name") == _VIEWSTATE_NAME and node.get("value")
        for node in hidden_nodes
    ):
        raise ValueError(f"{context} has no javax.faces.ViewState")


def _normalize_header(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
    return collapsed.casefold()


def _find_results_table(soup: BeautifulSoup) -> Tag | None:
    table = soup.find("table", id=re.compile(r"resultado|turmas", re.IGNORECASE))
    if table is not None:
        return table
    for candidate in soup.find_all("table"):
        for row in candidate.find_all("tr"):
            headers = {_normalize_header(th.get_text(" ", strip=True)) for th in row.find_all("th")}
            if "turma" in headers:
                return candidate
    return None


def parse_classes(html: str) -> list[ExtraordinaryClass]:
    """Extraordinária results table -> rows, SPEC §13.

    Raises ``ValueError`` when no recognizable results table is present at
    all (an unmodeled/unknown render -- the caller must fail closed, never
    guess). An empty list is returned when the table *is* recognized but no
    row matches anything (e.g. the searched component is simply absent).
    """
    soup = BeautifulSoup(html, "lxml")
    table = _find_results_table(soup)
    if table is None:
        raise ValueError("extraordinária results table not found")

    component: str | None = None
    columns: dict[str, int] = {}
    results: list[ExtraordinaryClass] = []
    for row in table.find_all("tr"):
        ths = row.find_all("th")
        if ths:
            if len(ths) == 1 and ths[0].get("colspan"):
                match = _COMPONENT_HEADER_RE.search(ths[0].get_text(" ", strip=True))
                if match:
                    component = match.group(1)
                continue
            columns = {}
            for index, th in enumerate(ths):
                key = _RESULTS_HEADER_MAP.get(_normalize_header(th.get_text(" ", strip=True)))
                if key is not None:
                    columns[key] = index
            continue
        tds = row.find_all("td")
        if not tds or not columns or component is None:
            continue
        cls = _row_to_class(component, tds, columns, row)
        if cls is not None:
            results.append(cls)
    return results


def _cell_text_or_none(tds: list[Tag], index: int | None) -> str | None:
    if index is None or index >= len(tds):
        return None
    text = tds[index].get_text(" ", strip=True)
    return text or None


def _parse_vacancies(text: str | None) -> int | None:
    if text is None:
        return None
    match = _VACANCY_RE.search(text)
    if match:
        return int(match.group(1))
    stripped = text.strip()
    return int(stripped) if stripped.isdigit() else None


def _parse_jsfcljs(href: str) -> tuple[tuple[str, str], ...]:
    match = _JSFCLJS_RE.search(href)
    if not match:
        return ()
    pairs = []
    for chunk in match.group(1).split(","):
        if ":" not in chunk:
            continue
        key, value = chunk.split(":", 1)
        pairs.append((key, value))
    return tuple(pairs)


def _selection_fields_from_row(row: Tag) -> tuple[tuple[str, str], ...]:
    link = row.find("a", href=re.compile(r"jsfcljs\("))
    if link is not None and link.get("disabled") is None:
        pairs = _parse_jsfcljs(link["href"])
        if pairs:
            return pairs
    button = row.find("input", attrs={"type": re.compile("^(submit|image)$", re.IGNORECASE), "name": True})
    if button is not None and button.get("disabled") is None and button.get("value") is not None:
        return ((button["name"], button.get("value", "")),)
    checkbox = row.find("input", attrs={"type": re.compile("^(checkbox|radio)$", re.IGNORECASE), "name": True})
    if checkbox is not None and checkbox.get("disabled") is None and checkbox.get("value"):
        return ((checkbox["name"], checkbox["value"]),)
    return ()


def _row_to_class(
    component_code: str, tds: list[Tag], columns: dict[str, int], row: Tag
) -> ExtraordinaryClass | None:
    turma_index = columns.get("turma")
    if turma_index is None or turma_index >= len(tds):
        return None
    class_label = tds[turma_index].get_text(" ", strip=True)
    if not class_label:
        return None
    return ExtraordinaryClass(
        component_code=component_code,
        class_token=normalize_class(class_label),
        class_label=class_label,
        vacancies=_parse_vacancies(_cell_text_or_none(tds, columns.get("vagas"))),
        schedule_raw=_cell_text_or_none(tds, columns.get("horario")),
        room=_cell_text_or_none(tds, columns.get("local")),
        selection_fields=_selection_fields_from_row(row),
    )


def select_target(rows: list[ExtraordinaryClass]) -> ExtraordinaryClass | None:
    """SPEC §10.3: exact component + turma match, never a turma-01 fallback."""
    target_token = normalize_class("02")
    matches = [
        row for row in rows
        if row.component_code == _TARGET_COMPONENT and normalize_class(row.class_token) == target_token
    ]
    if len(matches) > 1:
        raise AmbiguousSelectionError(
            "extraordinária results are ambiguous: more than one row normalizes to the target"
        )
    return matches[0] if matches else None


def selection_action(html: str, url: str, row: ExtraordinaryClass) -> FormAction:
    """Round-2 review fix: an empty ``selection_fields`` means no recognized
    control was found for this row (SPEC §13's "trustworthy enabled
    selection control" requirement) -- posting without it can't express
    which row was chosen, so this fails closed before touching the DOM.
    """
    if not row.selection_fields:
        raise ValueError("extraordinária target row has no recognized selection control")
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", attrs={"name": "form"})
    if form is None:
        raise ValueError("extraordinária results form not found")
    _require_viewstate(form.select('input[type="hidden"][name]'), "extraordinária results form")
    fields = build_form_payload(form, list(row.selection_fields))
    return FormAction(urljoin(url, form["action"]), tuple(fields))


def _find_confirmation_form(soup: BeautifulSoup) -> Tag | None:
    for form in soup.find_all("form"):
        if form.select_one('input[type="password"][name]') is not None:
            return form
    return None


def _find_birthdate_field(form: Tag, password_name: str) -> Tag | None:
    for node in form.select('input[type="date"], input[type="text"]'):
        name = node.get("name")
        if not name or name == password_name:
            continue
        if _BIRTHDATE_HINT_RE.search(name) or _BIRTHDATE_HINT_RE.search(node.get("id") or ""):
            return node
    return None


def _identity_fields(html: str) -> tuple[Tag, dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    form = _find_confirmation_form(soup)
    if form is None:
        raise ValueError("extraordinária confirmation form not found")
    password_field = form.select_one('input[type="password"][name]')
    if password_field is None:
        raise ValueError("extraordinária confirmation form has no password field")
    names = {"password": password_field["name"]}
    birthdate_field = _find_birthdate_field(form, password_field["name"])
    if birthdate_field is not None:
        names["birth_date"] = birthdate_field["name"]
    return form, names


def confirmation_identity_fields(html: str) -> dict[str, str]:
    """The confirmation form's identity field *names* (never values/secrets)."""
    _, names = _identity_fields(html)
    return names


_CANCEL_HINT_RE = re.compile(r"cancel|volt")
_CONFIRM_HINT_RE = re.compile(r"confirm")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _find_confirmation_button(form: Tag) -> Tag:
    """Review fix: the real confirmation button's name/value has never been
    captured from a live render, so unlike `search_action`'s exact match on
    the known `form:buscar`, this can only guess -- and the earlier guess
    ("first submit/image control in document order") posts Cancelar instead
    of Confirmar whenever a real render puts Cancelar first, with
    `prepared.sent` already True by the time that mistake is discovered.

    Picks the control whose name/value reads as "confirm" (casefolded,
    accent-insensitive); excludes any reading as "cancel"/"voltar" outright;
    and fails closed (`ValueError`) when that leaves anything other than
    exactly one candidate, rather than guessing among several.
    """
    controls = form.find_all(attrs={"type": re.compile("^(submit|image)$", re.IGNORECASE), "name": True})
    if not controls:
        raise ValueError("extraordinária confirmation form has no submit/image command button")
    candidates = [c for c in controls if not _CANCEL_HINT_RE.search(_fold(f"{c['name']} {c.get('value', '')}"))]
    if len(candidates) == 1:
        return candidates[0]
    confirm_candidates = [c for c in candidates if _CONFIRM_HINT_RE.search(_fold(f"{c['name']} {c.get('value', '')}"))]
    if len(confirm_candidates) == 1:
        return confirm_candidates[0]
    raise ValueError("extraordinária confirmation form has no unambiguous confirm command button")


def confirmation_action(html: str, url: str) -> FormAction:
    """Round-2 review fix: a JSF form posted without its command-button
    parameter never invokes the action (it just re-renders) -- the button
    is located and added, via `_find_confirmation_button` (see its
    docstring: this cannot match the real button by name the way
    `search_action` matches `form:buscar`, so it is heuristic and fails
    closed on ambiguity). Also fails closed when no submit/image control is
    found at all, same as a missing password field.
    """
    form, names = _identity_fields(html)
    _require_viewstate(form.select('input[type="hidden"][name]'), "extraordinária confirmation form")
    button = _find_confirmation_button(form)
    overrides = [(name, "") for name in names.values()]
    overrides.append((button["name"], button.get("value", "")))
    fields = build_form_payload(form, overrides)
    return FormAction(urljoin(url, form["action"]), tuple(fields))


def is_enrolled(html: str) -> bool:
    """SPEC §16: component 1109103 + turma 02 + MATRICULADO in the SAME row,
    for semester 2026.2. Any other component/turma, an explicit
    ``NÃO MATRICULADO``, a bodiless success message, or a historical semester
    (a Período/Semestre column present and not matching) is False.
    """
    soup = BeautifulSoup(html, "lxml")
    target_token = normalize_class("02")
    for table in soup.find_all("table"):
        columns: dict[str, int] = {}
        for row in table.find_all("tr"):
            ths = row.find_all("th")
            if ths:
                columns = {}
                for index, th in enumerate(ths):
                    key = _STATUS_HEADER_MAP.get(_normalize_header(th.get_text(" ", strip=True)))
                    if key is not None:
                        columns[key] = index
                continue
            if not columns:
                continue
            tds = row.find_all("td")
            if _row_shows_enrollment(tds, columns, target_token):
                return True
    return False


def _row_shows_enrollment(tds: list[Tag], columns: dict[str, int], target_token: str) -> bool:
    component_index = columns.get("componente")
    turma_index = columns.get("turma")
    status_index = columns.get("situacao")
    if component_index is None or turma_index is None or status_index is None:
        return False
    if component_index >= len(tds) or turma_index >= len(tds) or status_index >= len(tds):
        return False
    component_text = tds[component_index].get_text(" ", strip=True)
    component_match = _COMPONENT_CODE_RE.match(component_text)
    if component_match is None or component_match.group(1) != _TARGET_COMPONENT:
        return False
    turma_text = tds[turma_index].get_text(" ", strip=True)
    if normalize_class(turma_text) != target_token:
        return False
    status_text = _normalize_header(tds[status_index].get_text(" ", strip=True))
    if "não matriculado" in status_text or "nao matriculado" in status_text:
        return False
    # word-boundary match: "matriculado" must appear as its own word, not as
    # a substring of e.g. "desmatriculado" (a real, distinct negative status).
    if not _ENROLLED_STATUS_RE.search(status_text):
        return False
    # Fail closed: a verification table with no Período/Semestre column at
    # all can never prove the *current* semester, so it is never proof.
    period_index = columns.get("periodo")
    if period_index is None or period_index >= len(tds):
        return False
    period_text = tds[period_index].get_text(" ", strip=True)
    if period_text != _TARGET_SEMESTER:
        return False
    return True


def classify_message(html: str) -> str:
    """SPEC §22: a fixed diagnostic category, never the raw sanitized text.

    Classifies ONLY the text inside SIGAA's own message panels
    (`_MESSAGE_SELECTOR`) -- never the whole page. A real UFCG extraordinária
    SEARCH page's instructional prose (outside any message panel, in a
    `div.descricaoOperacao`) contains "já está matriculado", "choque de
    horários" and the literal word "MATRICULADO", none of which are an
    actual SIGAA message; scanning the whole document previously
    misclassified that ordinary page as "já matriculado" on every render.
    No recognized message panel -> `resposta desconhecida`, never a body-text
    guess.
    """
    soup = BeautifulSoup(html, "lxml")
    texts = [_normalize_header(node.get_text(" ", strip=True)) for node in soup.select(_MESSAGE_SELECTOR)]
    for text in texts:
        for category, needles in _MESSAGE_CATEGORIES:
            if any(_normalize_header(needle) in text for needle in needles):
                return category
    return _UNKNOWN_RESPONSE

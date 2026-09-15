from pathlib import Path

from bs4 import BeautifulSoup

from sigaa.parsers.matricula_extraordinaria import (
    FormAction,
    build_form_payload,
    is_authenticated_portal,
    login_action,
    menu_action,
    normalize_class,
    search_action,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ufcg"
PORTAL_URL = "https://sigaa.ufcg.edu.br/sigaa/portais/discente/discente.jsf"
LOGIN_URL = "https://sigaa.ufcg.edu.br/sigaa/verTelaLogin.do"
SEARCH_URL = (
    "https://sigaa.ufcg.edu.br/sigaa/graduacao/matricula/extraordinaria/"
    "matricula_extraordinaria.jsf"
)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_hidden_fields_preserve_duplicates_and_replace_current_value():
    form = BeautifulSoup(
        """<form>
      <input type="hidden" name="x" value="a">
      <input type="hidden" name="x" value="b">
      <input type="hidden" name="javax.faces.ViewState" value="render-2">
      <input name="password" value="must-not-copy">
    </form>""",
        "lxml",
    ).form
    assert build_form_payload(form, [("code", "1109103")]) == [
        ("x", "a"),
        ("x", "b"),
        ("javax.faces.ViewState", "render-2"),
        ("code", "1109103"),
    ]


def test_build_form_payload_keeps_repeated_overrides_as_given():
    form = BeautifulSoup(
        '<form><input type="hidden" name="x" value="a"></form>', "lxml"
    ).form
    result = build_form_payload(form, [("y", "1"), ("y", "2")])
    assert result == [("x", "a"), ("y", "1"), ("y", "2")]


# --- normalize_class ---------------------------------------------------


def test_normalize_class_treats_zero_padded_and_prefixed_labels_as_equal():
    assert normalize_class("02") == normalize_class("2") == normalize_class("Turma 02")


def test_normalize_class_rejects_compound_strings_as_equivalent():
    target = normalize_class("02")
    assert normalize_class("12") != target
    assert normalize_class("202") != target
    assert normalize_class("02/01") != target


# --- login_action --------------------------------------------------------


def test_login_action_extracts_action_and_fixed_dimensions():
    html = _fixture("login.html")
    action = login_action(html, LOGIN_URL)
    assert action.action == (
        "https://sigaa.ufcg.edu.br/sigaa/logar.do;jsessionid=FAKEJSESSION0001?dispatch=logOn"
    )
    fields = dict(action.fields)
    assert fields["width"] == "1280"
    assert fields["height"] == "800"
    assert fields["user.login"] == ""
    assert fields["user.senha"] == ""
    # hidden fields copied verbatim from the render
    assert fields["urlRedirect"] == ""
    assert fields["subsistemaRedirect"] == ""
    assert fields["acao"] == ""
    assert fields["acessibilidade"] == ""
    # the password field is never in the repr
    assert "user.senha" not in repr(action)


def test_login_action_uses_the_action_of_the_current_render():
    html = _fixture("login.html").replace(
        "jsessionid=FAKEJSESSION0001", "jsessionid=OTHERSESSION9999"
    )
    action = login_action(html, LOGIN_URL)
    assert "OTHERSESSION9999" in action.action
    assert "FAKEJSESSION0001" not in action.action


# --- menu_action -----------------------------------------------------------


def test_menu_action_finds_the_full_postback_string():
    html = _fixture("portal.html")
    action = menu_action(html, PORTAL_URL)
    assert action is not None
    fields = dict(action.fields)
    assert fields["jscook_action"] == (
        "menu_form_menu_discente_discente_menu:A]#{ matriculaExtraordinaria.iniciar}"
    )
    assert action.action == "https://sigaa.ufcg.edu.br/sigaa/portais/discente/discente.jsf"


def test_menu_action_reads_ids_from_the_current_render_not_a_previous_one():
    html = _fixture("portal.html").replace(
        "j_id_jsp_1111111_1", "j_id_jsp_2222222_9"
    ).replace("render-fake-0001", "render-fake-9999")
    action = menu_action(html, PORTAL_URL)
    fields = dict(action.fields)
    assert fields["id"] == "j_id_jsp_2222222_9"
    assert fields["javax.faces.ViewState"] == "render-fake-9999"


def test_menu_action_returns_none_when_period_closed():
    html = _fixture("period_closed.html")
    assert menu_action(html, PORTAL_URL) is None


def test_menu_action_finds_the_postback_inside_a_script_menu_array():
    # A standard Tomahawk JSCookMenu render leaves the hidden jscook_action
    # input empty and keeps the real postback string in a <script> array,
    # set into the field by an onclick handler that never runs during a
    # plain HTML fetch. The parser must search the whole render, not just
    # the hidden field's default value.
    html = _fixture("portal_script_menu.html")
    action = menu_action(html, PORTAL_URL)
    assert action is not None
    fields = dict(action.fields)
    assert fields["jscook_action"] == (
        "menu_form_menu_discente_discente_menu:A]#{ matriculaExtraordinaria.iniciar}"
    )
    # the other hidden fields (ViewState included) still come from the form.
    assert fields["id"] == "j_id_jsp_3333333_3"
    assert fields["javax.faces.ViewState"] == "render-fake-0003"


# --- search_action -----------------------------------------------------------


def test_search_action_fills_only_the_three_documented_overrides():
    html = _fixture("search.html")
    action = search_action(html, SEARCH_URL, "1109103")
    assert action.action == SEARCH_URL
    fields = dict(action.fields)
    assert fields["form:checkCodigo"] == "checked"
    assert fields["form:txtCodigo"] == "1109103"
    assert fields["form:buscar"] == "Buscar"
    # hidden fields from the current render are preserved
    assert fields["form"] == "form"
    assert fields["javax.faces.ViewState"] == "render-fake-0002"
    # fields not part of the documented overrides are not touched/added
    assert "form:txtNome" not in fields


def test_search_action_uses_the_buscar_button_label_of_the_current_render():
    html = _fixture("search.html").replace(
        'name="form:buscar" value="Buscar"', 'name="form:buscar" value="Pesquisar"'
    ).replace("render-fake-0002", "render-fake-7777")
    action = search_action(html, SEARCH_URL, "1109103")
    fields = dict(action.fields)
    assert fields["form:buscar"] == "Pesquisar"
    assert fields["javax.faces.ViewState"] == "render-fake-7777"


# --- is_authenticated_portal -------------------------------------------------


def test_is_authenticated_portal_true_on_portal_with_logout_link_and_no_login_form():
    assert is_authenticated_portal(_fixture("portal.html"), PORTAL_URL) is True


def test_is_authenticated_portal_false_when_login_form_still_present():
    assert is_authenticated_portal(_fixture("login.html"), LOGIN_URL) is False


def test_is_authenticated_portal_false_when_url_is_not_the_portal():
    assert is_authenticated_portal(_fixture("portal.html"), SEARCH_URL) is False


def test_is_authenticated_portal_false_on_substring_match_outside_the_path():
    # The portal path appearing as a query string value must not count: only
    # the URL's own path is checked.
    url = LOGIN_URL + "?urlRedirect=/sigaa/portais/discente/discente.jsf"
    assert is_authenticated_portal(_fixture("portal.html"), url) is False


def test_form_action_repr_hides_field_values():
    action = FormAction("https://sigaa.ufcg.edu.br/x", (("user.senha", "topsecret"),))
    assert "topsecret" not in repr(action)

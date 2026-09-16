from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from sigaa.parsers.matricula_extraordinaria import (
    AmbiguousSelectionError,
    ExtraordinaryClass,
    FormAction,
    build_form_payload,
    classify_message,
    confirmation_action,
    confirmation_identity_fields,
    is_authenticated_portal,
    is_enrolled,
    is_period_closed,
    login_action,
    menu_action,
    normalize_class,
    parse_classes,
    search_action,
    select_target,
    selection_action,
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


def test_search_action_fills_the_live_verified_overrides():
    # Live capture 2026-09-16: a real render rejected "form:checkCodigo=checked"
    # ("Por favor, escolha algum critério de busca" -- a browser submits "on"
    # for a checked checkbox with no value attribute) and rejected a payload
    # missing "form:comboDepartamento" ("Campo obrigatório não informado").
    html = _fixture("search.html")
    action = search_action(html, SEARCH_URL, "1109103")
    assert action.action == SEARCH_URL
    fields = dict(action.fields)
    assert fields["form:checkCodigo"] == "on"
    assert fields["form:txtCodigo"] == "1109103"
    assert fields["form:buscar"] == "Buscar"
    assert fields["form:comboDepartamento"] == "0"
    # hidden fields from the current render are preserved
    assert fields["form"] == "form"
    assert fields["javax.faces.ViewState"] == "render-fake-0002"
    # fields not part of the documented overrides are not touched/added
    assert "form:txtNome" not in fields


def test_search_action_sends_the_selects_explicitly_selected_option():
    # Regression for the live-verified contract: a <select> is not a hidden
    # input, so its currently *selected* option (not just the first one) must
    # be sent, exactly as a browser would submit it.
    html = """<html><body><form name="form" method="post" action="x.jsf">
      <select name="form:comboDepartamento">
        <option value="0">-- SELECIONE --</option>
        <option value="588" selected="selected">ASSESSORIA</option>
      </select>
      <input type="submit" name="form:buscar" value="Buscar">
      <input type="hidden" name="javax.faces.ViewState" value="render-fake-0002">
    </form></body></html>"""
    action = search_action(html, SEARCH_URL, "1109103")
    fields = dict(action.fields)
    assert fields["form:comboDepartamento"] == "588"
    assert fields["form:checkCodigo"] == "on"


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


# --- is_period_closed ---------------------------------------------------


def test_is_period_closed_true_on_explicit_message():
    assert is_period_closed(_fixture("period_closed.html"), SEARCH_URL) is True


def test_is_period_closed_true_on_bounce_to_authenticated_portal():
    assert is_period_closed(_fixture("portal.html"), PORTAL_URL) is True


def test_is_period_closed_true_when_search_form_lost_outside_the_flow():
    # No period message, no portal bounce, but the URL sits outside the
    # extraordinária flow and the search form is gone -- SPEC §8.4's third
    # signal.
    html = "<html><body>Sessão encerrada.</body></html>"
    assert is_period_closed(html, PORTAL_URL.replace("discente.jsf", "outra.jsf")) is True


def test_is_period_closed_false_when_search_form_present_on_the_flow_url():
    assert is_period_closed(_fixture("search.html"), SEARCH_URL) is False


def test_is_period_closed_false_on_unrecognized_render_still_on_the_flow_url():
    # A render on the extraordinária URL that isn't the search form (e.g. the
    # not-yet-modeled results page) must not be misclassified as closed.
    html = "<html><body><div id='resultados'>...</div></body></html>"
    assert is_period_closed(html, SEARCH_URL) is False


# --- select_target: exact component + turma, no fallback ---------------------


def test_selection_has_no_class_one_fallback():
    row = ExtraordinaryClass(
        component_code='1109103', class_token='1', class_label='01',
        vacancies=8, schedule_raw=None, room=None, selection_fields=(),
    )
    assert select_target([row]) is None


# --- parse_classes: real search form is confirmed, results table is a hypothesis ---


def test_parse_classes_maps_headers_by_th_not_position():
    rows = parse_classes(_fixture("results.html"))
    assert len(rows) == 2
    turma02 = next(r for r in rows if r.class_token == "2")
    assert turma02.component_code == "1109103"
    assert turma02.class_label == "Turma 02"
    assert turma02.vacancies == 2
    assert turma02.schedule_raw == "246810N34"
    assert turma02.room == "CAA-202"
    assert turma02.selection_fields == (("form:selecionarTurma_1", "postback-turma-02"),)


def test_parse_classes_turma_without_vacancy_or_control_has_none_selection():
    rows = parse_classes(_fixture("results.html"))
    turma01 = next(r for r in rows if r.class_token == "1")
    assert turma01.vacancies == 0
    assert turma01.selection_fields == ()


def test_parse_classes_raises_on_unrecognized_dom():
    with pytest.raises(ValueError):
        parse_classes("<html><body><div id='resultados'>unmodeled</div></body></html>")


def test_parse_classes_absent_values_are_none_not_zero():
    html = """
    <table class="formulario">
      <tr><th colspan="2">1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I (DISCIPLINA)</th></tr>
      <tr><th>Turma</th><th>Vagas</th></tr>
      <tr><td>Turma 02</td><td>-</td></tr>
    </table>
    """
    rows = parse_classes(html)
    assert rows[0].vacancies is None
    assert rows[0].schedule_raw is None
    assert rows[0].room is None


def test_parse_classes_headers_reordered_still_map_correctly():
    html = """
    <table class="formulario">
      <tr><th colspan="4">1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I (DISCIPLINA)</th></tr>
      <tr><th>Local</th><th>Vagas</th><th>Turma</th><th>Horário</th></tr>
      <tr><td>CAA-202</td><td>3 vagas</td><td>Turma 02</td><td>246810N34</td></tr>
    </table>
    """
    rows = parse_classes(html)
    assert rows[0].room == "CAA-202"
    assert rows[0].vacancies == 3
    assert rows[0].class_token == "2"
    assert rows[0].schedule_raw == "246810N34"


def test_parse_classes_component_absent_from_results_has_no_target():
    # A recognized table for a *different* component (SIGAA found no match
    # for the searched code): rows are still returned (diagnostic), but
    # select_target must find nothing for 1109103/02.
    html = """
    <table class="formulario">
      <tr><th colspan="4">1108021 - PROGRAMAÇÃO I (DISCIPLINA)</th></tr>
      <tr><th>Turma</th><th>Horário</th><th>Vagas</th><th>Local</th></tr>
      <tr><td>Turma 01</td><td>246810N12</td><td>5 vagas</td><td>CAA-100</td></tr>
    </table>
    """
    assert select_target(parse_classes(html)) is None


def test_parse_classes_recognized_table_with_zero_rows_is_empty():
    html = """
    <table class="formulario">
      <tr><th>Turma</th><th>Horário</th><th>Vagas</th><th>Local</th></tr>
    </table>
    """
    assert parse_classes(html) == []


def test_parse_classes_only_turma_one_present():
    html = """
    <table class="formulario">
      <tr><th colspan="4">1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I (DISCIPLINA)</th></tr>
      <tr><th>Turma</th><th>Horário</th><th>Vagas</th><th>Local</th></tr>
      <tr><td>Turma 01</td><td>246810N12</td><td>5 vagas</td><td>CAA-204</td></tr>
    </table>
    """
    rows = parse_classes(html)
    assert select_target(rows) is None


def test_parse_classes_jsfcljs_link_selection_control():
    html = """
    <table class="formulario">
      <tr><th colspan="2">1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I (DISCIPLINA)</th></tr>
      <tr><th>Turma</th><th>Vagas</th></tr>
      <tr><td>Turma 02</td><td>1 vaga</td>
        <td><a href="javascript:jsfcljs(document.forms['form'],'selecionar:2,k2:v2','')">Selecionar</a></td>
      </tr>
    </table>
    """
    rows = parse_classes(html)
    assert rows[0].selection_fields == (("selecionar", "2"), ("k2", "v2"))


def test_parse_classes_submit_button_selection_control():
    html = """
    <table class="formulario">
      <tr><th colspan="2">1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I (DISCIPLINA)</th></tr>
      <tr><th>Turma</th><th>Vagas</th></tr>
      <tr><td>Turma 02</td><td>1 vaga</td>
        <td><input type="submit" name="form:selecionarTurma02" value="Selecionar"></td>
      </tr>
    </table>
    """
    rows = parse_classes(html)
    assert rows[0].selection_fields == (("form:selecionarTurma02", "Selecionar"),)


# --- select_target: ambiguity fails closed --------------------------------


def test_select_target_raises_on_ambiguous_duplicate_rows():
    row = ExtraordinaryClass(
        component_code="1109103", class_token="2", class_label="Turma 02",
        vacancies=1, schedule_raw=None, room=None, selection_fields=(("a", "b"),),
    )
    with pytest.raises(AmbiguousSelectionError):
        select_target([row, row])


def test_select_target_requires_both_component_and_turma():
    other_component = ExtraordinaryClass(
        component_code="1108021", class_token="2", class_label="Turma 02",
        vacancies=5, schedule_raw=None, room=None, selection_fields=(("a", "b"),),
    )
    assert select_target([other_component]) is None


def test_select_target_picks_the_positive_vacancy_row():
    rows = parse_classes(_fixture("results.html"))
    target = select_target(rows)
    assert target is not None
    assert target.class_token == "2"
    assert target.vacancies == 2


# --- selection_action: rebuild from the row's own form ---------------------


def test_selection_action_rebuilds_current_hidden_fields_plus_row_postback():
    rows = parse_classes(_fixture("results.html"))
    target = select_target(rows)
    action = selection_action(_fixture("results.html"), SEARCH_URL, target)
    fields = dict(action.fields)
    assert fields["javax.faces.ViewState"] == "render-fake-0003"
    assert fields["form:selecionarTurma_1"] == "postback-turma-02"
    assert action.action == SEARCH_URL


# --- confirmation_action / confirmation_identity_fields ---------------------


def test_confirmation_identity_fields_are_located_dynamically_with_empty_values():
    html = _fixture("confirmation.html")
    names = confirmation_identity_fields(html)
    assert names["password"] == "form:senha"
    assert names["birth_date"] == "form:dataNascimento"
    action = confirmation_action(html, SEARCH_URL)
    fields = dict(action.fields)
    assert fields["form:senha"] == ""
    assert fields["form:dataNascimento"] == ""
    assert fields["javax.faces.ViewState"] == "render-fake-0004"
    # secrets are never stored here (values are always ""); simulate the
    # worker filling the real secret in later and confirm FormAction's
    # repr=False on `fields` still hides it (the previous assertion here was
    # vacuous: the sentinel it checked for never appeared anywhere).
    filled = FormAction(
        action.action,
        tuple((name, "S3ntinelSecretValue") if name == "form:senha" else (name, value) for name, value in action.fields),
    )
    assert "S3ntinelSecretValue" not in repr(filled)


def test_confirmation_action_without_password_field_fails_closed():
    html = "<html><body><form name='form'><input type='hidden' name='javax.faces.ViewState' value='x'></form></body></html>"
    with pytest.raises(ValueError):
        confirmation_action(html, SEARCH_URL)


def test_confirmation_action_missing_entirely_fails_closed():
    with pytest.raises(ValueError):
        confirmation_action("<html><body>nothing here</body></html>", SEARCH_URL)


# --- round 2 review fix #1: the command button must be in the payload ------


def test_confirmation_action_includes_the_command_button():
    action = confirmation_action(_fixture("confirmation.html"), SEARCH_URL)
    fields = dict(action.fields)
    # A JSF form posted without its submit/image parameter never invokes the
    # action -- it just re-renders. Real button: name="form:confirmar".
    assert fields["form:confirmar"] == "Confirmar Matrícula"


def test_confirmation_action_without_a_command_button_fails_closed():
    html = (
        "<html><body><form name='form'>"
        "<input type='hidden' name='javax.faces.ViewState' value='x'>"
        "<input type='password' name='form:senha' value=''>"
        "</form></body></html>"
    )
    with pytest.raises(ValueError):
        confirmation_action(html, SEARCH_URL)


def test_confirmation_action_skips_a_cancel_button_rendered_before_confirm():
    # Review fix: the old lookup took the FIRST submit/image control in
    # document order, which posts Cancelar (with `prepared.sent` already
    # True) if the real form ever renders it before Confirmar.
    html = (
        "<html><body><form name='form' action='/x'>"
        "<input type='hidden' name='javax.faces.ViewState' value='x'>"
        "<input type='password' name='form:senha' value=''>"
        "<input type='submit' name='form:cancelar' value='Cancelar'>"
        "<input type='submit' name='form:confirmar' value='Confirmar Matrícula'>"
        "</form></body></html>"
    )
    action = confirmation_action(html, SEARCH_URL)
    fields = dict(action.fields)
    assert fields["form:confirmar"] == "Confirmar Matrícula"
    assert "form:cancelar" not in fields


def test_confirmation_action_ambiguous_buttons_fail_closed():
    # Two submit controls, neither reading as "confirm" nor "cancel"/"voltar":
    # no rule picks a winner, so this must fail closed rather than guess.
    html = (
        "<html><body><form name='form' action='/x'>"
        "<input type='hidden' name='javax.faces.ViewState' value='x'>"
        "<input type='password' name='form:senha' value=''>"
        "<input type='submit' name='form:btn1' value='OK'>"
        "<input type='submit' name='form:btn2' value='Enviar'>"
        "</form></body></html>"
    )
    with pytest.raises(ValueError):
        confirmation_action(html, SEARCH_URL)


# --- is_enrolled: same row, same semester -----------------------------------


def test_is_enrolled_true_for_target_component_turma_and_semester():
    assert is_enrolled(_fixture("enrolled.html")) is True


def test_is_enrolled_false_for_different_component():
    html = """
    <table class="formulario">
      <tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>
      <tr><td>1108021 - PROGRAMAÇÃO I</td><td>02</td><td>MATRICULADO</td><td>2026.2</td></tr>
    </table>
    """
    assert is_enrolled(html) is False


def test_is_enrolled_false_for_different_turma():
    html = """
    <table class="formulario">
      <tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>
      <tr><td>1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</td><td>01</td><td>MATRICULADO</td><td>2026.2</td></tr>
    </table>
    """
    assert is_enrolled(html) is False


def test_is_enrolled_false_on_explicit_negation():
    html = """
    <table class="formulario">
      <tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>
      <tr><td>1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</td><td>02</td><td>NÃO MATRICULADO</td><td>2026.2</td></tr>
    </table>
    """
    assert is_enrolled(html) is False


def test_is_enrolled_false_on_success_message_without_a_bond_row():
    html = "<html><body><div class='info'>Matrícula realizada com sucesso.</div></body></html>"
    assert is_enrolled(html) is False


def test_is_enrolled_false_on_historical_semester():
    html = """
    <table class="formulario">
      <tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>
      <tr><td>1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</td><td>02</td><td>MATRICULADO</td><td>2025.1</td></tr>
    </table>
    """
    assert is_enrolled(html) is False


# --- round 2 review fix #3: no Período column at all must fail closed ------


def test_is_enrolled_false_when_the_table_has_no_period_column_at_all():
    # The old code only rejected a *present-but-mismatched* Período; a table
    # missing the column entirely fell through to True (fail open). A table
    # with no semester column can never prove the *current* semester.
    html = """
    <table class="formulario">
      <tr><th>Componente</th><th>Turma</th><th>Situação</th></tr>
      <tr><td>1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</td><td>02</td><td>MATRICULADO</td></tr>
    </table>
    """
    assert is_enrolled(html) is False


# --- round 2 review fix #4: "matriculado" must be a whole word -------------


def test_is_enrolled_false_on_desmatriculado_substring():
    html = """
    <table class="formulario">
      <tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>
      <tr><td>1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</td><td>02</td><td>DESMATRICULADO</td><td>2026.2</td></tr>
    </table>
    """
    assert is_enrolled(html) is False


def test_is_enrolled_false_on_nao_matriculado_still_rejected():
    html = """
    <table class="formulario">
      <tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>
      <tr><td>1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</td><td>02</td><td>NÃO MATRICULADO</td><td>2026.2</td></tr>
    </table>
    """
    assert is_enrolled(html) is False


def test_is_enrolled_true_still_holds_for_the_plain_positive_case():
    # Regression guard: the word-boundary + fail-closed-semester changes must
    # not break the ordinary positive case.
    assert is_enrolled(_fixture("enrolled.html")) is True


def test_is_enrolled_false_on_decoy_code_containing_target_as_substring():
    # A component code that merely *contains* the target digits (e.g. a typo
    # or a different discipline sharing the suffix) must never prove the
    # bond: the code must match exactly, not just "in" the cell text.
    html = """
    <table class="formulario">
      <tr><th>Componente</th><th>Turma</th><th>Situação</th><th>Período</th></tr>
      <tr><td>21109103 - OUTRA DISCIPLINA</td><td>02</td><td>MATRICULADO</td><td>2026.2</td></tr>
    </table>
    """
    assert is_enrolled(html) is False


# --- round 2 review fix #5: no recognized control -> fail closed, never post ---


def test_selection_action_raises_when_row_has_no_recognized_control():
    row = ExtraordinaryClass(
        component_code="1109103", class_token="2", class_label="Turma 02",
        vacancies=5, schedule_raw=None, room=None, selection_fields=(),
    )
    with pytest.raises(ValueError):
        selection_action(_fixture("results.html"), SEARCH_URL, row)


# --- classify_message: SPEC §22 categories, fixed diagnostics --------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Não há vaga disponível para esta turma.", "sem vaga"),
        ("Você já está matriculado neste componente.", "já matriculado"),
        ("Choque de horário com outra turma já matriculada.", "choque de horário"),
        ("Pré-requisito não cumprido para este componente.", "pré-requisito ou correquisito"),
        ("Limite de carga horária do semestre excedido.", "limite de carga horária"),
        ("Este componente não permite matrícula on-line.", "matrícula on-line não permitida"),
        ("O período de matrícula extraordinária encerrado.", "período fechado"),
        ("Senha incorreta, tente novamente.", "dados de confirmação incorretos"),
        ("Sua sessão expirou, faça login novamente.", "sessão expirada"),
        ("Sistema indisponível, tente novamente mais tarde.", "indisponibilidade do sistema"),
        # Live capture 2026-09-16: the real "no remaining vacancies" search
        # response, verbatim.
        (
            "Não foram encontradas turmas abertas com vagas remanescentes "
            "para os parâmetros de busca especificados.",
            "sem vaga",
        ),
        # Live capture 2026-09-16: the two real validation errors caused by a
        # malformed search payload -- protocol failures, never pollable.
        (
            "form:comboDepartamento: Campo obrigatório não informado ou "
            "valor informado para o campo é inválido.",
            "parâmetros de busca inválidos",
        ),
        ("Por favor, escolha algum critério de busca", "parâmetros de busca inválidos"),
    ],
)
def test_classify_message_categories(text, expected):
    html = f"<html><body><div class='erro'>{text}</div></body></html>"
    assert classify_message(html) == expected


def test_classify_message_unknown_never_echoes_the_body():
    html = "<html><body><div class='erro'>Um erro totalmente novo e inesperado.</div></body></html>"
    result = classify_message(html)
    assert result == "resposta desconhecida"
    assert "inesperado" not in result


# --- fix round 1: classify_message/is_enrolled must never read whole-page
# text, only SIGAA's own message panels / the same table row (SPEC §22, §16).
# Regression fixtures reproduce real UFCG extraordinária SEARCH-page prose
# (div.descricaoOperacao) that contains "já está matriculado", "choque de
# horários" and the literal word "MATRICULADO" outside any message panel or
# bond table -- a real render, per capture 0003-search.html, 2026-09-15.


def test_classify_message_ignores_instructional_prose_outside_message_panels():
    html = _fixture("search_with_instructions.html")
    # the prose contains "já está matriculado" and "choque de horários": a
    # whole-page-text scan used to misclassify this ordinary search page.
    assert classify_message(html) != "já matriculado"
    assert classify_message(html) != "choque de horário"
    assert classify_message(html) == "resposta desconhecida"  # no message panel exists on this page


def test_is_enrolled_false_on_a_page_with_only_instructional_prose_no_table():
    assert is_enrolled(_fixture("search_with_instructions.html")) is False


def test_is_enrolled_ignores_the_literal_word_matriculado_outside_the_bond_row():
    # A page with a genuine bond table AND the instructional prose elsewhere:
    # the target's own row (1109103/02/MATRICULADO/2026.2) is still proof.
    assert is_enrolled(_fixture("enrolled_with_instructional_prose.html")) is True


def test_is_enrolled_false_when_prose_present_but_no_matching_bond_row():
    # Same prose, but the only table row is for a different component/turma:
    # the prose's stray "MATRICULADO" must never substitute for a real row.
    assert is_enrolled(_fixture("not_enrolled_with_instructional_prose.html")) is False

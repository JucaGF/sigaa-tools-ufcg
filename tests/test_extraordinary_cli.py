"""CLI surface for `matricula-extraordinaria`: safe defaults, fast config
validation (exit 5, before any session/keyring access), credential
resolution, and the JSON/log output contract.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sigaa import cli as cli_module
from sigaa.cli import _build_parser
from sigaa.extraordinary import RunResult


def _parse(*extra: str):
    return _build_parser().parse_args(["matricula-extraordinaria", *extra])


# --- argparse defaults and syntax errors (brief's own seed test) -------------


def test_extraordinary_defaults_are_safe():
    args = _build_parser().parse_args([
        "matricula-extraordinaria", "--codigo", "1109103", "--turma", "02",
    ])
    assert args.confirm is False
    assert args.watch is False
    assert args.interval == 20


def test_missing_required_arguments_is_an_argparse_error():
    with pytest.raises(SystemExit) as excinfo:
        _parse()
    assert excinfo.value.code == 2


def test_non_numeric_interval_is_an_argparse_error():
    with pytest.raises(SystemExit) as excinfo:
        _parse("--codigo", "1109103", "--turma", "02", "--interval", "abc")
    assert excinfo.value.code == 2


# --- config validation: exit 5, before any session/keyring access ------------


def _never_open_session(monkeypatch):
    """Fail the test if a UFCGSession is ever constructed."""

    def boom(*a, **k):
        raise AssertionError("must not open a session for a rejected config")

    monkeypatch.setattr(cli_module, "UFCGSession", boom)


def _never_touch_keyring(monkeypatch) -> dict:
    """Returns a flag dict; callers assert ``not flag["called"]`` afterward.

    The stub must prove it was never invoked on its own terms: raising
    AssertionError alone doesn't work here, because `_ufcg_username`/
    `_ufcg_secret` swallow any `Exception` from the keyring backend via a
    broad `except Exception`, so a raised AssertionError would be silently
    absorbed and the test would pass even if keyring *was* touched.
    """
    flag = {"called": False}

    def boom(*a, **k):
        flag["called"] = True
        raise AssertionError("must not touch keyring for a rejected config")

    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=boom))
    return flag


@pytest.mark.parametrize("codigo", ["1109104", "abc", ""])
def test_wrong_component_code_returns_five_before_any_session(monkeypatch, codigo):
    _never_open_session(monkeypatch)
    flag = _never_touch_keyring(monkeypatch)
    args = _parse("--codigo", codigo or "0", "--turma", "02")
    args.codigo = codigo
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5
    assert not flag["called"]


@pytest.mark.parametrize("turma", ["12", "02/01", "202", "01"])
def test_wrong_turma_returns_five_before_any_session(monkeypatch, turma):
    _never_open_session(monkeypatch)
    flag = _never_touch_keyring(monkeypatch)
    args = _parse("--codigo", "1109103", "--turma", turma)
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5
    assert not flag["called"]


@pytest.mark.parametrize("interval", [9, 0, -1, float("nan"), float("inf"), float("-inf")])
def test_interval_below_minimum_or_non_finite_returns_five(monkeypatch, interval):
    _never_open_session(monkeypatch)
    flag = _never_touch_keyring(monkeypatch)
    args = _parse("--codigo", "1109103", "--turma", "02")
    args.interval = interval
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5
    assert not flag["called"]


def test_global_user_override_returns_five(monkeypatch):
    _never_open_session(monkeypatch)
    flag = _never_touch_keyring(monkeypatch)
    args = _parse("--codigo", "1109103", "--turma", "02")
    args.user = "someone"
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5
    assert not flag["called"]


def test_confirm_reaches_the_worker_with_confirm_true(monkeypatch):
    # --confirm is now live (repo owner authorized the confirmation POST for
    # 1109103/02, SPEC §25 phase 3/§27.8/§28): it must reach
    # ExtraordinaryWorker.run as confirm=True instead of being blocked here.
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_password=lambda s, k: "jucag" if k == "__active_username__" else "s3cr3t"),
    )

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, **kwargs):
            pass

        def run(self, **kwargs):
            assert kwargs == {"confirm": True, "watch": False, "interval": 20.0}
            return RunResult("enrolled", "matrícula confirmada", 0)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02", "--confirm")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 0


def test_default_run_still_passes_confirm_false_to_the_worker(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_password=lambda s, k: "jucag" if k == "__active_username__" else "s3cr3t"),
    )

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, **kwargs):
            pass

        def run(self, **kwargs):
            assert kwargs == {"confirm": False, "watch": False, "interval": 20.0}
            return RunResult("prepared", "matrícula preparada (dry-run)", 0)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 0


def test_confirm_with_unresolvable_secret_returns_five_without_sending(monkeypatch):
    # Mirrors the worker-level guarantee (tests/test_extraordinary.py::
    # test_confirm_fails_with_exit_five_before_sending_when_secret_unresolvable)
    # at the CLI boundary: the worker fails closed with exit 5 before any
    # POST when a required confirmation secret (e.g. birth date) can't be
    # resolved, and the CLI must relay that exit code unchanged.
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_password=lambda s, k: "jucag" if k == "__active_username__" else "s3cr3t"),
    )

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, **kwargs):
            pass

        def run(self, **kwargs):
            assert kwargs["confirm"] is True
            return RunResult("error", "UFCG birth_date not configured", 5)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02", "--confirm")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5


def test_watch_alone_is_no_longer_rejected_and_reaches_the_worker(monkeypatch):
    # `--watch` used to return 5 unconditionally; it's now accepted and wired
    # through to the worker (`--confirm` is the flag that stays blocked).
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_password=lambda s, k: "jucag" if k == "__active_username__" else "s3cr3t"),
    )

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, **kwargs):
            pass

        def run(self, **kwargs):
            assert kwargs == {"confirm": False, "watch": True, "interval": 20.0}
            return RunResult("period_closed", "matrícula extraordinária period is not open", 2)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02", "--watch")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 2


def test_capture_inside_git_worktree_returns_five_before_any_session(monkeypatch):
    _never_open_session(monkeypatch)
    flag = _never_touch_keyring(monkeypatch)
    # This repo's checkout itself is inside its own git work tree.
    inside = str(Path(__file__).resolve().parents[1] / "some-capture-dir")
    args = _parse("--codigo", "1109103", "--turma", "02", "--capture", inside)
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5
    assert not flag["called"]
    assert not Path(inside).exists()


def test_capture_dir_non_empty_returns_five_before_any_session(tmp_path, monkeypatch):
    # Fix (review): a reused, populated --capture dir used to crash mid-flow
    # on the worker's O_EXCL write (counter restarts at 1). Refused up front.
    _never_open_session(monkeypatch)
    flag = _never_touch_keyring(monkeypatch)
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    (capture_dir / "0001-portal.html").write_text("leftover", encoding="utf-8")
    args = _parse("--codigo", "1109103", "--turma", "02", "--capture", str(capture_dir))
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5
    assert not flag["called"]


def test_capture_pointing_at_a_regular_file_returns_five_not_a_traceback(tmp_path, monkeypatch):
    # Round-2 review fix: path.exists() and any(path.iterdir()) raised an
    # uncaught NotADirectoryError when --capture pointed at a regular file.
    _never_open_session(monkeypatch)
    flag = _never_touch_keyring(monkeypatch)
    capture_path = tmp_path / "not-a-directory"
    capture_path.write_text("hello", encoding="utf-8")
    args = _parse("--codigo", "1109103", "--turma", "02", "--capture", str(capture_path))
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5  # must not raise
    assert not flag["called"]


def test_capture_dir_empty_or_absent_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_password=lambda s, k: "jucag" if k == "__active_username__" else "s3cr3t"),
    )

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, capture_dir=None):
            assert capture_dir is not None

        def run(self, **kwargs):
            return RunResult("period_closed", "matrícula extraordinária period is not open", 2)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    capture_dir = tmp_path / "does-not-exist-yet"
    args = _parse("--codigo", "1109103", "--turma", "02", "--capture", str(capture_dir))
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 2


# --- credentials: keyring service sigaa-ufcg, env fallback -------------------


def test_missing_username_returns_five_after_resolution(monkeypatch):
    _never_open_session(monkeypatch)
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=lambda *a: None))
    monkeypatch.delenv("SIGAA_USER", raising=False)
    args = _parse("--codigo", "1109103", "--turma", "02")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5


def test_blank_password_env_is_treated_as_missing_not_a_valid_empty_password(monkeypatch):
    # SIGAA_PASS="" (or whitespace) used to pass the `is None` guard, so a
    # blank password would have been POSTed. Isolated from real keyring/env.
    _never_open_session(monkeypatch)
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=lambda *a: None))
    monkeypatch.setenv("SIGAA_USER", "envuser")
    monkeypatch.setenv("SIGAA_PASS", "   ")
    args = _parse("--codigo", "1109103", "--turma", "02")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5


def test_ufcg_secret_treats_blank_or_whitespace_env_value_as_unset(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=lambda s, k: None))
    monkeypatch.setenv("SIGAA_PASS", "   ")
    assert cli_module._ufcg_secret("jucag", "password") is None


def test_ufcg_secret_returns_a_non_blank_value_unchanged(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=lambda s, k: None))
    monkeypatch.setenv("SIGAA_PASS", "s3cr3t")
    assert cli_module._ufcg_secret("jucag", "password") == "s3cr3t"


def test_missing_password_returns_five_after_resolution(monkeypatch):
    _never_open_session(monkeypatch)

    def get_password(service, key):
        if key == "__active_username__":
            return "jucag"
        return None  # password lookup misses

    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=get_password))
    monkeypatch.delenv("SIGAA_PASS", raising=False)
    args = _parse("--codigo", "1109103", "--turma", "02")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 5


def test_username_resolves_from_active_keyring_entry_then_password_from_username_entry(monkeypatch):
    store = {
        ("sigaa-ufcg", "__active_username__"): "jucag",
        ("sigaa-ufcg", "jucag"): "s3cr3t",
    }
    monkeypatch.setitem(
        sys.modules, "keyring", SimpleNamespace(get_password=lambda s, k: store.get((s, k)))
    )

    class FakeSession:
        def __init__(self, username, password):
            assert username == "jucag"
            assert password() == "s3cr3t"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, capture_dir=None):
            assert confirmation_secret("password") == "s3cr3t"

        def run(self, **kwargs):
            assert kwargs == {"confirm": False, "watch": False, "interval": 20.0}
            return RunResult("period_closed", "matrícula extraordinária period is not open", 2)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 2


def test_username_falls_back_to_env_when_keyring_backend_errors(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("backend unavailable")

    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=boom))
    monkeypatch.setenv("SIGAA_USER", "envuser")
    monkeypatch.setenv("SIGAA_PASS", "envpass")

    class FakeSession:
        def __init__(self, username, password):
            assert username == "envuser"
            assert password() == "envpass"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, capture_dir=None):
            pass

        def run(self, **kwargs):
            return RunResult("period_closed", "matrícula extraordinária period is not open", 2)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02")
    assert cli_module._cmd_matricula_extraordinaria(args, None) == 2


# --- output contract: JSON keys, exit codes, no secrets ----------------------


def test_json_output_has_exactly_the_documented_keys(monkeypatch, capsys):
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_password=lambda s, k: "jucag" if k == "__active_username__" else "s3cr3t"),
    )

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, *a, **k):
            pass

        def run(self, **kwargs):
            return RunResult("period_closed", "matrícula extraordinária period is not open", 2)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02", "--json")
    exit_code = cli_module._cmd_matricula_extraordinaria(args, None)

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {"status", "component_code", "class", "message"}
    assert payload["component_code"] == "1109103"
    assert payload["class"] == "02"
    assert payload["status"] == "period_closed"
    assert "exit_code" not in payload


def test_config_error_json_also_uses_the_documented_keys(monkeypatch, capsys):
    _never_open_session(monkeypatch)
    _never_touch_keyring(monkeypatch)
    args = _parse("--codigo", "1109103", "--turma", "02", "--json")
    args.codigo = "9999999"  # wrong component: config error, before any session
    exit_code = cli_module._cmd_matricula_extraordinaria(args, None)

    assert exit_code == 5
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {"status", "component_code", "class", "message"}


def test_secrets_never_appear_in_stdout_or_stderr(monkeypatch, capsys):
    store = {
        ("sigaa-ufcg", "__active_username__"): "jucag",
        ("sigaa-ufcg", "jucag"): "S3ntinelPW",
        ("sigaa-ufcg", "jucag:birth_date"): "S3ntinelBD",
    }
    monkeypatch.setitem(
        sys.modules, "keyring", SimpleNamespace(get_password=lambda s, k: store.get((s, k)))
    )

    class FakeSession:
        def __init__(self, username, password):
            assert password() == "S3ntinelPW"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, capture_dir=None):
            assert confirmation_secret("birth_date") == "S3ntinelBD"

        def run(self, **kwargs):
            return RunResult("error", "captura de resultados necessária", 6)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02", "--json")
    cli_module._cmd_matricula_extraordinaria(args, None)

    captured = capsys.readouterr()
    assert "S3ntinelPW" not in captured.out
    assert "S3ntinelPW" not in captured.err
    assert "S3ntinelBD" not in captured.out
    assert "S3ntinelBD" not in captured.err
    assert "jucag" not in captured.out
    assert "jucag" not in captured.err


def test_secrets_never_appear_in_stdout_or_stderr_on_the_confirm_path(monkeypatch, capsys):
    # Same guarantee as above, but with --confirm actually passed (the
    # previous test never did) and simulating a real enrolled/rejected
    # outcome, so the confirm=True path is the one under test here.
    store = {
        ("sigaa-ufcg", "__active_username__"): "jucag",
        ("sigaa-ufcg", "jucag"): "S3ntinelPW",
        ("sigaa-ufcg", "jucag:birth_date"): "S3ntinelBD",
    }
    monkeypatch.setitem(
        sys.modules, "keyring", SimpleNamespace(get_password=lambda s, k: store.get((s, k)))
    )

    class FakeSession:
        def __init__(self, username, password):
            assert password() == "S3ntinelPW"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class FakeWorker:
        def __init__(self, session, confirmation_secret, capture_dir=None):
            assert confirmation_secret("birth_date") == "S3ntinelBD"

        def run(self, **kwargs):
            assert kwargs["confirm"] is True
            return RunResult("enrolled", "matrícula confirmada", 0)

    monkeypatch.setattr(cli_module, "UFCGSession", FakeSession)
    monkeypatch.setattr(cli_module, "ExtraordinaryWorker", FakeWorker)
    args = _parse("--codigo", "1109103", "--turma", "02", "--confirm", "--json")
    cli_module._cmd_matricula_extraordinaria(args, None)

    captured = capsys.readouterr()
    assert "S3ntinelPW" not in captured.out
    assert "S3ntinelPW" not in captured.err
    assert "S3ntinelBD" not in captured.out
    assert "S3ntinelBD" not in captured.err
    assert "jucag" not in captured.out
    assert "jucag" not in captured.err


# --- main(): dispatch skips Settings() and UFPB overrides ---------------------


def test_main_does_not_construct_settings_for_matricula_extraordinaria(monkeypatch):
    monkeypatch.setattr(
        cli_module, "Settings", lambda: (_ for _ in ()).throw(AssertionError("Settings must stay untouched"))
    )

    def fake_cmd(args, settings):
        assert settings is None
        return 0

    monkeypatch.setattr(cli_module, "_cmd_matricula_extraordinaria", fake_cmd)
    assert cli_module.main(
        ["matricula-extraordinaria", "--codigo", "1109103", "--turma", "02"]
    ) == 0


def test_keyboard_interrupt_during_the_session_returns_130_with_a_non_generic_message(monkeypatch, capsys):
    # Dispatch stays inside main()'s existing try/except KeyboardInterrupt
    # (the brief's ruling); the command-specific message means
    # _cmd_matricula_extraordinaria must catch it itself, before that generic
    # handler ever sees it.
    monkeypatch.setattr(
        cli_module, "Settings", lambda: (_ for _ in ()).throw(AssertionError("Settings must stay untouched"))
    )
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(get_password=lambda s, k: "jucag" if k == "__active_username__" else "s3cr3t"),
    )

    class InterruptedSession:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            raise KeyboardInterrupt

        def __exit__(self, *exc):
            return None

    monkeypatch.setattr(cli_module, "UFCGSession", InterruptedSession)
    exit_code = cli_module.main(
        ["matricula-extraordinaria", "--codigo", "1109103", "--turma", "02"]
    )

    assert exit_code == 130
    err = capsys.readouterr().err
    assert "setup cancelled" not in err

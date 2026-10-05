import os

from spider.brain import EDIT_RE, apply_edit, make_diff, safe_target
from spider.legs import check_syntax, parse_pytest
from spider.personas import PERSONAS


def test_parse_pytest_pass():
    out = "....\n4 passed in 0.12s\n"
    assert parse_pytest(out, 0) == {"state": "pass", "passed": 4, "failed": 0, "test": "a test", "line": ""}


def test_parse_pytest_fail_finds_test_and_line():
    out = ("tests/test_auth.py:42: AssertionError\n"
           "FAILED tests/test_auth.py::test_login - assert 1 == 2\n"
           "1 failed, 3 passed in 0.2s\n")
    r = parse_pytest(out, 1)
    assert r["state"] == "fail" and r["test"] == "test_login" and r["line"] == "42"
    assert r["passed"] == 3 and r["failed"] == 1


def test_parse_pytest_no_tests():
    assert parse_pytest("no tests ran in 0.01s", 5)["state"] == "none"


def test_check_syntax(tmp_path):
    good, bad = tmp_path / "g.py", tmp_path / "b.py"
    good.write_text("x = 1\n")
    bad.write_text("def f(:\n    pass\n")
    assert check_syntax(str(good)) is None
    assert check_syntax(str(bad))[0] == 1


def test_safe_target_blocks_escape(tmp_path):
    assert safe_target(str(tmp_path), "pkg/mod.py").endswith(os.path.join("pkg", "mod.py"))
    assert safe_target(str(tmp_path), "../outside.py") is None
    assert safe_target(str(tmp_path), "/etc/passwd") is None
    assert safe_target("", "a.py") is None


def test_edit_block_parsed():
    text = "Here's the fix.\n```edit path=app/calc.py\ndef add(a, b):\n    return a + b\n```\nDone."
    m = EDIT_RE.search(text)
    assert m.group(1) == "app/calc.py" and "return a + b" in m.group(2)


def test_apply_edit_backs_up(tmp_path):
    f = tmp_path / "calc.py"
    f.write_text("def add(a, b):\n    return a - b\n")
    diff = make_diff(str(f), "def add(a, b):\n    return a + b\n", "calc.py")
    assert "-    return a - b" in diff and "+    return a + b" in diff
    backup = apply_edit(str(tmp_path), str(f), "def add(a, b):\n    return a + b\n")
    assert "a + b" in f.read_text()
    assert os.path.exists(backup) and "a - b" in open(backup).read()


def test_personas_have_every_line():
    events = ["welcome", "no_folder", "no_key", "pass", "fail", "fail_noline", "syntax", "no_tests",
              "thinking", "needs_approval", "approved", "rejected", "long_session", "idle", "error"]
    for p in PERSONAS.values():
        for e in events:
            assert p.say(e, n=3, test="t", line=1, file="f.py", hours=3, msg="m"), (p.key, e)


def test_provider_defaults_and_keys(tmp_path, monkeypatch):
    from spider import settings as cfg
    monkeypatch.setattr(cfg, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test-openai\nANTHROPIC_API_KEY=\n")
    s = dict(cfg.DEFAULTS)
    assert cfg.provider(s) == "openai" and cfg.model_for(s) == "gpt-5-mini"
    assert cfg.api_key("openai") == "sk-test-openai"
    assert cfg.api_key("anthropic") == ""
    s["provider"] = "anthropic"
    assert cfg.model_for(s) == "claude-sonnet-5-5"
    s["provider"] = "nonsense"
    assert cfg.provider(s) == "openai"


def test_openai_call_parses_edit(tmp_path, monkeypatch):
    import sys
    import types
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    reply = "Subtraction bug.\n```edit path=calc.py\ndef add(a, b):\n    return a + b\n```"
    seen = {}

    class FakeClient:
        def __init__(self, api_key):
            seen["key"] = api_key
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

        def create(self, model, messages):
            seen["model"], seen["system"] = model, messages[0]["content"]
            msg = types.SimpleNamespace(content=reply)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeClient))
    from spider.brain import Ask
    a = Ask("openai", "sk-x", "gpt-5-mini", "You are Nib.", [], "fix it", "ctx", str(tmp_path))
    out = {}
    a.answered.connect(lambda text, edit: out.update(text=text, edit=edit))
    a.run()     # run synchronously, no thread
    assert seen["key"] == "sk-x" and seen["model"] == "gpt-5-mini" and "You are Nib." in seen["system"]
    assert out["text"] == "Subtraction bug." and out["edit"]["rel"] == "calc.py"
    assert "+    return a + b" in out["edit"]["diff"]


def test_context_includes_tree_and_readme(tmp_path):
    from spider.brain import build_context
    (tmp_path / "README.md").write_text("# PaperTrail\nCited QA over ML papers.\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('hi')\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("")
    ctx = build_context(str(tmp_path), "", "", None)
    assert "app/main.py" in ctx and "Cited QA over ML papers" in ctx and "x.pyc" not in ctx
    assert "Choose project folder" in build_context("", "", "", None)

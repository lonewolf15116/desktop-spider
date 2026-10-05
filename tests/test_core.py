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

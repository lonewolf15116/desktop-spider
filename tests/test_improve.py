"""The improvement round: project tools, multi-file edits, the chat window, size and fade."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from spider.brain import parse_edits, run_tool
from spider.chat import display_text, segments


def _project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("import os\nTOKEN_NAME = 'x'\nprint('hi')\n")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-secret\n")
    (tmp_path / "notes.md").write_text("todo: TOKEN_NAME cleanup\n")
    return str(tmp_path)


def test_tools_read_list_and_search(tmp_path):
    root = _project(tmp_path)
    assert run_tool(root, "list_files", {}).splitlines() == ["app/", "notes.md"]
    out = run_tool(root, "read_file", {"path": "app/main.py", "start_line": 2, "end_line": 2})
    assert "TOKEN_NAME" in out and "import os" not in out
    hits = run_tool(root, "search_code", {"pattern": "token_name"})
    assert "app/main.py:2:" in hits and "notes.md:1:" in hits
    assert "notes.md" not in run_tool(root, "search_code", {"pattern": "token_name", "glob": "*.py"})


def test_tools_stay_inside_the_project_and_never_read_keys(tmp_path):
    (tmp_path / "proj").mkdir()
    root = _project(tmp_path / "proj")
    (tmp_path / "outside.txt").write_text("private")
    assert run_tool(root, "read_file", {"path": "../outside.txt"}) == "No such file inside the project."
    assert run_tool(root, "list_files", {"path": ".."}) == "Not a folder inside the project."
    assert "sk-secret" not in run_tool(root, "read_file", {"path": ".env"})
    assert "sk-secret" not in run_tool(root, "search_code", {"pattern": "sk-"})
    assert run_tool("", "list_files", {}) == "No project folder is selected."


def test_parse_edits_handles_several_files_and_refuses_escapes(tmp_path):
    root = _project(tmp_path)
    text = ("Two changes.\n```edit path=app/main.py\nprint('bye')\n```\n"
            "```edit path=app/new.py\nX = 1\n```\n```edit path=../evil.py\nboom\n```")
    clean, edits, ignored = parse_edits(text, root)
    assert clean == "Two changes."
    assert [e["rel"] for e in edits] == ["app/main.py", "app/new.py"]
    assert "+print('bye')" in edits[0]["diff"] and ignored == ["../evil.py"]


def test_streaming_display_hides_edit_bodies_and_memory_lines():
    raw = "Fix below.\n```edit path=a.py\nsecret body\n```\nremember: Likes tabs\nDone."
    shown = display_text(raw)
    assert "secret body" not in shown and "remember:" not in shown and "`a.py`" in shown
    half = display_text("Working…\n```edit path=b.py\nhalf a fi")
    assert "half a fi" not in half and "writing changes to `b.py`" in half


def test_segments_split_code_even_while_unclosed():
    md = "Try:\n```python\nprint(1)\n```\nthen\n```bash\nls -"
    assert segments(md) == [("text", "Try:"), ("code", "python", "print(1)"), ("text", "then"),
                            ("code", "bash", "ls -")]


def test_chat_window_streams_and_approves():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from spider.chat import ChatWindow, CodeBlock
    w = ChatWindow()
    w.style_for("zip", "Zip", "#f2a93b", "OpenAI · gpt-5-mini")
    w.open_chat()
    w.add_user("hi")
    w.begin_answer("Thinking…")
    w.stream("Here:\n```python\nprint(")
    w._render_pending()
    w.stream("Here:\n```python\nprint(1)\n```\nDone")
    w._render_pending()
    blocks = w.current.findChildren(CodeBlock)
    assert len(blocks) == 1 and blocks[0].body.toPlainText() == "print(1)"
    blocks[0]._copy()
    assert app.clipboard().text() == "print(1)"
    w.finish_answer("Here:\n```python\nprint(1)\n```\nDone")
    assert not w.busy and w.sendbtn.text() == "Send"
    got = []
    w.approved.connect(lambda: got.append("yes"))
    w.show_edits("Approve?", [{"rel": "a.py", "diff": "+x"}, {"rel": "b.py", "diff": "-y"}])
    assert w.mode == "approve" and w.yes.text() == "Approve all 2"
    w.yes.click()
    assert got == ["yes"]
    w.clear_edits()
    assert w.mode == "chat"


def test_every_persona_has_a_chat_style():
    from spider.personas import PERSONAS
    from spider import bubble, chat, memory_panel
    for key in PERSONAS:
        assert key in bubble.STYLES and key in chat.STYLES and key in memory_panel.STYLE
    assert list(PERSONAS)[0] == "zip"


def test_claude_streams_and_uses_tools(tmp_path, monkeypatch):
    import sys
    import types
    root = _project(tmp_path)
    calls = []

    class Stream:
        def __init__(self, texts, content):
            self.text_stream, self.content = iter(texts), content

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(content=self.content)

    class Messages:
        def stream(self, **kw):
            calls.append(kw)
            if len(calls) == 1:
                use = types.SimpleNamespace(type="tool_use", id="tu1", name="search_code", input={"pattern": "print"})
                return Stream(["Let me look. "], [types.SimpleNamespace(type="text", text="Let me look. "), use])
            return Stream(["It prints ", "hi."], [types.SimpleNamespace(type="text", text="It prints hi.")])

    class Client:
        def __init__(self, api_key):
            self.messages = Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    from spider.brain import Ask
    a = Ask("anthropic", "k", "claude-sonnet-5-5", "You are Zip.", [], "what runs?", "ctx", root)
    out = {}
    a.answered.connect(lambda t, e: out.update(text=t))
    a.run()
    assert calls[0]["tools"][0]["name"] == "list_files"
    result = calls[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and "app/main.py:3:" in result["content"]
    assert out["text"] == "Let me look.\n\nIt prints hi."

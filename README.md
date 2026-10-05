# Desktop Spider

A coding companion that lives in the corner of your screen. Its legs watch your project, it talks to Claude when you ask, and it never changes your code without your approval.

Two personas, switchable from the right-click menu:

- **Vesper**, the glass weaver: calm, precise, a little mysterious. Smoked glass with amber light.
- **Nib**, the ink familiar: warm, curious, cheeky. A hand-inked spider with glowing eyes.

Full persona sheet: [`docs/Desktop-Spider-Personas.docx`](docs/Desktop-Spider-Personas.docx).

## How it works

Every action takes one of three routes, shown by the colour of the spider's threads:

| Route | Colour | What runs |
|---|---|---|
| **code** | green | The legs. A syntax check on every save and your test command after it. Instant, no model calls. |
| **claude** | blue | Click the spider and ask. It sends your latest saved file and test output as context. |
| **you** | gold | Any file change Claude proposes is shown as a diff. Nothing is written until you press **Approve**. The old file is backed up to `.spider_backups/` first. |

## Run it (Windows)

1. Double-click `run_spider.bat`. The first run installs `PyQt5`, `anthropic` and `pytest` if they're missing.
2. To let it talk to Claude, open `.env` and set `ANTHROPIC_API_KEY=...`.
3. Right-click the spider → **Choose project folder…**.

Or from a terminal: `pip install -r requirements.txt`, then `python -m spider`.

## Controls

- **Click** to open the chat bubble. **Esc** closes it.
- **Drag** to move it. It snaps to the nearest screen corner.
- **Right-click** for persona, chattiness (silent, normal, talkative), focus mode, project folder, running tests, and quit.

Settings are saved in `settings.json`: persona, corner, accent colour, chattiness, watch folder, test command, active legs, model and long-session reminder hours.

## Develop

```
python -m pytest -q
```

## Roadmap

- More legs: a linter, git status, reading errors from your terminal.
- Parallel Claude agents, one per leg, each working in its own git worktree.
- A tray icon and a global shortcut to summon the chat.

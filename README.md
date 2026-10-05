# Desktop Spider

A coding companion that lives in the corner of your screen. Its legs watch your project, it talks to OpenAI or Claude when you ask, and it never changes your code without your approval.

Two personas, switchable from the right-click menu:

- **Vesper**, the glass weaver: calm, precise, a little mysterious. Smoked glass with amber light.
- **Nib**, the ink familiar: warm, curious, cheeky. A hand-inked spider with glowing eyes.

Full persona sheet: [`docs/Desktop-Spider-Personas.docx`](docs/Desktop-Spider-Personas.docx).

## How it works

Every action takes one of three routes, shown by the colour of the spider's threads:

| Route | Colour | What runs |
|---|---|---|
| **code** | green | The legs. A syntax check on every save and your test command after it. Instant, no model calls. |
| **model** | blue | Click the spider and ask OpenAI (default) or Claude. It sends your latest saved file and test output as context. |
| **you** | gold | Any file change the model proposes is shown as a diff. Nothing is written until you press **Approve**. The old file is backed up to `.spider_backups/` first. |

## Memory: it learns you

The spider keeps what it knows about you in `memory.json` next to the app. Nothing goes in without your yes:

- **You tell it.** Type `remember that I prefer short answers` in the chat. That's handled locally, with no model call.
- **It hears it.** When something you say in a chat sounds lasting (tools you like, how you want answers, what your projects are), it asks *"Shall I keep this thread?"* under the answer. **Remember** keeps it, **Not now** drops it.
- **It notices.** From your saves it spots patterns, like the hours you usually code or the project you return to. It offers at most one per day and never asks twice about the same thing.

Right-click → **Memory…** shows everything, each line with a **Forget** button. You can also add things, pause learning, or forget everything.

What it remembers is sent to your chosen model with every question, so the answers fit you. That's also why it refuses anything that looks like a key, password, token or card number. `memory.json` and `stats.json` are in `.gitignore`, so they stay on your machine.

## Run it (Windows)

1. Double-click `run_spider.bat`. The first run installs `PyQt5`, `openai`, `anthropic` and `pytest` if they're missing.
2. Open `.env` and paste your key after `OPENAI_API_KEY=`. To use Claude instead, fill in `ANTHROPIC_API_KEY=` and pick it from right-click → **Brain**.
3. Right-click the spider → **Choose project folder…**.

Or from a terminal: `pip install -r requirements.txt`, then `python -m spider`.

## Controls

- **Click** to open the chat bubble. **Esc** closes it.
- **Drag** to move it. It snaps to the nearest screen corner.
- **Right-click** for brain (OpenAI or Claude), memory, persona, chattiness (silent, normal, talkative), focus mode, project folder, running tests, and quit.

Settings are saved in `settings.json`: persona, corner, accent colour, chattiness, watch folder, test command, active legs, brain (`provider`, `openai_model`, `anthropic_model`) and long-session reminder hours.

## Develop

```
python -m pytest -q
```

## Roadmap

- Stage 2: legs beyond code, such as a daily work summary from git, reminders, a notes inbox and reading papers.
- Stage 3: always there. Start with Windows, a tray icon and a global shortcut.
- Stage 4: your other devices. Install on each device you choose, sync memory through a private store you own, pair devices with a code.

- More legs: a linter, git status, reading errors from your terminal.
- Parallel model agents, one per leg, each working in its own git worktree.

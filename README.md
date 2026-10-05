# Desktop Spider

A coding companion that lives in the corner of your screen. Its legs watch your project, it talks to OpenAI or Claude when you ask, and it never changes your code without your approval.

Three personas, switchable from the right-click menu:

- **Zip** (default), the jumping spider: quick, bright and upbeat. Charcoal fuzz, teal stripes and four big eyes. It drops in on a silk thread, does a backflip when your tests pass and slumps when they fail.
- **Vesper**, the glass weaver: calm, precise, a little mysterious. Smoked glass with amber light.
- **Nib**, the ink familiar: warm, curious, cheeky. A hand-inked spider with glowing eyes.

Full persona sheet: [`docs/Desktop-Spider-Personas.docx`](docs/Desktop-Spider-Personas.docx).

## How it works

Every action takes one of three routes, shown by the colour of the spider's threads:

| Route | Colour | What runs |
|---|---|---|
| **code** | green | The legs. A syntax check on every save and your test command after it. Instant, no model calls. |
| **model** | blue | Click the spider and ask OpenAI (default) or Claude. It starts with a project overview, your latest saved file and test output, and can read more of the project itself (see below). |
| **you** | gold | Any file change the model proposes is shown as a diff. Nothing is written until you press **Approve**. The old file is backed up to `.spider_backups/` first. |

## The chat window

Click the spider (or press **Ctrl+Alt+V**) to open a proper chat window. Move and resize it, and it opens in the same place next time.

- **Replies stream in** as they're written. **Stop** cuts one short.
- **Watch the legs pull.** At the top of the chat, every answer grows a web: one leg for each thing the spider pulls in, coloured by route. Green legs are pulled on your laptop: the project, your last file, test output, memory, and every file the model asks to read. Blue is the model writing. Gold legs are fixes waiting for your Approve. A leg is dashed while it pulls, goes solid when its thing lands, and snaps red if it fails (a file that isn't there, say). When the model asks for several files at once, the legs fetch them in parallel. After you approve a fix, one more leg brings back the test result.
- Code blocks have a **Copy** button.
- **It reads your project.** Before answering, the model can list folders, read files and search your code. You'll see what it's doing under the chat (for example *Reading app/api.py*). These tools are read-only, can't leave the project folder and never open `.env`.
- **Fixes that span files.** One answer can change up to 6 files. You get every diff in one card and choose **Approve all** or **Reject**.
- **Enter** sends, **Shift+Enter** adds a new line, **Esc** hides the window and **New chat** starts fresh.

The small bubble next to the spider is only for short remarks, like tests passing or a reminder. Click it to open the chat.

## Out of your way

- Right-click → **Size**: small (the default), medium or large.
- After 20 quiet seconds the spider fades to a ghost. It comes back when you hover over it, when tests run or fail, or when it has something to say. Turn this off with **Size → Fade when idle**.

## Memory: it learns you

The spider keeps what it knows about you in `memory.json` next to the app. Nothing goes in without your yes:

- **You tell it.** Type `remember that I prefer short answers` in the chat. That's handled locally, with no model call.
- **It hears it.** When something you say in a chat sounds lasting (tools you like, how you want answers, what your projects are), it asks *"Shall I keep this thread?"* under the answer. **Remember** keeps it, **Not now** drops it.
- **It notices.** From your saves it spots patterns, like the hours you usually code or the project you return to. It offers at most one per day and never asks twice about the same thing.

Right-click → **Memory…** shows everything, each line with a **Forget** button. You can also add things, pause learning, or forget everything.

What it remembers is sent to your chosen model with every question, so the answers fit you. That's also why it refuses anything that looks like a key, password, token or card number. `memory.json` and `stats.json` are in `.gitignore`, so they stay on your machine.

## Beyond code: tasks

Type these in the chat. They're handled on your laptop, without a model call:

| You type | It does |
|---|---|
| `note: buy printer ink` | Adds a dated line to `notes.md` (right-click → **Open notes**) |
| `remind me in 20 min to stretch` / `remind me at 6pm to call home` | Sets a reminder. The spider speaks up and the tray shows a notification. |
| `reminders` | Lists what's coming up |
| `summary` or `what did I do today?` | Today's commits, files touched and uncommitted work across your recent projects, plus reminders and notes |

Right-click → **Read a paper (PDF)…** extracts a paper's text and asks the model for a short summary covering the problem, idea, evaluation, headline result and a limitation, related to your projects where your memory makes that possible.

## Always there

- **Tray icon:** click it to talk. Right-click it for the full menu, so you can hide the spider and still reach it.
- **Ctrl+Alt+V** opens the chat from anywhere (Windows). If another app already owns it, the spider falls back to Ctrl+Alt+S, Ctrl+Alt+W and then Ctrl+Shift+Alt+S, and tells you which one it took. Set your own with `"hotkey"` in `settings.json`, e.g. `"ctrl+alt+k"`.
- Right-click → **Always there → Start with Windows** adds a small launcher to your Startup folder. Untick it to remove it.
- It remembers your last conversation and, after a break, says where you left off.
- Only one spider runs at a time, even if Windows starts one and you double-click the launcher too.

## Your other devices

**Shared memory.** Right-click → **Devices → Sync memory through a folder…** and pick a folder your cloud drive already syncs, such as OneDrive. Install the spider on another computer and point it at the same folder, and both share one memory. Anything you forget on one device is forgotten on all of them. Only `memory.json` goes there.

**Phone link.** Right-click → **Devices → Phone link**. With your phone on the same Wi-Fi, open the address the spider shows and enter the 6-digit pairing code. From the phone you can chat (with your memory and current project as context), add notes and reminders, see today's summary and run your tests.

Phone safety:
- It's off until you turn it on, and it's only reachable on your local network.
- A code works once, expires after 10 minutes, and is replaced after 5 wrong tries.
- Paired phones keep a private token, which the laptop stores only as a hash. **Unpair all phones** revokes them.
- Code changes and new memories are never approved from the phone; they wait on the laptop.
- The connection is plain HTTP on your home network, so don't turn it on over public Wi-Fi.

## Run it (Windows)

1. Double-click `run_spider.bat`. The first run installs `PyQt5`, `openai`, `anthropic`, `pypdf` and `pytest` if they're missing.
2. Open `.env` and paste your key after `OPENAI_API_KEY=`. To use Claude instead, fill in `ANTHROPIC_API_KEY=` and pick it from right-click → **Brain**.
3. Right-click the spider → **Choose project folder…**.

Or from a terminal: `pip install -r requirements.txt`, then `python -m spider`.

## Controls

- **Click** to open the chat window. **Esc** hides it.
- **Drag** to move it. It snaps to the nearest screen corner.
- **Ctrl+Alt+V** summons the chat from anywhere. The **tray icon** does the same. Right-click → **Always there** shows the shortcut in use.
- **Right-click** for today's summary, papers, notes, memory, devices, brain (OpenAI or Claude), persona, size and fade, chattiness (silent, normal, talkative), focus mode, project folder, running tests, and quit.

Settings are saved in `settings.json`: persona, size, fade when idle, corner, accent colour, chattiness, watch folder, test command, active legs, brain (`provider`, `openai_model`, `anthropic_model`), long-session reminder hours and where the chat window was.

## Develop

```
python -m pytest -q
```

## Your data stays yours

These files live next to the app and are all in `.gitignore`: `.env` (keys), `settings.json`, `memory.json`, `stats.json`, `notes.md`, `reminders.json`, `session.json` and `phone_devices.json`. Memory is sent to your chosen model with each question. Nothing else leaves your machine, except `memory.json` going to a sync folder you picked.

## Roadmap

- More legs: a linter, git status, reading errors from your terminal.
- Let the model run your tests itself (after asking you) to check its own fix before you approve it.
- Parallel model agents, one per leg, each in its own git worktree.
- HTTPS for the phone link, and approving code changes from the phone with a second confirmation on the laptop.

# mobile-agent-kit

A local agent that controls a real Android phone through natural language. It holds a conversation, remembers user preferences across sessions, and delegates multi-step tasks to VLM-driven skills that autonomously tap, type, and swipe on the device.

**Delivered capabilities (MVP)**

| Capability | How to trigger | Notes |
|---|---|---|
| Chat + memory | `python -m mobile_agent.app` | Extracts user preferences; persists across sessions |
| Publish Xiaohongshu note | Chat: "Post a Xiaohongshu note about X" | VLM autonomously completes the entire publish flow |
| Browse Xiaohongshu feed | Chat: "Scroll through two RedNote posts and summarize them" | VLM reads posts and returns key points |
| Emergency controls | Three buttons in the UI (bottom-right) | Stop / Home / Clear recents |

- Full architecture and design contracts: [`prd/手机Agent实现版PRD_副本.md`](prd/手机Agent实现版PRD_副本.md)
- Honest project retrospective (why I stopped investing further): [`docs/postmortem.md`](docs/postmortem.md)

---

## 1. First-time setup (fresh machine, fresh phone)

### 1.1 PC environment (Windows 10/11)

```powershell
# Python 3.10+ — install from python.org, check "Add to PATH"
python --version

# Install adb — pick one:
# A. Scoop (recommended)
irm get.scoop.sh | iex
scoop install adb

# B. Manual: download platform-tools from Google, extract to C:\platform-tools\, add to PATH

adb version    # verify
```

### 1.2 Phone setup

Enable developer options and USB debugging:

1. Settings → About phone → tap **Build number** 7 times → Developer options unlocked
2. In Developer options, enable all of the following:
   - **USB debugging**
   - **USB debugging (Security settings)** ← required for atx-agent
   - **Install via USB** ← required for ADBKeyboard
   - **Pointer location** (optional, useful for debugging)
3. Connect via USB cable (use the OEM data cable — charge-only cables won't work)
4. Tap **Allow** on the "Allow USB debugging?" popup on the phone; check **Always allow from this computer**

### 1.3 Project initialization

```powershell
cd path\to\mobile-agent-kit

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install langgraph langchain-core
```

> If `Activate.ps1` is blocked by execution policy, run first:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 1.4 Configure API key (store outside the project directory)

To ensure the key can never accidentally reach GitHub, store `.env` outside the repo:

```powershell
# Windows
$cfg = "$env:USERPROFILE\.config\mobile-agent"
New-Item -ItemType Directory -Force -Path $cfg | Out-Null
Copy-Item .env.example "$cfg\.env"
notepad "$cfg\.env"
```

```bash
# macOS / Linux
mkdir -p ~/.config/mobile-agent
cp .env.example ~/.config/mobile-agent/.env
$EDITOR ~/.config/mobile-agent/.env
```

Fill in `MOONSHOT_API_KEY`. Leave the model IDs at their defaults for now; the next step will confirm which models are available.

> Alternative: set `MOBILE_AGENT_ENV_FILE` to point to any `.env` path, or place `.env` directly in the project root (already in `.gitignore`, but not recommended).

### 1.5 Verify available Kimi models

```powershell
python scripts\verify_kimi_model.py
```

Copy the two recommended lines printed at the end (e.g., `MODEL_NAME=moonshot-v1-32k`) into your `.env`.

### 1.6 Push atx-agent to the phone

```powershell
python -m uiautomator2 init
```

No error on the last line means success.

### 1.7 Install ADBKeyboard APK (Chinese input over ADB)

```powershell
.\scripts\install_adbkeyboard.ps1
```

If the last line shows `[WARN] set IME manually:...`, go to:
> Settings → System → Language & input → Manage keyboards → enable **ADBKeyboard**

The agent automatically switches to ADBKeyboard when typing and restores the original IME after the task.

### 1.8 Five-point device health check

```powershell
python scripts\check_device.py
```

All `[ OK ]` is the goal. Up to two `[WARN]` entries are acceptable (ADBKeyboard not set as IME, or lock screen hiding the package name). Any `[FAIL]` must be resolved before proceeding.

---

## 2. Daily startup (phone already paired)

```powershell
# If adb is not in PATH, add it:
# $env:Path += ";C:\platform-tools"

.\.venv\Scripts\Activate.ps1
adb devices                    # should show:  <serial>  device
python -m mobile_agent.app
```

Browser opens automatically at http://127.0.0.1:7860.

### Device troubleshooting

| Symptom | Fix |
|---|---|
| `adb devices` shows nothing | Unplug and replug; watch for the popup on the phone |
| `unauthorized` | Tap **Allow** on the phone popup, check "Always allow" |
| `offline` | `adb kill-server; adb start-server`, then replug |
| Still `offline` | Developer options → Revoke USB debugging authorizations, replug, re-authorize |

---

## 3. UI walkthrough

```
┌──────────────────────────────┬──────────────────────────────┐
│                              │                              │
│  Left: chat                  │  Right: live phone screenshot│
│  - user messages             │                              │
│  - agent replies             │   ┌──────────────────┐       │
│  - "Running..." progress     │   │   step_NN.png    │       │
│                              │   └──────────────────┘       │
│  ┌────────────────────────┐  │                              │
│  │ input box              │  │  [🛑 Stop] [🏠 Home] [🧹 Clear]│
│  └────────────────────────┘  │                              │
│  [Send]    [Clear chat]      │                              │
└──────────────────────────────┴──────────────────────────────┘
```

**Left pane — chat**

Speak naturally; the agent routes your intent to the right skill automatically:

```
# Casual chat
"Hello"

# Trigger publish skill
"Post a Xiaohongshu note on the topic of solo elderly companionship"

# Trigger browse skill
"Scroll through two RedNote posts and give me the key takeaways"

# Set a long-term preference (auto-saved to memory)
"Always write my notes in a warm, conversational tone from now on"

# Cancel a running task
"Stop"
```

**Right pane — live screenshot**

Refreshes after each action so you can see exactly what the model is doing and where it might be stuck.

**Emergency buttons (bypass the agent, direct device control)**

| Button | Effect |
|---|---|
| 🛑 Stop | Sets the cancel token; waits for the current action to finish, then halts |
| 🏠 Home | Immediately presses the HOME key, regardless of any running task |
| 🧹 Clear recents | Opens the recents screen, clears all apps, returns to home |

---

## 4. Command-line entry points (no UI)

| Command | Purpose |
|---|---|
| `python -m mobile_agent.agent.cli` | CLI chat mode (no screenshot pane, no emergency buttons) |
| `python -m mobile_agent.skills.publish_xhs_text_note --theme=<topic>` | Invoke the publish skill directly, bypassing the agent |
| `python -m mobile_agent.skills.browse_xhs_posts --count=2` | Invoke the browse skill directly |
| `python scripts\manual_repl.py` | Interactive device REPL (screenshot / tap / Chinese text input) |
| `python scripts\check_device.py` | Five-point device health check |
| `python scripts\check_memory.py` | Inspect SQLite tables: conversations / tasks / facts / skills |
| `python scripts\cleanup_stale_tasks.py` | Remove tasks stuck in `running` state after a Ctrl+C interrupt |

---

## 5. Project structure

```
mobile_agent/
├── app.py              # Gradio UI entry point
├── constants.py        # Timeouts, retry caps, package names
├── config.py           # Reads .env
├── device/             # Action layer (uiautomator2 wrappers)
│   ├── device.py       #   Device main class
│   ├── vlm_loop.py     #   VLM autonomous action loop (semantic action set)
│   ├── ocr.py          #   OCR fallback (optional)
│   ├── vlm_finder.py   #   VLM coordinate fallback
│   ├── adb_keyboard.py
│   ├── lock.py         #   Device mutex lock
│   └── ui_tree.py
├── skills/             # Skill layer
│   ├── base.py
│   ├── publish_xhs_text_note.py
│   └── browse_xhs_posts.py
├── agent/              # LangGraph orchestration (5 nodes)
│   ├── graph.py
│   ├── nodes.py        #   load_context / route / chat / run_skill / cancel / summarize
│   └── cli.py
├── memory/             # SQLite long-term memory (4 tables)
│   ├── db.py           #   conversations / tasks / facts / skills
│   └── facts.py        #   Automatic long-term fact extraction
├── llm/
│   ├── kimi_client.py
│   └── prompts/        #   router / xhs_content / fact_extract
└── utils/
    ├── logger.py
    └── cancel.py       #   CancelToken

scripts/                # Ops and debug scripts
runs/                   # Task screenshots and logs (.gitignore)
data/                   # SQLite DB + downloaded APKs (.gitignore)
prd/                    # Design documents
```

---

## 6. Adding a new skill

Drop a `.py` file into `mobile_agent/skills/` following this skeleton:

```python
from pydantic import BaseModel, Field
from mobile_agent.skills.base import RunContext, SkillResult


class MyArgs(BaseModel):
    foo: str = Field(...)


class _MySkill:
    name = "my_skill"
    description = "One-line description shown to the agent router"
    args_schema = MyArgs

    def run(self, args: MyArgs, ctx: RunContext) -> SkillResult:
        # Use ctx.device to control the phone
        # Use mobile_agent.device.vlm_loop.run_vlm_loop for autonomous VLM-driven sequences
        return SkillResult(ok=True, summary="...", artifacts=[])


SKILL = _MySkill()
```

`autoload()` discovers and registers new skills automatically at startup — no changes needed elsewhere.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `adb devices` shows nothing | Cable is charge-only; swap for the OEM data cable |
| Garbled Chinese in PowerShell | Add `PYTHONUTF8=1` to `.env`, or use Windows Terminal |
| Intermittent errors with Chinese/spaces in path | Move the project to a short ASCII path like `C:\dev\mobile-agent` |
| ADBKeyboard installed but missing from `ime list -s` | Settings → Language & input → Manage keyboards → enable manually |
| OPPO phone: APK install fails with `[-99]` | Settings → Security → disable "Verify apps before installing"; or sign in to OPPO account |
| DB has tasks stuck at `running` after Ctrl+C | `python scripts\cleanup_stale_tasks.py` |
| Agent always routes to chat instead of a skill | Use more explicit phrasing, e.g. "Call publish_xhs_text_note to post …" |
| VLM stuck in a loop | Click 🛑 Stop in the UI; paste the log to analyze why the model got stuck |

---

## 8. Known limitations (v2 roadmap)

- **VLM convergence**: the model occasionally forgets the task is done after a successful publish and repeats actions. Stricter done-detection is needed.
- **Cancel latency**: the Stop button waits for the current HTTP request to complete. Moving to async execution would bring this to sub-second response.
- **Multi-device**: one lock, one device per process. Multi-device parallelism requires Redis.
- **Login / CAPTCHA**: automatic login is not supported; the Xiaohongshu account must already be signed in on the phone.
- **Image / video posts**: only plain-text notes are supported.

---

For the full design contract, anti-crash mechanism checklist, and phased delivery criteria, see [`prd/手机Agent实现版PRD_副本.md`](prd/手机Agent实现版PRD_副本.md).

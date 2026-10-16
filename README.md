<div align="center">

# FocusLedger

**A local-only work-session tracker that understands what you did, not just where you clicked.**

*It forgets what it saw. It only remembers what it meant.*

`Gemma 3 12B` · `Ollama` · `Apple Vision OCR` · `100% on-device` · `zero network`

</div>

---

## ⚡ Quick Start — Try Everything End-to-End in 60 Seconds

FocusLedger includes a one-command bootstrap script (`./start.sh`), a standalone macOS application bundle (`FocusLedger.app`), a native **Notch Onboarding Wizard**, and a **⚡ Quick Test (1m)** mode so you can experience the entire pipeline immediately:

```bash
# 1. One-command setup & launch (creates venv, builds Dictate.app & FocusLedger.app, starts Ollama, opens Notch)
./start.sh

# Or launch directly into the First-Run Onboarding Wizard:
./start.sh --onboarding

# Or launch in Quick Test mode (1-minute checkpoints, 2s polling):
./start.sh --quick

# Or double-click FocusLedger.app in Finder:
open FocusLedger.app
```

### How to Test the Full Loop in Under 1 Minute:
1. **Onboarding Check**: On first launch (or by clicking **`⚙ Setup`** in the notch), FocusLedger checks **Gemma 3 Local AI**, **Screen Capture & OCR**, and **On-Device Voice** inside the notch, with one-click buttons to start Ollama or open macOS Privacy settings. Click **`Continue →`**.
2. **Set Your Goals**: Click **`🎙 Speak goals`** to dictate on-device, type your goals, or click **`✨ Sample`** to fill sample goals in one click.
3. **Enable Quick Mode**: Make sure **`⚡ Quick 1m`** is selected, then click **`Start day`**. The notch smoothly collapses into slim status wings around your MacBook notch.
4. **Live Judgment & Report**: Work in any app for 15–30 seconds, click the notch, and click **`View report`**. FocusLedger immediately flushes your live buffer through Gemma #1 (`checkpoint()`), synthesizes the report with Gemma #2 (`daily_report()`), and opens your WHOOP-style report in the browser.
5. **Explore Full-Day Demo or Reset**:
   - Click **`Demo day`** in the notch to combine your real captured session with a full day of afternoon/evening sessions.
   - Click **`New day`** anytime to reset today's ledger and test setting new goals from scratch.

---

## The idea

Screen-time apps tell you *"3h 14m in Chrome."* Useless — they see the app, not the meaning.

FocusLedger runs **Gemma locally on your Mac**. It watches only while you're actually working, reads what's on screen with on-device OCR, and judges it against goals you set that morning. At the end of the day it hands you one report: what you did, whether it matched your intent, and what to fix tomorrow.

It **cannot** be a cloud product. Streaming your whole screen all day to an API is unaffordable, and nobody would consent to it. **Local open weights are the only reason this can exist.**

## Where Gemma is used — two distinct call sites

Remove Gemma and there is no product, only a screenshot folder. Both call sites live in [`gemma.py`](gemma.py).

1. **Per-block classification** (`checkpoint()`, prompt `CHECKPOINT_SYS`) — every 30 minutes (or 1 minute in `⚡ Quick 1m` mode, or on-demand when clicking `View report`) a batch of messy OCR samples + your goals become **one structured JSON verdict**: activity, category, which goal it served, aligned or not, confidence, evidence. Low temperature — a judge, not a poet.
2. **Whole-day synthesis** (`daily_report()`, prompt `REPORT_SYS`) — at end of day Gemma reads *only the ledger of verdicts* and writes the headline, executive coach assessment, tactical friction rule, per-goal progress, drift list, and tomorrow's actions.

## Architecture

```
SESSION MANAGER   idle_seconds() every 10s → active? idle?  (gates everything below)
      │ only runs while you're active
CAPTURE           frontmost app + title · screenshot only if screen changed · blocklist
      │
OCR               Apple Vision, on-device → text → DELETE IMAGE IMMEDIATELY
      │
BUFFER            ~30 min of text samples, in memory only (flushed on timer or SIGUSR1)
      │
GEMMA #1          checkpoint() → one JSON verdict → raw text discarded
      │
LEDGER            ledger.jsonl — verdicts only, never pixels or raw text
      │
GEMMA #2          daily_report() → WHOOP-style HTML report
```

Everything on disk is a verdict. No pixels, no raw text. Ever.

## Privacy by design

- **Session-gated** — polls macOS idle time (`ioreg HIDIdleTime`, no permissions). Captures only while you're active; idle time is never observed.
- **Images deleted the instant they're read** — a screenshot exists on disk for the length of one OCR call and no longer. `captures/` stays empty mid-run.
- **Raw text never persisted** — it lives in memory until the next checkpoint turns it into a verdict, then it's gone.
- **Blocklist** — password managers, Messages/Signal, and titles like *bank*, *login*, *checkout*, *private browsing* are refused outright.
- **Airplane mode still works** — every token runs on your laptop.

## Automated Verification Suite

Run the 14-check preflight suite at any time to verify Python dependencies, Ollama + Gemma model, `FocusLedger.app` & `Dictate.app` bundles, Screen Recording, Apple Vision OCR, prompt-injection resistance, and report rendering:

```bash
./start.sh --verify
```

## Files

| File | Role |
|---|---|
| [`start.sh`](start.sh) | One-command setup, dependency installer, & launcher |
| [`build_app.sh`](build_app.sh) | Builds the double-clickable `FocusLedger.app` macOS bundle |
| [`notch.py`](notch.py) | Dynamic notch companion — onboarding wizard, voice/text goals, live status, report controls |
| [`focusledger.py`](focusledger.py) | Session manager + capture loop + `SIGUSR1` live checkpoint flush |
| [`vision_ocr.py`](vision_ocr.py) | Apple Vision OCR; image deleted right after |
| [`gemma.py`](gemma.py) | Ollama client + both prompts, both schemas, & readiness checks |
| [`report.py`](report.py) | Ledger → Gemma synthesis → WHOOP-style HTML report |
| [`seed.py`](seed.py) | Demo evening/night sessions generator |
| [`verify_setup.py`](verify_setup.py) | 14-point automated preflight & verification suite |
| [`templates/report.html`](templates/report.html) | Jinja2 report template |
| `ledger.jsonl` | Your real activity — **gitignored** |
| [`ledger.sample.jsonl`](ledger.sample.jsonl) | Committed sample for instant demo preview |

## Libraries

Ollama · Gemma 3 12B · pyobjc (Vision, Quartz, AppKit) · mss · Jinja2 · requests

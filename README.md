<div align="center">
  <h1>FocusLedger</h1>
</div>

<div align="center">
  <h3>Tells you whether your day matched your goals, judged by a Gemma model that never leaves your Mac.</h3>
</div>

<div align="center">
  <img src="https://img.shields.io/badge/platform-macOS-black" alt="Platform: macOS">
  <img src="https://img.shields.io/badge/model-Gemma%203%20(1B%20%C2%B7%204B%20%C2%B7%2012B)-4285F4" alt="Model: Gemma 3, 1B, 4B or 12B">
  <img src="https://img.shields.io/badge/network-localhost%20only-brightgreen" alt="Network: localhost only">
</div>

<br>

<div align="center">
  <img src="docs/images/report-light.png" width="520" alt="FocusLedger daily report with focus score, time by category, goals and drift (sample data)">
  <br><sub>End-of-day report, rendered from the sample ledger.</sub>
</div>

<br>

Set your goals in the morning. While you work, FocusLedger OCRs your
focused window with Apple Vision, deletes the screenshot immediately,
and every 30 minutes asks a local Gemma model (via Ollama) whether that
block served a goal. At the end of the day you get one report. The only
network call is to `localhost:11434`.

```bash
git clone https://github.com/Aaryan1524/305Gemma-efficiencyproj.git
cd 305Gemma-efficiencyproj
./start.sh
```

> [!NOTE]
> You need [Ollama](https://ollama.com/download) installed. The model
> (0.8 to 8.1 GB) downloads from inside the app, only when you click
> **Download**.

## Setup

1. **Run `./start.sh`.** It creates `venv/`, installs packages, builds
   `Dictate.app` and `FocusLedger.app`, starts Ollama, and opens the
   notch. Safe to re-run.
2. **Click the notch.** The setup screen shows three cards; fix any that
   has a button.

   | Card | Button | Notes |
   |---|---|---|
   | On-device AI | Get Ollama / Start / Download | Pick Light, Balanced or Best below the cards. |
   | Screen reading | Allow | Turn it on for **Python** in System Settings, then **quit and reopen** the app. macOS applies it only to a new process. |
   | Voice goals | Build | Needs Xcode tools (`xcode-select --install`). Optional: you can type goals instead. |

3. **Continue**, enter goals (type or **Speak**), then **Start day**.
4. **Check it works:** in the `…` menu turn on **Test mode**, work for
   20 seconds, then **View report**. Or run `./start.sh --verify` for the
   14-check preflight.

<div align="center">
  <img src="docs/images/notch-setup.png" width="600" alt="Setup screen with on-device AI, screen reading and voice goals ready, and a Light, Balanced, Best model picker">
</div>

## Usage

| Control | Does |
|---|---|
| **Start day** | Tracks against today's goals. Collapses to a dot and timer. |
| **View report** | Judges what it has seen so far, opens the report. |
| **End day** | Final checkpoint, closes the session, opens the report. |
| `…` menu | Setup, model size, test mode, sample goals, demo report, new day, quit. |

Other commands: `./start.sh --quick` (test mode), `--onboarding`,
`--demo-report`, and `./venv/bin/python notch.py --install-login` to
launch at login.

## Models

| Size | Tag | Download | Notes |
|---|---|---|---|
| Light | `gemma3:1b` | 0.8 GB | Fastest. Keeps the JSON format but sometimes picks the wrong category. |
| Balanced | `gemma3:4b` | 3.3 GB | Good default for most Macs. |
| Best | `gemma3:12b` | 8.1 GB | Most reliable. Suits 16 GB or more. |

The default is chosen from your RAM. Your choice is saved in
`~/Library/Application Support/FocusLedger/config.json` and shared by
every process. `FL_MODEL=gemma3:4b ./start.sh` overrides it for one run.

## How it works

```
idle gate  →  focused window  →  OCR, delete image  →  Gemma verdict  →  ledger  →  report
(10s poll)    (app + title)      (Apple Vision)        (every 30 min)    (jsonl)    (Gemma synthesis)
```

- **Idle gate:** `ioreg HIDIdleTime` opens a session when you're active
  and closes it after 10 minutes idle, so idle time is never logged.
- **Verdicts:** `gemma.py` forces replies into a JSON schema, so text
  on screen can't hijack the classifier.
- **On disk:** `ledger.jsonl` (verdicts and session times, gitignored)
  and `config.json`. No pixels, no raw text.
- **Never captured:** 1Password, Keychain Access, Bitwarden, Messages,
  Signal, FaceTime, and windows titled bank, login, password, checkout,
  payment, incognito or private browsing (see `BLOCKED_*` in
  `focusledger.py`).

```
start.sh            setup + launcher         notch.py       notch UI
build_app.sh        builds FocusLedger.app   focusledger.py session manager + capture loop
build_dictate.sh    builds Dictate.app       gemma.py       Ollama client, prompts, model catalog
verify_setup.py     14-check preflight       report.py      ledger → report (templates/report.html)
seed.py             demo sessions            vision_ocr.py  Apple Vision OCR
```

Voice runs in a separate `Dictate.app` because macOS blames the parent
process for microphone access; a helper spawned by `python` dies with
`TCC_CRASHING_DUE_TO_PRIVACY_VIOLATION`. Launching it with `open` makes
it its own process.

## Known gaps

- **Apple Silicon, macOS 26 only tested.** Intel and older macOS are
  untested.
- **Permission shows as "Python".** `FocusLedger.app` is a launcher
  script, so macOS asks on behalf of Python. A signed, notarized build
  would fix it.
- **Single display.** Only the primary monitor is captured.
- **1B can misclassify.** Use 4B or 12B for results you'll act on.
- **Latency varies** (about 5 to 100 s per checkpoint), so **View
  report** can take a moment.
- **Keep `FocusLedger.app` inside the repo folder.** Moving the whole
  folder works; copying the `.app` alone does not.
- **The demo report mixes real and seeded data** (`seed.py`).

## Troubleshooting

```bash
./start.sh --verify                 # which check fails
curl -s localhost:11434/api/tags    # is Ollama up, which models exist
ollama list
```

**Screen reading says "Allow, then reopen app" after granting.** Quit
FocusLedger and launch it again. If it persists, check System Settings,
Privacy & Security, Screen & System Audio Recording for **Python**.

**Continue is dimmed.** AI or Screen reading isn't ready. Fix the card
with a button, then **Re-check**.

**Ollama isn't running and Start does nothing.** Open the Ollama app, or
run `ollama serve`, then **Re-check**.

**Model not downloaded and Download fails.** Run
`ollama pull gemma3:4b` yourself, then **Re-check**.

**Voice says "Not built yet".** Run `xcode-select --install` then
`./build_dictate.sh`, or type your goals.

**Report is empty or says "Gemma synthesis unavailable".** Ollama wasn't
reachable when it rendered. Start it and press **View report** again.

**Checkpoints time out.** A big model on a busy 8 GB Mac can exceed the
180 s limit. Switch to Balanced in the `…` menu.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.focusledger.notch.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/com.focusledger.notch.plist
rm -rf ~/Library/Application\ Support/FocusLedger
ollama rm gemma3:12b gemma3:4b gemma3:1b      # optional
cd .. && rm -rf 305Gemma-efficiencyproj
```

Then remove **Python** from Screen & System Audio Recording in System
Settings.

Built for the 305 SummerCodex Build with Gemma hackathon (FIU, July 24,
2026).

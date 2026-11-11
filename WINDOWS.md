# Running xconf on native Windows 11 (no WSL2, no Docker)

The lab runs on Windows 11 with nothing but **native Python** and the
built-in **PowerShell** — no WSL, no Docker, no Linux of any kind. This
guide covers the prerequisites, how to run it, and how to **package the
project so you can hand it to someone whose Windows 11 machine has no
WSL**.

---

## Prerequisites

| Requirement        | Notes                                                        |
|--------------------|--------------------------------------------------------------|
| **Python 3.10+**   | 3.11 or 3.12 recommended; 64-bit. From python.org or the Microsoft Store. |
| **pip**            | Bundled with the python.org installer.                       |
| **PowerShell 5.1** | Built into Windows 11 (PowerShell 7+ also works).            |
| Internet access    | Only for the one-time `pip install` of dependencies.         |

No C/C++ build tools are needed — all four dependencies (`flask`,
`requests`, `cbor2`, `aiocoap`) ship as pre-built Windows wheels, so
`pip install` just downloads them.

### Installing Python

Download from <https://www.python.org/downloads/windows/> and, in the
installer, **check "Add python.exe to PATH"**. Then open a *new*
PowerShell window and verify:

```powershell
python --version      # e.g. Python 3.12.x   (or:  py -3 --version)
pip --version
```

If `python` isn't found but you installed via python.org, use the `py`
launcher (`py -3 ...`); `run.ps1` understands both.

---

## Install the dependencies

From the project folder:

```powershell
pip install -r requirements.txt
```

(If you manage multiple projects, create a virtual environment first:
`python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt`.)

---

## Run

```powershell
.\run.ps1 start all     # starts netconf, restconf, coreconf, client
.\run.ps1 status
# open http://127.0.0.1:8080 in a browser
.\run.ps1 stop all
.\run.ps1 reset all
```

From `cmd.exe`, or by double-clicking, use the wrapper (it bypasses the
execution policy for you):

```bat
run.cmd start all
run.cmd status
run.cmd stop all
```

If PowerShell blocks `run.ps1`, allow it for the current shell only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Ports used: web UI **8080**, NETCONF **8300/tcp**, RESTCONF **8400/tcp**,
CORECONF **5683/udp**. Windows may show a Firewall prompt the first time —
"Allow access" on private networks is enough for local use.

---

## Packaging to share with a WSL-less Windows 11 machine

Because Docker Desktop on Windows relies on a WSL2 (or the deprecated
Hyper-V) backend, **don't ship the Docker image** to a machine that has no
WSL. Instead ship the **source**, which runs on native Python. Two
approaches:

### Option A — plain source zip (recipient has, or will install, Python)

This is the normal case and the smallest download. On your machine:

```powershell
# From the parent folder of the project, zip a clean copy (exclude the
# runtime 'state' folder and Python caches so it starts fresh).
Compress-Archive -Path .\xconf\* -DestinationPath .\xconf.zip
```

Or, to be sure no `state\` or `__pycache__\` is included, copy first:

```powershell
robocopy .\xconf .\xconf-share /E /XD state __pycache__ .git
Compress-Archive -Path .\xconf-share\* -DestinationPath .\xconf.zip
```

(On Linux/macOS the equivalent is:
`git archive --format=zip -o xconf.zip HEAD` from inside the repo, which
naturally excludes everything in `.gitignore`.)

The recipient then:

```powershell
# 1. Unzip xconf.zip
# 2. Install Python 3.10+ from python.org (tick "Add to PATH")
# 3. In the unzipped folder:
pip install -r requirements.txt
.\run.ps1 start all
# open http://127.0.0.1:8080
```

### Option B — fully offline bundle (recipient may have no internet)

If the target machine can't reach the internet to `pip install`, bundle
the dependency wheels alongside the source so installation is offline.

On a machine that *does* have internet (ideally a Windows box, so the
wheels match; otherwise add the `--platform` flags shown):

```powershell
# Download Windows wheels for all deps into a 'vendor' folder.
pip download -r requirements.txt -d .\xconf\vendor `
  --only-binary=:all: --platform win_amd64 --python-version 312
```

Then zip the project *including* `vendor\`. The recipient installs from
that folder with no network:

```powershell
pip install --no-index --find-links .\vendor -r requirements.txt
.\run.ps1 start all
```

> Tip: match `--python-version` to the Python the recipient will run
> (e.g. `311` or `312`). If you generate the wheels on the same Windows
> version the recipient uses, you can drop the `--platform` /
> `--python-version` flags entirely.

### What to include / exclude in the share

Include (everything needed to run):

```
README.md  WINDOWS.md  requirements.txt
run.ps1  run.cmd  run.py
yang\  common\  servers\  client\
(optional) vendor\      # only for the offline bundle (Option B)
```

Exclude (generated at runtime, not needed):

```
state\            # datastores, logs, pid files — recreated on first run
__pycache__\      # Python bytecode — regenerated on import
.git\             # version-control metadata
```

---

## Troubleshooting

- **`python` is not recognized** — reinstall Python with "Add to PATH"
  ticked, or use `py -3` (and `run.ps1` will pick it up automatically).
- **`run.ps1 cannot be loaded because running scripts is disabled`** —
  use `run.cmd ...`, or run
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.
- **A port is already in use** — something else is on 8080/8300/8400/5683.
  Stop it, or edit the `PORT`/`HOST` values in the server and `client`
  files (and the matching `CLIENT_URL` in `run.py` / `run.ps1`).
- **Browser can't reach the UI** — confirm `.\run.ps1 status` shows all
  four components `running`, and check `state\logs\client.log`.
- **pip can't find a wheel offline (Option B)** — the wheels in `vendor\`
  were built for a different Python version or architecture; regenerate
  with `--python-version`/`--platform` matching the target.

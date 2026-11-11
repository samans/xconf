# Reusable prompt: enable native-Windows execution for a project

A concise, project-agnostic prompt you can paste into an AI coding agent
to make an existing (typically Unix-developed) project run on **native
Windows 11 — no WSL, no Docker** — and to make it shareable with a
WSL-less machine. Edit the bracketed placeholders if your project differs.

---

## The prompt

> Make this project runnable on **native Windows 11 without WSL2 or
> Docker**, keeping the existing Unix/macOS workflow unchanged.
>
> 1. **Audit for Unix-only code.** Find anything that won't work on native
>    Windows — e.g. `os.fork` / `os.kill(pid, 0)` / `os.killpg` /
>    `os.getpgid` / `signal.SIGTERM` / `start_new_session`, hard-coded `/`
>    paths, `#!/bin/bash` scripts, and shell-outs to Unix tools. Report
>    what you find before changing it.
>
> 2. **Add a Windows launcher as separate files** (do not fork the
>    existing launcher with platform branches). Provide a `run.ps1`
>    PowerShell script that mirrors the existing launcher's verbs and
>    targets [e.g. start / stop / status / reset], using
>    `Start-Process -WindowStyle Hidden -PassThru` for background
>    processes, PID files for tracking, `taskkill /PID <pid> /T /F` to
>    stop, and `Get-Process` for status. Reuse the project's existing
>    cross-platform logic where possible (delegate to it rather than
>    reimplementing). Add a `run.cmd` wrapper that calls
>    `powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 %*` so it
>    works from `cmd.exe` without changing the execution policy.
>    Auto-detect the interpreter (`py -3`, then `python`, then `python3`).
>    Note: `Start-Process` needs separate files for stdout and stderr.
>
> 3. **Make any host bindings reachable.** If a service binds `127.0.0.1`,
>    make the bind host configurable via an environment variable so it
>    stays loopback by default but can be opened when needed. [Only if the
>    project has network services.]
>
> 4. **Document prerequisites and packaging** in a dedicated `WINDOWS.md`,
>    and add a short Windows section + link to the README:
>    - Prerequisites: the minimum language/runtime version (verify it
>      against the actual code and dependencies, don't guess), the package
>      manager, built-in PowerShell, and whether any build tools are
>      needed (check that all deps have pre-built Windows wheels/binaries).
>    - How to install deps and run via `run.ps1` / `run.cmd`, including the
>      `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` note.
>    - **Packaging to share with a WSL-less machine:** ship *source*, not
>      a Docker image (Docker Desktop needs a WSL2/Hyper-V backend).
>      Document (a) a plain source zip — `git archive --format=zip -o
>      app.zip HEAD`, or an equivalent that excludes generated/runtime
>      dirs — and (b) a fully **offline** bundle that vendors Windows deps:
>      `pip download -r requirements.txt -d vendor --only-binary=:all:
>      --platform win_amd64 --python-version <ver>` then `pip install
>      --no-index --find-links .\vendor -r requirements.txt`. List exactly
>      which files to include vs exclude.
>      [Adapt the dependency-vendoring commands to the project's ecosystem
>      if it isn't Python — e.g. `npm ci --offline` with a packed cache,
>      Go vendoring, etc.]
>
> 5. **Verify what you can, and be explicit about what you can't.** If you
>    cannot execute on Windows from the current environment, say so, and
>    still verify everything verifiable: syntax-check the scripts, confirm
>    any delegated/cross-platform command actually runs, and test that the
>    offline-download command produces `win_amd64` artifacts. Do not claim
>    the Windows path is tested if it wasn't run on Windows.
>
> Leave the existing Unix/macOS launcher untouched. Then update any
> project docs (README, a prompts/changelog file, and the knowledge base
> if one exists) to reflect the new Windows support.

---

## Why these specifics matter (rationale, optional to include)

- **Separate launcher files**, not platform `if` branches, keep each
  platform's logic readable and avoid breaking the working Unix path.
- **`taskkill /T`** terminates child processes too; a bare `Stop-Process`
  can orphan them.
- **Docker is not a Windows-without-WSL answer** — Docker Desktop's
  backend is WSL2 (or the deprecated Hyper-V), so a source bundle is the
  correct way to reach a truly WSL-less machine.
- **Offline wheel vendoring** (`pip download --platform win_amd64
  --python-version <ver>`) lets you build the shareable bundle from any
  OS, including Linux/CI, and still get correct Windows binaries.
- **Verify-or-disclose** avoids shipping an untested Windows script as if
  it were confirmed working.

---

## One-liner version

> Add native-Windows-11 support (no WSL/Docker): audit for Unix-only calls,
> add a separate `run.ps1` (+ `run.cmd` wrapper) mirroring the existing
> launcher via `Start-Process`/`taskkill`/`Get-Process`, make any
> `127.0.0.1` binds env-configurable, and write a `WINDOWS.md` covering
> prerequisites (verified min runtime version, no build tools if deps have
> Windows wheels) plus how to package for a WSL-less machine as a source
> zip and an offline vendored-deps bundle. Leave the Unix launcher as-is;
> verify what you can and state what you couldn't run on Windows.

# Peach Haven - Workspace Agent Guidelines

## Project Scope

This repository contains the reverse-engineering analysis, protocol recovery notes, a local dual-service Python compatibility server (HTTP SDK @ 8080 + Game TCP @ 21001), and a client relay patch toolkit for the mobile game *Peach Utopia* (蜜桃乌托邦, `com.IdolTime.Cards.game18`).

- **Workspace Root**: The directory containing `server/`, `tools/`, `docs/`, `tests/`, and root runner scripts.
- **Target Package Name**: `com.IdolTime.Cards.game18`
- **Project Name**: Peach Haven
- **Target Game Name**: Peach Utopia (蜜桃乌托邦)
- **License**: GNU General Public License v3.0 (GPL-3.0)

## Important Boundaries & Compliance

- **No Proprietary Binaries**: Do not bundle, ship, or commit original game APK binaries, proprietary art assets, or audio files (`*.apk`, `*.zip`, `build/`, and `dist/` are gitignored).
- **Client Patch Toolkit**: The one-click patch tool (`patch.ps1`) strictly operates on user-provided original APK paths and exports to `dist/`.
- **YooAsset / HotUpdate Isolation**: Treat `pxcdn.jhdwxp.com` as the upstream CDN host. Keep hot-update traffic separate from local SDK/TCP servers.
- **Privacy & Desensitization**: Never hardcode personal developer usernames, machine-specific absolute file paths, private IP addresses (use `127.0.0.1` or `192.168.1.100`), or real user credentials.
- **Non-Destructive Git Rule**: Do not execute destructive Git commands such as `git reset --hard` on public branches.

## Directory Layout

### Input & Analysis Directories (Read-Only)
- `decoded/` — Decompiled assets and manifests (analysis input, gitignored)
- `decoded_smali_20260822/` — Smali bytecode reverse-engineering tree (analysis input, gitignored)
- `files/` — Runtime YooAsset cache and IL2CPP metadata dumps (analysis input, gitignored)

### Output & Workspace Artifacts
- `server/` — Python local server source code (FastAPI HTTP + AsyncIO Game TCP)
- `server/data/` — SQLite databases (`app.db`), captures, and logs (gitignored)
- `tools/` — Helper scripts and APK relay patch toolkit source
- `build/` — Build intermediates, keystores, and decompiled work trees (gitignored)
- `dist/` — Final exported signed APK and SHA-256 artifacts (gitignored)
- `docs/` — Structured technical reverse-engineering and architecture documentation
- `tests/` — Automated test suite and regression tests
- `.tools/` — Local third-party utilities and Android build-tools (gitignored)
- `.cache/` — Pip and build caches (gitignored)

## One-Click Entry Points
- `patch.ps1` — One-click APK patch and signature pipeline
- `start.ps1` — One-click background launcher for HTTP SDK and Game TCP servers
- `stop.ps1` — One-click process termination for local servers
- `manage.ps1` — Passthrough CLI to `python -m server.cli`

## Code & Editing Standards

- Use structured parsers for JSON, SQLite, Protobuf wire bytes, and APK metadata where practical.
- Use relative paths exclusively across all code, scripts, documentation, and markdown links.
- Prefer ASCII for code identifiers and file paths; use Chinese in documentation for clarity.
- Maintain test coverage across `tests/` whenever changing server protocol or game state models.

## Server Validation Commands

Run from the workspace root:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server tests tools
python -m server.client
```

- **HTTP SDK Server**: FastAPI / Uvicorn on `0.0.0.0:8080`, AES-128-ECB encrypted endpoints.
- **Game TCP Server**: AsyncIO TCP server on `0.0.0.0:21001`, 10-byte binary framing.
- **Default Test Account**: `test / test1234`.

## Evidence Confidence Rules

Every reverse-engineering finding must be marked with one of:
- **Confirmed by static analysis** — verified from smali, decompiled C#, or manifest declarations.
- **Confirmed by packet capture or runtime observation** — verified from pcap, reconstructed TCP frames, or device logcat.
- **Inferred and still requiring validation** — derived from naming conventions or incomplete traces.

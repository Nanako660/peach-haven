# Peach Haven

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

<p><b>Local compatibility server & client patch toolkit for the mobile game <i>Peach Utopia</i> (蜜桃乌托邦 / <code>com.IdolTime.Cards.game18</code>)</b></p>

<h2 style="color: #ff3333;">⚠️ DISCLAIMER</h2>
<p style="color: #ff4d4f; font-weight: bold; font-size: 1.15em;">
  This project is developed solely for reverse engineering, network protocol analysis, and academic research purposes.<br>
  It does NOT provide, bundle, or distribute any proprietary game assets (APK binaries, artwork, audio, or commercial code).<br>
  Commercial use or monetization is strictly prohibited.<br>
  This project is a milestone research artifact and will NOT be continuously maintained or updated.
</p>

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Protocol: AES--128--ECB](https://img.shields.io/badge/SDK_Auth-AES--128--ECB-orange.svg)](docs/analysis/sdk-network-protocol.md)
[![Status: Research](https://img.shields.io/badge/Status-Research%20%2F%20Experimental-lightgrey.svg)](#feature-support-matrix)

</div>

> [!CAUTION]
> **Legal Notice**: This project is personal amateur research on reverse engineering and communication protocol compatibility. This repository **does NOT contain, provide, or distribute** original game APK binaries or copyrighted assets. Users who wish to utilize the client patch toolkit must supply their legally obtained original game packages. This project represents a milestone technical exploration and is **not committed to long-term maintenance or continuous updates**.

---

## Table of Contents

- [About The Project](#about-the-project)
- [Architecture & Core Features](#architecture--core-features)
- [Feature Support Matrix](#feature-support-matrix)
- [Project Directory Structure](#project-directory-structure)
- [Prerequisites & Environment](#prerequisites--environment)
- [Quick Start Guide](#quick-start-guide)
  - [1. Install Python Dependencies](#1-install-python-dependencies)
  - [2. One-Click Client Patch (Optional)](#2-one-click-client-patch-optional)
  - [3. Start Local Servers](#3-start-local-servers)
  - [4. Server Management CLI](#4-server-management-cli)
  - [5. Run Test Suite](#5-run-test-suite)
- [Network Protocol & Technical Design](#network-protocol--technical-design)
  - [1. SDK HTTP Protocol](#1-sdk-http-protocol)
  - [2. Game TCP Binary Protocol](#2-game-tcp-binary-protocol)
  - [3. YooAsset & HotUpdate Boundary](#3-yooasset--hotupdate-boundary)
- [Comprehensive Documentation Index](#comprehensive-documentation-index)
- [License](#license)

---

## About The Project

**Peach Haven** is a localized compatibility server suite designed for the Unity IL2CPP mobile card game *Peach Utopia* (蜜桃乌托邦, `com.IdolTime.Cards.game18`). Through static decompilation, runtime analysis, and packet capture reconstruction, the project restores the game's AES-encrypted SDK authentication protocol and proprietary TCP gameplay protocol. It provides a dual-service Python backend (FastAPI HTTP + AsyncIO TCP) and an automated client patch pipeline capable of running fully offline or in local area networks.

---

## Architecture & Core Features

The system consists of three main components operating in synergy:

```
+-------------------------------------------------------------+
|                  Peach Haven Architecture                   |
+-------------------------------------------------------------+
|                                                             |
|  +---------------------+        +------------------------+  |
|  |  HTTP SDK Server    |        |    Game TCP Server     |  |
|  |  (FastAPI @ 8080)   |        |  (AsyncIO @ 21001)     |  |
|  +----------+----------+        +-----------+------------+  |
|             |                               |               |
|             | AES-128-ECB Login/Token/Order | 10-Byte Binary|
|             | Server List & Virtual Wallet  | Startup/Battle|
|             v                               v               |
|  +-------------------------------------------------------+  |
|  |          SQLite Data Persistence (server/data/app.db) |  |
|  |   - User Accounts & PBKDF2 Password Hashes            |  |
|  |   - Virtual G-Point Wallet & Transaction Logs         |  |
|  |   - Character States (Level, Gold, Stamina, Diamonds) |  |
|  |   - Bag/Inventory Deltas & Lineup Presets             |  |
|  +-------------------------------------------------------+  |
|                                                             |
|  +-------------------------------------------------------+  |
|  |        Local Relay APK Patch Pipeline (patch.ps1)     |  |
|  |   - SDK Domain Convergence to 127.0.0.1:8080          |  |
|  |   - Injected classes3.dex Overlay & Lifecycle Hooks   |  |
|  +-------------------------------------------------------+  |
+-------------------------------------------------------------+
```

1. **HTTP SDK Compatibility Server (`FastAPI @ 0.0.0.0:8080`)**:
   - Emulates the game SDK's AES-128-ECB encrypted communication protocol.
   - Handles account registration, login, guest login, token validation, version check, and server list dispatch.
   - Built-in virtual wallet and simulated payment processing with automatic G-point top-up for local testing.
2. **Game TCP Compatibility Server (`AsyncIO @ 0.0.0.0:21001`)**:
   - Implements 10-byte big-endian framing and TCP stream defragmentation.
   - Supports handshake and startup frame sequences (`3 -> 4 -> 25/26/27/28`) for seamless game entry.
   - Persistent player character state model supporting stamina, currency, bag item deltas, lineups, and gacha.
3. **Client Relay Patch Toolkit (`patch.ps1`)**:
   - Automates decompilation, points SDK endpoints to `127.0.0.1:8080`, injects floating debug overlay and custom Dex extensions, and performs zipalign and resigning.
4. **Unified Management CLI (`server.cli` / `manage.ps1`)**:
   - Offers service health checks, real-time log monitoring, account/password management, virtual wallet crediting, and fixture inspection.

---

## Feature Support Matrix

| Module | Feature / Endpoint | Status | Description |
| :--- | :--- | :---: | :--- |
| **SDK Auth** | Registration / Password Login (`/api/sdk/Login/*`) | ✅ Supported | PBKDF2 hash storage with duplicate account validation |
| **SDK Auth** | Quick Guest Login / Token Validation (`validateToken`) | ✅ Supported | Session token issuance with expiration management |
| **SDK Auth** | Single Game Verification (`singleGameVerify`) | ✅ Supported | Game server authorization handshake |
| **SDK Analytics** | Client Tracking (`system/gameTrack`) | ✅ Supported | Ingests and stores client telemetry events |
| **SDK Billing** | Simulated Billing & Spending (`spend/create2`) | ✅ Supported | Deducts virtual G-points and fulfills in-game orders |
| **Game TCP** | 10-Byte Header & TCP Stream Reassembly | ✅ Supported | Handles sticky packets and concurrent stream frames |
| **Game TCP** | Startup Sequence (`3 -> 4 -> 25/26/27/28`) | ✅ Supported | Allows real game client to enter main town interface |
| **Game TCP** | Character Attributes (Stamina/Gold/Diamond/Level) | ✅ Supported | Persisted in SQLite with dynamic client sync |
| **Game TCP** | Hero Management & Lineup Presets (`lineup`) | ✅ Supported | Default team rosters and custom formation saving |
| **Game TCP** | Bag System (`bag delta`) | ✅ Supported | Item addition, quantity modification, and consumption |
| **Game TCP** | Gacha / Card Recruitment | 🟡 Basic | Protocol flow supported; RNG weighting in progress |
| **Game TCP** | Stage Battle & Reward Settlement | 🟡 Basic | Progress tracking supported; drop rules in progress |
| **Client Tools** | One-Click APK Patch & Re-signing | ✅ Supported | Interactive or parameterized pipeline via `patch.ps1` |
| **Assets & CDN** | YooAsset / HotUpdate Asset Delivery | ⏸️ Upstream | Isolates CDN traffic to upstream `pxcdn.jhdwxp.com` |

---

## Project Directory Structure

```text
peach-haven/
├── server/                     # Python local server backend
│   ├── main.py                 # HTTP SDK (FastAPI) entry point
│   ├── game_tcp.py             # Game TCP (AsyncIO) entry point
│   ├── game_proto.py           # TCP binary framing & parsing
│   ├── game_state.py           # Game state model & delta persistence
│   ├── crypto.py               # SDK AES-128-ECB crypto module
│   ├── storage.py              # SQLite database persistence layer
│   ├── products.py             # In-game product & pricing map
│   ├── startup_template.py     # Startup frame templates
│   ├── cli.py                  # CLI management suite
│   ├── client.py               # Smoke test Python client
│   └── config.toml.example     # Configuration template
├── tools/                      # Reverse engineering & helper scripts
│   ├── apk-relay/              # Relay APK patch scripts & Java source
│   ├── analyze_game_tcp_pcap.py # TCP pcap dissection utility
│   └── recover_game_tcp_protocol.py # Protocol schema recovery tool
├── docs/                       # Technical analysis and design docs
│   ├── README.md               # Documentation directory index
│   ├── analysis/               # Decompilation & pcap dissection docs
│   ├── implementation/         # Server & patch design specifications
│   ├── decisions/              # Architecture Decision Records (ADRs)
│   ├── evidence/               # End-to-end device testing evidence
│   └── todo/                   # Compatibility task list & roadmap
├── tests/                      # Automated unit test suite
├── patch.ps1                   # One-click client patch script
├── start.ps1                   # One-click dual-server launcher
├── stop.ps1                    # One-click server termination script
├── manage.ps1                  # Pass-through CLI helper script
├── requirements.txt            # Python dependencies manifest
├── LICENSE                     # GNU General Public License v3.0
├── TODO.md                     # Roadmap & task tracking
├── README.zh-CN.md             # Chinese documentation
└── README.md                   # English documentation (this file)
```

---

## Prerequisites & Environment

Running this project requires:

1. **Operating System**: Windows 10/11 or Linux / macOS (PowerShell 7+ / Bash).
2. **Python**: Python 3.10 or higher.
3. **Java JDK** (only needed when using the client patch tool): JDK 11 or JDK 17.
4. **Android SDK Build-Tools** (only needed when using the client patch tool): `d8`, `zipalign`, `apksigner` (on PATH or inside `.tools/`).

---

## Quick Start Guide

### 1. Install Python Dependencies

It is recommended to use a Python virtual environment:

```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# Or Linux / macOS:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. One-Click Client Patch (Optional)

> Required if connecting a physical device or emulator to the local compatibility server.

Prepare your legally obtained original APK file:

```powershell
# Interactive mode (prompts for the APK path)
.\patch.ps1

# Or specify the original APK path directly
.\patch.ps1 -Apk ".\com.IdolTime.Cards.game18.apk"

# Force clean intermediate caches and re-decode
.\patch.ps1 -Clean -Apk ".\com.IdolTime.Cards.game18.apk"
```

The signed APK will be output to `dist/com.IdolTime.Cards.game18-local-relay-v3.apk`, ready for installation.

### 3. Start Local Servers

Launch both HTTP (8080) and TCP (21001) services in the background:

```powershell
# Start both servers
.\start.ps1
```

The console will display the local network addresses. To run servers individually in the foreground for debugging:

```powershell
# Run HTTP SDK server
python -m server.main

# Run Game TCP server
python -m server.game_tcp
```

### 4. Server Management CLI

Manage the backend using `manage.ps1` or `python -m server.cli`:

```powershell
# View running status and port bindings
.\manage.ps1 status

# Run health check for both services
.\manage.ps1 health

# Stream server logs
.\manage.ps1 logs

# List registered accounts
.\manage.ps1 account list

# Create a test account
.\manage.ps1 account create test test1234

# Credit virtual G-points for simulated billing
.\manage.ps1 account credit test 10000

# Stop local servers
.\stop.ps1
```

Default test credentials: `test` / `test1234`.

### 5. Run Test Suite

Run the full automated test suite covering crypto, state machines, and billing idempotency:

```powershell
# Run unit tests
python -m unittest discover -s tests -v

# Run standalone end-to-end Python client smoke test
python -m server.client
```

---

## Network Protocol & Technical Design

### 1. SDK HTTP Protocol

- **Encryption**: AES-128-ECB mode with PKCS7 padding, Base64 encoded.
- **Envelope Structure**: Request bodies contain encrypted JSON with `device_id`, `token`, and timestamp payload.
- **Specification**: See [`docs/analysis/sdk-network-protocol.md`](docs/analysis/sdk-network-protocol.md).

### 2. Game TCP Binary Protocol

- **Frame Layout**:
  ```
  +-------------------+-------------------+-------------------+-------------------+------------------------+
  |  TotalLen (4B BE) |   MsgId (2B BE)   |   SeqId (4B BE)   |   Reserved (2B)   |   Protobuf / Body...   |
  +-------------------+-------------------+-------------------+-------------------+------------------------+
  ```
- **Core Handshake**:
  - `CSLoginReq (MsgId=3)`: Client initiates login with SDK token.
  - `SCLoginAck (MsgId=4)`: Server returns session acknowledgment and character metadata.
  - `SCStartupInfo (MsgId=25~27)`: Downlinks hero collection, equipment, and quest progress.
  - `SCStartupInfoEndNtf (MsgId=28)`: Signals startup completion, unlocking main UI.
- **Specification**: See [`docs/analysis/recovered-game-tcp-protocol.md`](docs/analysis/recovered-game-tcp-protocol.md).

### 3. YooAsset & HotUpdate Boundary

Packet capture confirms upstream CDN host `pxcdn.jhdwxp.com`. By architectural decision, **hot update traffic is kept with upstream CDN servers**, while the local compatibility server handles auth, accounts, and gameplay logic. See [`docs/decisions/001-local-sdk-original-hotupdate.md`](docs/decisions/001-local-sdk-original-hotupdate.md).

---

## Comprehensive Documentation Index

All reverse engineering analyses, protocol structures, and test logs are documented in `docs/`:

| Category | Document | Description |
| :--- | :--- | :--- |
| **Index** | [`docs/README.md`](docs/README.md) | Master documentation index and findings summary |
| **Static Analysis** | [`docs/analysis/apk-overview.md`](docs/analysis/apk-overview.md) | APK structure, Unity IL2CPP, assemblies, and YooAsset cache |
| **Protocol Analysis** | [`docs/analysis/sdk-network-protocol.md`](docs/analysis/sdk-network-protocol.md) | SDK HTTP API schema and AES-128 crypto specification |
| **Protocol Analysis** | [`docs/analysis/sdk-domain-manager.md`](docs/analysis/sdk-domain-manager.md) | Domain cache resolution and fallback mechanisms |
| **Protocol Analysis** | [`docs/analysis/client-payment-chain-analysis.md`](docs/analysis/client-payment-chain-analysis.md) | Billing callbacks, virtual wallet, and order fulfillment |
| **TCP Analysis** | [`docs/analysis/game-tcp-capture-analysis-20260823.md`](docs/analysis/game-tcp-capture-analysis-20260823.md) | Analysis of real client TCP startup sequence |
| **TCP Analysis** | [`docs/analysis/gameplay-tcp-capture-20260823.md`](docs/analysis/gameplay-tcp-capture-20260823.md) | In-game battle, settlement, lineup, and gacha captures |
| **TCP Analysis** | [`docs/analysis/recovered-game-tcp-protocol.md`](docs/analysis/recovered-game-tcp-protocol.md) | Recovered TCP header framing and Message ID definitions |
| **Implementation** | [`docs/implementation/local-server.md`](docs/implementation/local-server.md) | Python server architecture and SQLite data storage design |
| **Implementation** | [`docs/implementation/game-state-model.md`](docs/implementation/game-state-model.md) | Game state machine and incremental bag delta synchronization |
| **Implementation** | [`docs/implementation/local-relay-apk.md`](docs/implementation/local-relay-apk.md) | Client relay patch design and classes3.dex injection |
| **Tooling** | [`tools/README.md`](tools/README.md) | Comprehensive toolchain catalog & upstream repository references |
| **Tooling** | [`tools/apk-relay/README.md`](tools/apk-relay/README.md) | Automated APK patching pipeline tool guide |
| **Decisions** | [`docs/decisions/001-local-sdk-original-hotupdate.md`](docs/decisions/001-local-sdk-original-hotupdate.md) | Architectural decision on local SDK + upstream CDN isolation |
| **Evidence** | [`docs/evidence/p0-1-device-e2e-20260823.md`](docs/evidence/p0-1-device-e2e-20260823.md) | Physical device / emulator end-to-end validation report |
| **Roadmap** | [`docs/todo/server-compatibility-todo.md`](docs/todo/server-compatibility-todo.md) | Compatibility task breakdown and acceptance criteria |

---

## License

This project is licensed under the **[GNU General Public License v3.0 (GPL-3.0)](LICENSE)**.

- This codebase is intended strictly for security research, protocol analysis, and academic study.
- Commercial hosting, unauthorized private server operation, or monetization is strictly forbidden.
- Any consequence resulting from misuse of this project is the sole responsibility of the user.

# Peach Haven Technical Documentation & Research Index

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

</div>

This directory contains the reverse engineering analyses, protocol reconstruction notes, packet capture evidence, Python local server specifications, and Architectural Decision Records (ADRs) for the mobile game *Peach Utopia* (`com.IdolTime.Cards.game18`).

---

## 📚 Categorized Documentation Index

### 1. Static Decompilation & Resource Analysis (Analysis)

- [`analysis/apk-overview.md`](analysis/apk-overview.md): APK structure, Unity IL2CPP runtime architecture, managed assembly organization, and YooAsset delivery cache.
- [`analysis/apk-modification-feasibility.md`](analysis/apk-modification-feasibility.md): Feasibility evaluation of APK modification, byte patching, and repackaging.
- [`analysis/files-resource-analysis.md`](analysis/files-resource-analysis.md): Client-side local filesystem cache and data directory structure dissection.

### 2. Network Protocols & Authentication Reverse-Engineering (Protocols)

- [`analysis/sdk-network-protocol.md`](analysis/sdk-network-protocol.md): SDK HTTP API endpoints, AES-128-ECB cryptographic specifications, and response envelopes.
- [`analysis/sdk-domain-manager.md`](analysis/sdk-domain-manager.md): Client domain cache resolution, server list discovery, and fallback strategies.
- [`analysis/client-payment-chain-analysis.md`](analysis/client-payment-chain-analysis.md): Billing lifecycle, virtual G-point wallet, and in-game order fulfillment.
- [`analysis/hot-update-yooasset.md`](analysis/hot-update-yooasset.md): YooAsset CDN update mechanisms, manifest layout, and asset bundle loading.

### 3. TCP Protocol Capture & Recovery (TCP & Traffic)

- [`analysis/original-game-tcp-capture-20260823.md`](analysis/original-game-tcp-capture-20260823.md): Official server TCP traffic capture, stream reassembly, and login handshake bytes.
- [`analysis/game-tcp-capture-analysis-20260823.md`](analysis/game-tcp-capture-analysis-20260823.md): Dissection of real client startup frame sequences (`3/4/25/26/27/28`) and fixture extraction.
- [`analysis/gameplay-tcp-capture-20260823.md`](analysis/gameplay-tcp-capture-20260823.md): Gameplay battle, settlement, team lineup, gacha, and hero progression packet analysis.
- [`analysis/recovered-game-tcp-protocol.md`](analysis/recovered-game-tcp-protocol.md): Restored TCP 10-byte binary header framing and Message ID mappings.
- [`analysis/recovered-game-tcp-protocol.json`](analysis/recovered-game-tcp-protocol.json): Machine-readable JSON definition of restored TCP protocol messages.

### 4. System Implementation & Architecture Design (Implementation)

- [`implementation/local-server.md`](implementation/local-server.md): Python backend architecture (FastAPI HTTP + AsyncIO TCP) and SQLite persistence layer.
- [`implementation/game-state-model.md`](implementation/game-state-model.md): Player character state machine, inventory bag delta updates, and idempotent operations.
- [`implementation/local-relay-apk.md`](implementation/local-relay-apk.md): Client relay patch design, `classes3.dex` injection, and loopback proxy architecture.
- [`../tools/README.md`](../tools/README.md): Comprehensive toolchain catalog and upstream open-source repository references.
- [`../tools/apk-relay/README.md`](../tools/apk-relay/README.md): Client relay patch pipeline source code and build instructions.

### 5. Architecture Decision Records (ADR)

- [`decisions/001-local-sdk-original-hotupdate.md`](decisions/001-local-sdk-original-hotupdate.md): ADR 001: Local SDK compatibility server with upstream CDN hot-update traffic isolation.

### 6. Device Testing & Evidence Chain (Evidence)

- [`evidence/artifacts.md`](evidence/artifacts.md): Index of reverse-engineering evidence artifacts, pcap dumps, and test logs.
- [`evidence/p0-1-device-e2e-20260823.md`](evidence/p0-1-device-e2e-20260823.md): Physical Android device and emulator end-to-end integration test report.

### 7. Roadmap & Compatibility Criteria (Roadmap)

- [`todo/server-compatibility-todo.md`](todo/server-compatibility-todo.md): Detailed server compatibility checklist, feature gaps, and acceptance criteria.

---

## 🔍 Evidence Confidence Standard

All reverse-engineering conclusions documented across this repository adhere to the following confidence levels:

- **Confirmed**: Verified directly through static bytecode disassembly, decompiled C# symbols, automated regression tests, or Wireshark traffic dissection.
- **Inferred**: Deduced from calling contexts, naming patterns, or partial traces; basic implementation provided but requires further validation.
- **Pending**: Lacks full network request/response samples or runtime trace data for specific boundary scenarios.

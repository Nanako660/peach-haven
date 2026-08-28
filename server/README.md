# Local SDK & Game Compatibility Server

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

</div>

> **Category**: System Implementation / Python Backend Guide  
> **Status**: Confirmed (Verified by automated unit tests)  
> **Disclaimer**: This documentation and server implementation are solely for reverse-engineering, protocol analysis, and academic research. Commercial use is strictly forbidden.

This is the FastAPI + AsyncIO compatibility server suite for *Peach Utopia* (`com.IdolTime.Cards.game18`). It does not modify original APK assets or hijack YooAsset/HotUpdate traffic.

---

## Service Startup & Management

Run commands from the repository root containing the `server` directory.

### One-Click Background Startup & CLI Management (Recommended)

```powershell
.\start.ps1                       # Launch HTTP (8080) + Game TCP (21001) in background
.\stop.ps1                        # Stop all background server instances
python -m server.cli status       # Check process status and port listeners
python -m server.cli health       # Run HTTP & TCP health checks
python -m server.cli logs         # Stream server logs (--service http|game|all, -f to follow)
python -m server.cli lan          # Display local LAN IPv4 addresses
python -m server.cli account list # List all registered accounts
python -m server.cli account create <username> <password>
python -m server.cli account password <username> <new_password>
python -m server.cli account credit <username> <g_points>
python -m server.cli account balance <username>
python -m server.cli fixture ...  # Passthrough to fixture_tool
python -m server.cli smoke        # Run Python client smoke test
python -m server.cli test         # Execute full test suite
```

`start.ps1` supports `--http-port`, `--tcp-port`, `--config`, and `--foreground` (for foreground HTTP debugging). Process outputs and PID files are written to `server/data/`.

### Manual Foreground Startup (For Debugging)

```powershell
# In terminal 1: Run HTTP SDK service
python -m server.main

# In terminal 2: Run Game TCP service
python -m server.game_tcp

# Optional: Run Game TCP with explicit gameplay capture fallback
python -m server.game_tcp --gameplay-capture .\server\data\captures\tao-continuous-20260823-174438-game-frames.json
```

Verify working directory:

```powershell
Test-Path .\server\main.py
```

To stop foreground servers: press `Ctrl+C`.

To check port listeners:

```powershell
Get-NetTCPConnection -LocalPort 8080 -State Listen
```

---

## Health Check

```powershell
Invoke-WebRequest http://127.0.0.1:8080/healthz
```

From local network devices, access the host machine's IPv4 address:

```text
http://192.168.1.100:8080/healthz
```

---

## HTTP SDK Endpoints

All SDK `POST` endpoints require AES-encrypted request payloads; `/healthz` is the only unencrypted plaintext endpoint.

| Method | Path | Current Behavior |
| --- | --- | --- |
| GET | `/healthz` | Returns server health status |
| POST | `/server/list` | Returns local Game TCP server address in plaintext JSON |
| POST | `/api/domain` | Returns local SDK candidate domains (accepts JSON or AES payload) |
| POST | `/resource/url` | Returns upstream CDN root address without contacting upstream |
| POST | `/api/sdk/Login/account` | Authenticates username/password and issues Session Token |
| POST | `/api/sdk/Login/username` | Registers a new account and issues Session Token |
| POST | `/api/sdk/Login/quickAccount` | Generates a random guest account |
| POST | `/api/sdk/user/validateToken` | Validates session token, returns `data=true` upon success |
| POST | `/api/sdk/User/doUpdate` | Persists nickname, gender, avatar, etc. |
| POST | `/api/sdk/system/info` | Returns minimum `GameSystemData` and `UserData` |
| POST | `/api/sdk/system/gameTrack` | Validates Token and ingests client telemetry data |
| POST | `/api/sdk/UserProduct/getProductList` | Returns empty product list for payment UI compatibility |
| POST | `/api/sdk/Recharge/create` | Simulates local payment creation without contacting payment gateways |
| POST | `/api/sdk/Recharge/createAndSpend` | Simulates recharge & instant spending |
| POST | `/api/sdk/spend/create2` | Fulfills registered game orders and grants diamonds; falls back to virtual G-points |
| POST | `/api/sdk/login/singleGameVerify` | Game server authorization verification |

---

## Cryptographic Protocol Specification

- **Algorithm**: AES-128 ECB
- **Padding**: PKCS5 / PKCS7
- **Key**: `f237311e06398eac`
- **Request Content-Type**: `application/octet-stream`
- **Outer Request Schema (Decrypted)**:

```json
{
  "token": "",
  "deviceId": "device-id",
  "data": {
    "username": "test",
    "password": "test1234"
  }
}
```

- **Response Schema (Decrypted)**:

```json
{
  "status": "y",
  "time": "unix_timestamp",
  "errorCode": "",
  "error": "",
  "data": {}
}
```

Invalid or expired tokens return `status="n"` and `errorCode="2002"`.

---

## Data & Configuration

- **Active Config**: `server/config.toml` (local file, gitignored)
- **Config Template**: `server/config.toml.example`
- **SQLite Database**: `server/data/server.sqlite3` / `app.db`
- **Application Logs**: `server/data/server.log`
- **Game TCP Logs**: `server/data/game_tcp.log`
- **Default Account**: `test / test1234`
- **Password Storage**: PBKDF2-HMAC-SHA256 hashes (never stores plaintext passwords)
- **Token**: Random opaque string containing issue and expiry timestamps
- **Virtual G-Point Wallet**: Managed in `wallet_accounts` with ledger records in `wallet_transactions`. Default setting automatically credits required G-points during local simulated purchases.

---

## Game TCP Framing & Startup Sequence

TCP binary header is 10 bytes: big-endian `bodyLen(uint16) + msgId(uint16) + seq(int32) + flag(uint16)`.
The TCP service covers gameplay frames confirmed in captures: lineup, battle start/settlement, gacha, hero upgrade, nickname, story reading, conditions, user profile, community, and event queries.

```powershell
# Validate and install captured fixtures
python -m server.fixture_tool validate .\capture.json
python -m server.fixture_tool install .\capture.json .\server\data\fixtures\test-role.json

# Reconstruct fixture from analyze_game_tcp_pcap output
python -m server.fixture_tool from-capture .\server\data\captures\game-frames.json .\server\data\fixtures\captured-role.json --sdk-user-id 1 --login-open-id 1
```

### Configuration File (`server/config.toml`)

```toml
[http]
host = "0.0.0.0"
port = 8080

[sdk]
local_base_url = "http://192.168.1.100:8080"
domain_urls = ["http://192.168.1.100:8080"]
auto_credit_g_points = true

[game]
tcp_host = "0.0.0.0"
tcp_port = 21001
advertise_host = "192.168.1.100"
server_id = 4
fixture_dir = "server/data/fixtures"
```

---

## Python Client & Test Execution

Run end-to-end smoke test:

```powershell
python -m server.client
```

Run full regression test suite:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server tests
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'server'`
Commands must be run from the workspace root containing the `server` directory:
```powershell
Test-Path .\server\main.py
```

### Port 8080 / 21001 Conflict
Check listening processes and terminate stale instances:
```powershell
Get-NetTCPConnection -LocalPort 8080 -State Listen | Select-Object OwningProcess
Stop-Process -Id <PID>
```

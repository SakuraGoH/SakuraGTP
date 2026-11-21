# SakuraGTP

SakuraGTP is an open-source AI connector for **FoxGo(FoxWeiqi)**.  
It bridges GTP-compatible AI engines (KataGo, LeelaZero, etc.) with the FoxGo client, providing real-time winrate curves, candidate move visualization, HTTP API, and remote SSH support.Currently, only Chinese is supported. However, in the future, I will decide whether to add support for English and other languages based on my personal mood.
Since there was already an internal test version previously, the first release started with v1.4.0

---

## Features

- **Local engine support**: KataGo, LeelaZero, and any GTP-compatible engine.
- **Engine dialect auto-detection**: on start, SakuraGTP probes the engine (`protocol_version`, `name`, `list_commands`) and only sends commands the engine actually supports — `kata-*` for KataGo, plain `genmove`/`time_settings` for everyone else, and a graceful fallback if a command is rejected. Engines that do not echo GTP command ids are supported too.
- **Robust re-sync**: the Fox move list is the source of truth; after a reconnect, an engine restart or a move-number mismatch, SakuraGTP rebuilds the position with `clear_board` + full replay instead of relying on `undo`.
- **Remote engine support**: Built-in SSH client (no external `plink` needed), or custom command line (plink, ikatago, etc.).
- **Real-time board**: Live candidate moves with winrate, score lead, and visit counts.
- **Winrate curve**: Real-time winrate and score lead curves, exportable as PNG.
- **HTTP API**: Local JSON API for external tools, analysis scripts, and integrations.
- **GTP Shell**: Send GTP commands directly to the engine.
- **Rule switching**: One-click switch between Chinese and Japanese rules.
- **Auto reconnect**: Automatically recover after Fox Go client disconnection.
- **Heartbeat**: Optional engine heartbeat to detect unresponsive engines.
- **API Token**: Optional token authentication for the HTTP API.
- **Cross-platform**: Runs on Windows 10/11 (64-bit).

---

## Engine compatibility

SakuraGTP no longer assumes KataGo:

| Engine | What is sent |
|---|---|
| KataGo | `kata-genmove_analyze`, `kata-set-param`, `kata-set-rules`, `final_score` (candidates + winrate kept) |
| Leela Zero / GNU Go / Fuego / Pachi / others | core GTP only: `boardsize`, `komi`, `time_settings`, `time_left`, `play`, `genmove`, `final_score` |
| No `final_score` | Fox's `$AFSCORE` is answered with `error`, as the Fox protocol allows |

A from-scratch Python re-implementation of the official FoxGTP connector is available on the
[`foxgtp-py`](https://github.com/SakuraGoH/SakuraGTP/tree/foxgtp-py) branch: same protocol
behaviour (core GTP commands only, move-list re-sync, byo-yomi translation), plus support for
arbitrary GTP commands, a modern UI and a single-file executable.

Two useful config keys for byo-yomi translation (in `sakura_config.json`, matching FoxGTP's options):

- `use_common_byo_yomi`: `true` = "N seconds × M periods" (Go convention); `false` = converted to Canadian byo-yomi (1 stone per period).
- `data_transfer_time`: if > 0, seconds are subtracted from the engine's byo-yomi so network latency doesn't make the Fox client time out.

---

## Requirements

- **Python**: 3.8 or later
- **OS**: Windows 10 / 11 (64-bit)
- **AI Engine**: KataGo, LeelaZero, or any GTP-compatible engine
- **Fox Go client**: An account with AI access permission
- **Runtime libraries**:
  - Microsoft Visual C++ 2010 Redistributable (x86)
  - Microsoft Visual C++ 2015-2022 Redistributable (x64)

---

## Installation

### Option 1: Download the prebuilt exe

Download the latest `SakuraGTP.exe` from the [Releases](https://github.com/SakuraGoH/SakuraGTP/releases) page.

### Option 2: Run from source

```bash
git clone https://github.com/yourname/SakuraGTP.git
cd SakuraGTP
pip install -r requirements.txt
python main.py
```

---

## Quick Start

1. Launch **SakuraGTP**.
2. Choose **Local Engine** or **SSH Connection**.
3. Fill in engine path, weight path, and config path (local), or SSH host, user, password/key, and command (SSH).
4. Click **Start Engine** or **SSH Start**.
5. Click **Start Listening** to listen for the Fox Go client.
The following operations are the same as those for FoxGTP.

---

## HTTP API

SakuraGTP provides a local HTTP API at `http://127.0.0.1:8765` by default.

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | API info and endpoint list |
| GET | `/status` | Engine, Fox Go, AI color, board size |
| GET | `/board` | Current board position |
| GET | `/candidates` | Current candidate moves |
| GET | `/winrate` | Winrate curve data |
| GET | `/score` | Score lead curve data |
| GET | `/engine` | Engine info |
| GET | `/version` | API version |
| POST | `/gtp` | Send a GTP command |
| POST | `/engine/start` | Start engine |
| POST | `/engine/stop` | Stop engine |
| POST | `/fox/start` | Start listening |
| POST | `/fox/stop` | Stop listening |
| POST | `/rules` | Switch rules |

### Example

```python
import requests

BASE = "http://127.0.0.1:8765"

# Query status
print(requests.get(f"{BASE}/status").json())

# Query candidates
print(requests.get(f"{BASE}/candidates").json())

# Send GTP command
print(requests.post(f"{BASE}/gtp", json={"command": "genmove B"}).json())
```

### Token Authentication

If enabled, all requests must include:

```
Authorization: Bearer <your_token>
```

---

## Build

```bash
pyinstaller --onefile --windowed --name SakuraGTP ^
    --add-data "SakuraGTP HTTP API 文档.md;." ^
    --hidden-import=PyQt5 ^
    --hidden-import=PIL ^
    --hidden-import=paramiko ^
    main.py
```

The output is `dist/SakuraGTP.exe`.

---

## Security

- The HTTP API listens on `127.0.0.1` by default.
- SSH password is **not** saved to the config file.
- Optional API token authentication.
- Optional engine heartbeat to detect unresponsive engines.

---

## Contributing

Contributions are welcome. Please open an issue or submit a pull request.

---

## License

SakuraGTP is licensed under the **GNU General Public License v3.0 (GPL-3.0)**.

You are free to use, modify, and distribute this software.  
If you modify and distribute it, you **must** release the modified source code under the same license.

See [LICENSE](LICENSE) for details.

---

## Acknowledgments

- [KataGo](https://github.com/lightvector/KataGo)
- [LeelaZero](https://github.com/leela-zero/leela-zero)
- [PyQt5](https://pypi.org/project/PyQt5/)
- [paramiko](https://www.paramiko.org/)

---

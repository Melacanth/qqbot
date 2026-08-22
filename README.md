# QQ NapCat DeepSeek Bot

QQ group bot using NapCat OneBot v11 forward WebSocket and DeepSeek chat models.

## Run

1. Copy `.env.example` to `.env` and fill local secrets and allowed groups.
2. Start NapCat forward WebSocket.
3. Run:

```bash
python main.py
```

Runtime paths are configured through `.env`. Relative `DATA_DIR` values are
resolved from the project root; `DATABASE_PATH` and `IMAGE_ROOT` are resolved
from `DATA_DIR`; `LOG_DIR` is resolved from the project root. Windows and Linux
absolute paths are also supported through `pathlib.Path`.

Raspberry Pi OS and Ubuntu Server deployment instructions are available in
[`DEPLOY_RPI.md`](DEPLOY_RPI.md).

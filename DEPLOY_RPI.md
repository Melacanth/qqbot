# Raspberry Pi / Ubuntu Linux 部署

本方案适用于：

- Ubuntu Server 24.04（x86_64 或 ARM64）
- Raspberry Pi OS 64-bit
- Python 3.10 或更高版本
- 使用 systemd 的实体机或虚拟机

安装脚本会创建 Python 虚拟环境，安装 Tesseract 中文 OCR 和 Python
依赖，并生成 `qq-ai-bot.service`。脚本只启用服务，不会立即启动；请先完成
`.env` 配置。

## 1. 准备项目

把项目放在一个长期不移动的目录，例如：

```bash
cd /opt
sudo git clone <你的仓库地址> qq-deepseek-bot
sudo chown -R "$USER":"$USER" /opt/qq-deepseek-bot
cd /opt/qq-deepseek-bot
```

也可以放在当前用户的主目录。安装完成后不要随意移动项目，因为 systemd
服务会记录项目和虚拟环境的绝对路径。

## 2. 执行安装

推荐用普通登录用户执行，让脚本只在安装 apt 包和 systemd 服务时使用
`sudo`：

```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

脚本会完成：

1. 检查 Python 版本，最低要求为 Python 3.10。
2. 安装 `python3-venv`、`python3-dev`、`tesseract-ocr`、
   `tesseract-ocr-chi-sim`、`fonts-noto-cjk`、`libgl1` 和
   `libglib2.0-0`。
3. 创建 `.venv/` 并安装 `requirements.txt`。
4. 创建 `data/`、`logs/` 和 `image_library/`。
5. 在 `.env` 不存在时从 `.env.example` 生成一份部署配置。
6. 写入 `/etc/systemd/system/qq-ai-bot.service` 并启用服务。

如系统依赖已经安装，可以跳过 apt：

```bash
SKIP_APT=1 ./scripts/install.sh
```

可选安装参数：

```bash
BOT_USER=botuser PYTHON_BIN=python3 ./scripts/install.sh
```

- `BOT_USER`：systemd 服务运行用户，默认是执行安装脚本的用户。
- `BOT_GROUP`：服务运行组，默认取 `BOT_USER` 的主组。
- `PYTHON_BIN`：用于创建虚拟环境的 Python，可填写 `python3.12`。
- `VENV_DIR`：虚拟环境目录，默认是项目下的 `.venv/`。
- `BOT_DATA_DIR`：数据目录，默认是项目下的 `data/`。
- `BOT_LOG_DIR`：日志目录，默认是项目下的 `logs/`。
- `BOT_IMAGE_DIR`：图库目录，默认是项目下的 `image_library/`。

## 3. 配置环境变量

编辑安装脚本生成或保留的 `.env`：

```bash
nano .env
```

至少配置：

```dotenv
DEEPSEEK_API_KEY=你的密钥
ALLOWED_GROUP_IDS=允许机器人工作的QQ群号
NAPCAT_WS_URL=ws://192.168.1.100:3001
NAPCAT_WS_TOKEN=
```

路径默认值为：

```dotenv
DATA_DIR=data
LOG_DIR=logs
DATABASE_PATH=bot_state.db
IMAGE_ROOT=../image_library
```

因此数据库位于 `data/bot_state.db`，图库位于项目根目录的
`image_library/`。所有相对路径都由程序通过 `pathlib` 解析，也可以在
`.env` 中改成绝对路径。例如：

```dotenv
# Raspberry Pi OS / Ubuntu Server
DATA_DIR=/home/pi/qq-deepseek-bot/data
LOG_DIR=/home/pi/qq-deepseek-bot/logs
```

如果 NapCat 不在同一台机器，不能使用 `127.0.0.1`，需要填写运行
NapCat 的主机 IP 或可访问域名，并确保 WebSocket 端口可以从机器人主机访问。

OCR 默认先从 `PATH` 查找 `tesseract`；若未找到，Linux 会使用
`/usr/bin/tesseract`。可验证中文语言包：

```bash
tesseract --version
tesseract --list-langs | grep chi_sim
```

如果 Tesseract 位于非标准位置，在 `.env` 中设置：

```dotenv
IMAGE_OCR_TESSERACT_CMD=/usr/bin/tesseract
```

## 4. 管理 systemd 服务

启动：

```bash
sudo systemctl start qq-ai-bot
```

停止：

```bash
sudo systemctl stop qq-ai-bot
```

重启：

```bash
sudo systemctl restart qq-ai-bot
```

查看状态：

```bash
sudo systemctl status qq-ai-bot
```

服务已由安装脚本执行 `systemctl enable`，系统重启后会自动启动。如需取消：

```bash
sudo systemctl disable qq-ai-bot
```

## 5. 查看日志

标准输出和错误日志分别写入：

```text
logs/qq-ai-bot.log
logs/qq-ai-bot-error.log
```

实时查看：

```bash
tail -f logs/qq-ai-bot.log
tail -f logs/qq-ai-bot-error.log
```

systemd 自身事件可通过以下命令查看：

```bash
sudo journalctl -u qq-ai-bot -n 100 --no-pager
sudo journalctl -u qq-ai-bot -f
```

## 6. 更新项目

停止服务后更新代码并重新执行安装脚本；现有 `.env` 会保留：

```bash
sudo systemctl stop qq-ai-bot
git pull
./scripts/install.sh
sudo systemctl start qq-ai-bot
```

## 7. 故障排查

检查配置与 Python 导入：

```bash
.venv/bin/python -c "import app.runtime; print('runtime import OK')"
```

检查语法：

```bash
.venv/bin/python -m compileall .
```

检查服务内容：

```bash
systemctl cat qq-ai-bot
sudo systemd-analyze verify /etc/systemd/system/qq-ai-bot.service
```

常见问题：

- `ALLOWED_GROUP_IDS 不能为空`：在 `.env` 填写允许群号。
- 无法连接 NapCat：检查 `NAPCAT_WS_URL`、Token、端口和防火墙。
- 找不到 `chi_sim`：重新安装 `tesseract-ocr-chi-sim`。
- 摘要图片中文显示为方框：确认已安装 `fonts-noto-cjk`，或通过
  `SUMMARY_FONT_PATH` 指定可用中文字体。
- `libGL.so.1` 缺失：安装 `libgl1`。
- 服务启动后立刻退出：先查看 `logs/qq-ai-bot-error.log` 和
  `systemctl status qq-ai-bot`。

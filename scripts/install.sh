#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

SERVICE_NAME="qq-ai-bot.service"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/.venv}"
BOT_DATA_DIR="${BOT_DATA_DIR:-${PROJECT_ROOT}/data}"
BOT_LOG_DIR="${BOT_LOG_DIR:-${PROJECT_ROOT}/logs}"
BOT_IMAGE_DIR="${BOT_IMAGE_DIR:-${PROJECT_ROOT}/image_library}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SERVICE_FILE="${SYSTEMD_DIR}/${SERVICE_NAME}"
ENV_FILE="${PROJECT_ROOT}/.env"
ENV_EXAMPLE="${PROJECT_ROOT}/.env.example"
REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements.txt"

TEMP_SERVICE_FILE=""
TEMP_ENV_FILE=""


log() {
    printf '[install] %s\n' "$*"
}


fail() {
    printf '[install] ERROR: %s\n' "$*" >&2
    exit 1
}


cleanup() {
    if [[ -n "${TEMP_SERVICE_FILE}" && -f "${TEMP_SERVICE_FILE}" ]]; then
        rm -f -- "${TEMP_SERVICE_FILE}"
    fi
    if [[ -n "${TEMP_ENV_FILE}" && -f "${TEMP_ENV_FILE}" ]]; then
        rm -f -- "${TEMP_ENV_FILE}"
    fi
}
trap cleanup EXIT


require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "缺少命令：$1"
}


escape_unit_value() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    printf '%s' "${value}"
}


if [[ "$(uname -s)" != "Linux" ]]; then
    fail "此安装脚本仅支持 Linux。"
fi

[[ -f "${PROJECT_ROOT}/main.py" ]] || fail "未找到 main.py：${PROJECT_ROOT}"
[[ -f "${REQUIREMENTS_FILE}" ]] || fail "未找到 requirements.txt"
[[ -f "${ENV_EXAMPLE}" ]] || fail "未找到 .env.example"

require_command "${PYTHON_BIN}"
require_command apt-get
require_command systemctl
require_command install

PYTHON_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    fail "需要 Python 3.10 或更高版本，当前为 ${PYTHON_VERSION}"
fi
log "Python 版本检查通过：${PYTHON_VERSION}"

if [[ "${EUID}" -eq 0 ]]; then
    SUDO=()
    DEFAULT_BOT_USER="${SUDO_USER:-root}"
else
    require_command sudo
    SUDO=(sudo)
    DEFAULT_BOT_USER="$(id -un)"
fi

BOT_USER="${BOT_USER:-${DEFAULT_BOT_USER}}"
id "${BOT_USER}" >/dev/null 2>&1 || fail "运行用户不存在：${BOT_USER}"
BOT_GROUP="${BOT_GROUP:-$(id -gn "${BOT_USER}")}"

run_as_bot() {
    if [[ "$(id -u)" -eq "$(id -u "${BOT_USER}")" ]]; then
        "$@"
    elif [[ "${EUID}" -eq 0 ]]; then
        require_command runuser
        runuser -u "${BOT_USER}" -- "$@"
    else
        sudo -u "${BOT_USER}" -- "$@"
    fi
}

if [[ "${SKIP_APT:-0}" != "1" ]]; then
    log "安装系统依赖..."
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python3-venv \
        python3-dev \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        fonts-noto-cjk \
        libgl1 \
        libglib2.0-0
else
    log "SKIP_APT=1，跳过系统依赖安装。"
fi

log "创建数据目录..."
"${SUDO[@]}" install -d -m 0750 -o "${BOT_USER}" -g "${BOT_GROUP}" \
    "${BOT_DATA_DIR}" \
    "${BOT_LOG_DIR}" \
    "${BOT_IMAGE_DIR}" \
    "${VENV_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
    log "根据 .env.example 创建 .env..."
    TEMP_ENV_FILE="$(mktemp)"
    sed \
        -e 's|^DATA_DIR=.*|DATA_DIR=data|' \
        -e 's|^IMAGE_ROOT=.*|IMAGE_ROOT=../image_library|' \
        "${ENV_EXAMPLE}" > "${TEMP_ENV_FILE}"
    "${SUDO[@]}" install -m 0600 -o "${BOT_USER}" -g "${BOT_GROUP}" \
        "${TEMP_ENV_FILE}" "${ENV_FILE}"
else
    log "保留现有 .env。"
    "${SUDO[@]}" chown "${BOT_USER}:${BOT_GROUP}" "${ENV_FILE}"
    "${SUDO[@]}" chmod 0600 "${ENV_FILE}"
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    log "创建 Python 虚拟环境：${VENV_DIR}"
    run_as_bot "${PYTHON_BIN}" -m venv "${VENV_DIR}"
else
    log "复用现有 Python 虚拟环境：${VENV_DIR}"
fi

log "安装 Python 依赖..."
run_as_bot "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
run_as_bot "${VENV_DIR}/bin/python" -m pip install --prefer-binary \
    -r "${REQUIREMENTS_FILE}"

require_command tesseract
if ! tesseract --list-langs 2>/dev/null | grep -Fxq 'chi_sim'; then
    fail "Tesseract 未检测到 chi_sim 中文语言包。"
fi
log "Tesseract 与 chi_sim 语言包检查通过。"

ROOT_UNIT="$(escape_unit_value "${PROJECT_ROOT}")"
VENV_UNIT="$(escape_unit_value "${VENV_DIR}")"
DATA_UNIT="$(escape_unit_value "${BOT_DATA_DIR}")"
LOG_UNIT="$(escape_unit_value "${BOT_LOG_DIR}")"
IMAGE_UNIT="$(escape_unit_value "${BOT_IMAGE_DIR}")"
ENV_UNIT="$(escape_unit_value "${ENV_FILE}")"

TEMP_SERVICE_FILE="$(mktemp)"
cat > "${TEMP_SERVICE_FILE}" <<EOF
[Unit]
Description=QQ AI Bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=${BOT_USER}
Group=${BOT_GROUP}
WorkingDirectory="${ROOT_UNIT}"
Environment="PYTHONUNBUFFERED=1"
Environment="PYTHONUTF8=1"
Environment="DATA_DIR=${DATA_UNIT}"
Environment="LOG_DIR=${LOG_UNIT}"
Environment="DATABASE_PATH=bot_state.db"
Environment="IMAGE_ROOT=${IMAGE_UNIT}"
EnvironmentFile=-"${ENV_UNIT}"
ExecStart="${VENV_UNIT}/bin/python" "${ROOT_UNIT}/main.py"
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
StandardOutput="append:${LOG_UNIT}/qq-ai-bot.log"
StandardError="append:${LOG_UNIT}/qq-ai-bot-error.log"

[Install]
WantedBy=multi-user.target
EOF

log "安装 systemd 服务：${SERVICE_FILE}"
"${SUDO[@]}" install -d -m 0755 "${SYSTEMD_DIR}"
"${SUDO[@]}" install -m 0644 "${TEMP_SERVICE_FILE}" "${SERVICE_FILE}"
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable "${SERVICE_NAME}"

if command -v systemd-analyze >/dev/null 2>&1; then
    "${SUDO[@]}" systemd-analyze verify "${SERVICE_FILE}"
fi

log "安装完成。请先编辑 ${ENV_FILE}，至少填写："
printf '  DEEPSEEK_API_KEY\n'
printf '  ALLOWED_GROUP_IDS\n'
printf '  NAPCAT_WS_URL\n\n'
printf '启动：sudo systemctl start %s\n' "${SERVICE_NAME}"
printf '停止：sudo systemctl stop %s\n' "${SERVICE_NAME}"
printf '状态：sudo systemctl status %s\n' "${SERVICE_NAME}"
printf '日志：tail -f %s/qq-ai-bot.log\n' "${BOT_LOG_DIR}"

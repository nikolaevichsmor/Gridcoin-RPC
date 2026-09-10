#!/usr/bin/env bash
# ========================================================
#  Gridcoin Discord Rich Presence - Linux / macOS Installer
# ========================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo -e "\033[1;36m========================================================\033[0m"
echo -e "\033[1;36m   Gridcoin Discord Rich Presence - Linux Installer    \033[0m"
echo -e "\033[1;36m========================================================\033[0m"
echo ""

# 1. Check Python 3
echo -e "\033[1;33m[1/4] Checking Python 3 environment...\033[0m"
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    echo -e "  \033[1;32mFound: $PY_VER\033[0m"
else
    echo -e "  \033[1;31mError: python3 is not installed or not in PATH.\033[0m"
    echo "  Please install Python 3 (e.g. sudo apt install python3 python3-pip python3-venv)"
    exit 1
fi

# 2. Virtual environment and dependencies
echo -e "\033[1;33m[2/4] Setting up dependencies...\033[0m"
VENV_DIR="$PROJECT_ROOT/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR" || {
        echo "  Notice: python3-venv may not be installed. Falling back to user site-packages."
    }
fi

if [ -f "$VENV_DIR/bin/pip" ]; then
    PYTHON_EXEC="$VENV_DIR/bin/python"
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -r "$PROJECT_ROOT/requirements.txt"
    echo -e "  \033[1;32mDependencies installed in virtual environment.\033[0m"
else
    PYTHON_EXEC="$(command -v python3)"
    pip3 install --user --quiet -r "$PROJECT_ROOT/requirements.txt" || {
        pip install --user --quiet -r "$PROJECT_ROOT/requirements.txt"
    }
    echo -e "  \033[1;32mDependencies installed via pip user site-packages.\033[0m"
fi

# 3. Check Gridcoin core config
echo -e "\033[1;33m[3/4] Verifying Gridcoin node RPC configuration...\033[0m"
GRC_CONF="$HOME/.GridcoinResearch/gridcoinresearch.conf"
if [ -f "$GRC_CONF" ]; then
    echo -e "  \033[1;32mFound: $GRC_CONF\033[0m"
else
    if [ -f "$PROJECT_ROOT/.env" ]; then
        echo -e "  \033[1;32mFound local .env file\033[0m"
    else
        echo "  Notice: Neither ~/.GridcoinResearch/gridcoinresearch.conf nor .env found."
        if [ -f "$PROJECT_ROOT/.env.example" ]; then
            cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
            echo -e "  \033[1;32mCreated .env template in project directory.\033[0m"
        fi
    fi
fi

# 4. Setup systemd user service
echo -e "\033[1;33m[4/4] Configuring systemd user service...\033[0m"
if command -v systemctl &>/dev/null; then
    SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SYSTEMD_USER_DIR"
    SERVICE_FILE="$SYSTEMD_USER_DIR/gridcoin-rpc.service"

    cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Gridcoin Discord Rich Presence Daemon
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON_EXEC $PROJECT_ROOT/main.py --headless
WorkingDirectory=$PROJECT_ROOT
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

    echo -e "  \033[1;32mGenerated service unit at: $SERVICE_FILE\033[0m"
    systemctl --user daemon-reload
    systemctl --user enable --now gridcoin-rpc.service
    echo -e "  \033[1;32mService gridcoin-rpc enabled and started!\033[0m"
    echo ""
    echo "  Check service status with:"
    echo "    systemctl --user status gridcoin-rpc"
    echo "  View live logs with:"
    echo "    journalctl --user -u gridcoin-rpc -f"
else
    echo "  systemctl not found (non-systemd environment or macOS)."
    echo "  You can run the daemon manually with:"
    echo "    $PYTHON_EXEC $PROJECT_ROOT/main.py --headless"
fi

echo ""
echo -e "\033[1;32mInstallation complete! Gridcoin-RPC is now active.\033[0m"


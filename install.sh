#!/usr/bin/env bash

# We'll enable strict mode later, after detection
echo "==> Starting Kuun installer..."

SSH_URL="git@github.com:dcaric/Kuun.git"
HTTPS_URL="https://github.com/dcaric/Kuun.git"

# Explicitly set defaults
REPO_URL="https://github.com/dcaric/Kuun.git"
INSTALL_DIR="$HOME/Kuun"
SHELL_RC="$HOME/.zshrc"

echo "==> Detecting environment..."

# 1. Check for existing repo
if [ -d ".git" ]; then
    echo "    Checking current directory..."
    REMOTE_URL=$(git remote get-url origin 2>/dev/null < /dev/null || echo "none")
    if [[ "$REMOTE_URL" == *"Kuun"* ]]; then
        INSTALL_DIR=$(pwd)
        REPO_URL="$REMOTE_URL"
        echo "    Using current directory: $INSTALL_DIR"
    fi
fi

# 2. Check for SSH if we aren't already in a repo
if [[ "$REPO_URL" == "https://github.com/dcaric/Kuun.git" ]]; then
    echo "    Checking GitHub SSH access..."
    # BatchMode=yes prevents it from asking for a password/passphrase
    # < /dev/null prevents it from stealing the script pipe during curl | bash
    if ssh -o ConnectTimeout=3 -o BatchMode=yes -o StrictHostKeyChecking=no -T git@github.com < /dev/null 2>&1 | grep -q "Hi " 2>/dev/null; then
        REPO_URL="git@github.com:dcaric/Kuun.git"
        echo "    SSH access confirmed, switching to SSH URL."
    fi
fi

PATH_LINE="export PATH=\"$INSTALL_DIR:\$PATH\""

echo "==> Configuration set:"
echo "    Repo: $REPO_URL"
echo "    Dir:  $INSTALL_DIR"

set -euo pipefail # Now we enable strict mode for the actual installation

prompt_text() {
  local __var_name="$1"
  local __prompt="$2"
  local __value=""
  if [ -w /dev/tty ]; then
    printf "%s" "$__prompt" > /dev/tty
  else
    printf "%s" "$__prompt"
  fi
  if ! read -r __value < /dev/tty 2>/dev/null; then
    read -r __value
  fi
  printf -v "$__var_name" '%s' "$__value"
}

prompt_secret() {
  local __var_name="$1"
  local __prompt="$2"
  local __value=""
  if [ -w /dev/tty ] && [ -r /dev/tty ]; then
    printf "%s" "$__prompt" > /dev/tty
    while IFS= read -r -s -n1 __ch < /dev/tty; do
      if [ -z "$__ch" ]; then
        break
      fi
      if [ "$__ch" = $'\177' ] || [ "$__ch" = $'\b' ]; then
        if [ -n "$__value" ]; then
          __value="${__value%?}"
          printf '\b \b' > /dev/tty
        fi
      else
        __value="${__value}${__ch}"
        printf '*' > /dev/tty
      fi
    done
    echo > /dev/tty
  else
    printf "%s" "$__prompt"
    read -r -s __value
    echo
  fi
  printf -v "$__var_name" '%s' "$__value"
}

echo "==> Installing Kuun to: $INSTALL_DIR"
echo "⚠️  Gemini API key is mandatory for Kuun to work."
echo "    Recommended primary auth: gemini OAuth subscription via 'gemini auth login'."
echo "    This installer will also store GEMINI API key as backup in kuun.config (GOOGLE_API_KEY)."
echo
echo "Installation steps:"
if [[ "${OSTYPE:-}" == darwin* ]]; then
  echo "1) Install Homebrew (if missing)"
  echo "2) Install macOS packages via Homebrew: node, python@3.11, gemini-cli"
  echo "3) Clone or update Kuun repository at: $INSTALL_DIR"
  echo "4) Install Python and Node dependencies"
  echo "5) Configure Kuun:"
  echo "   - Kuun name (BOT_TRIGGER): word used at the start of WhatsApp commands"
  echo "   - BRIDGE_SECRET_KEY: shared secret for internal bridge auth (24-128 chars)"
  echo "   - ALLOWED_NUMBERS: admin numbers allowed to run trigger/agent commands"
  echo "   - GEMINI API key: backup auth if OAuth is unavailable"
  echo "6) Add Kuun to PATH in $SHELL_RC (if missing)"
  echo "7) Offer to run 'kuun whatsapp' to open WhatsApp bridge/link mode now"
else
  echo "1) Clone or update Kuun repository at: $INSTALL_DIR"
  echo "2) Install Python and Node dependencies"
  echo "3) Configure Kuun:"
  echo "   - Kuun name (BOT_TRIGGER): word used at the start of WhatsApp commands"
  echo "   - BRIDGE_SECRET_KEY: shared secret for internal bridge auth (24-128 chars)"
  echo "   - ALLOWED_NUMBERS: admin numbers allowed to run trigger/agent commands"
  echo "   - GEMINI API key: backup auth if OAuth is unavailable"
  echo "4) Add Kuun to PATH in $SHELL_RC (if missing)"
  echo "5) Offer to run 'kuun whatsapp' to open WhatsApp bridge/link mode now"
fi
echo
prompt_text CONFIRM_INSTALL "Continue? (yes/no): "
CONFIRM_INSTALL="$(printf '%s' "$CONFIRM_INSTALL" | tr '[:upper:]' '[:lower:]')"
if [ "$CONFIRM_INSTALL" != "yes" ] && [ "$CONFIRM_INSTALL" != "y" ]; then
  echo "Installation canceled."
  exit 0
fi

if [[ "${OSTYPE:-}" == darwin* ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    if ! [ -t 0 ] && ! [ -t 1 ]; then
      echo "==> Homebrew not found."
      echo "❌ Cannot auto-install Homebrew from non-interactive piped mode."
      echo "Run these commands instead:"
      echo "1) curl -fsSL https://raw.githubusercontent.com/dcaric/Kuun/main/install.sh -o /tmp/kuun-install.sh"
      echo "2) bash /tmp/kuun-install.sh"
      echo "Or install Homebrew manually, then re-run this installer."
      exit 1
    fi
    echo "==> Homebrew not found. Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    if [ -x /opt/homebrew/bin/brew ]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
      eval "$(/usr/local/bin/brew shellenv)"
    fi
  fi

  if command -v brew >/dev/null 2>&1; then
    echo "==> Installing macOS prerequisites via Homebrew..."
    brew install node python@3.11 gemini-cli
  else
    echo "❌ Homebrew installation failed. Please install it manually, then re-run install.sh."
    exit 1
  fi
fi

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> Existing Kuun repo found, pulling latest changes..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "==> Cloning Kuun..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

echo "==> Running setup..."
./kuun setup

echo
echo "==> Kuun name setup (BOT_TRIGGER)"
echo "This name is used as the trigger at the beginning of WhatsApp commands."
echo "Example: if name is 'kuun', users send: 'kuun - what time is it?'"
while true; do
  prompt_text KUUN_NAME "Enter Kuun name (letters/numbers/_/-): "
  if [[ "$KUUN_NAME" =~ ^[A-Za-z0-9_-]{1,32}$ ]]; then
    break
  fi
  echo "Name must be 1-32 chars and contain only letters, numbers, _ or -."
done

if grep -q '^BOT_TRIGGER=' "$INSTALL_DIR/kuun.config"; then
  sed -i.bak "s|^BOT_TRIGGER=.*|BOT_TRIGGER=${KUUN_NAME}|" "$INSTALL_DIR/kuun.config"
else
  printf '\nBOT_TRIGGER=%s\n' "$KUUN_NAME" >> "$INSTALL_DIR/kuun.config"
fi
rm -f "$INSTALL_DIR/kuun.config.bak"
echo "✅ BOT_TRIGGER saved."

echo
echo "==> BRIDGE_SECRET_KEY setup (required)"
echo "BRIDGE_SECRET_KEY is an internal shared secret between Kuun components."
echo "It protects your local bridge endpoints from unauthorized requests."
echo "Use 24-128 characters. Recommended: a random 64-hex string."
echo "Example generator: openssl rand -hex 32"
while true; do
  prompt_text BRIDGE_SECRET_KEY "Enter BRIDGE_SECRET_KEY: "
  key_len=${#BRIDGE_SECRET_KEY}
  if [ "$key_len" -ge 24 ] && [ "$key_len" -le 128 ]; then
    break
  fi
  echo "BRIDGE_SECRET_KEY must be between 24 and 128 characters."
done

if grep -q '^BRIDGE_SECRET_KEY=' "$INSTALL_DIR/kuun.config"; then
  sed -i.bak "s|^BRIDGE_SECRET_KEY=.*|BRIDGE_SECRET_KEY=${BRIDGE_SECRET_KEY}|" "$INSTALL_DIR/kuun.config"
else
  printf '\nBRIDGE_SECRET_KEY=%s\n' "$BRIDGE_SECRET_KEY" >> "$INSTALL_DIR/kuun.config"
fi
rm -f "$INSTALL_DIR/kuun.config.bak"
echo "✅ BRIDGE_SECRET_KEY saved."

echo
echo "==> ALLOWED_NUMBERS setup (required for admin/agent commands)"
echo "Only these numbers can run trigger commands (agent mode)."
echo "Format: comma-separated phone numbers, digits only."
echo "Example: 38591333444,38598111222"
while true; do
  prompt_text ALLOWED_NUMBERS_INPUT "Enter ALLOWED_NUMBERS: "
  ALLOWED_NUMBERS_CSV="$(echo "$ALLOWED_NUMBERS_INPUT" | tr -d '[:space:]')"
  if [ -z "$ALLOWED_NUMBERS_CSV" ]; then
    echo "ALLOWED_NUMBERS cannot be empty."
    continue
  fi
  if echo "$ALLOWED_NUMBERS_CSV" | grep -Eq '^[0-9]+(,[0-9]+)*$'; then
    break
  fi
  echo "Use digits and commas only, e.g. 38591333444,38598111222"
done

if grep -q '^ALLOWED_NUMBERS=' "$INSTALL_DIR/kuun.config"; then
  sed -i.bak "s|^ALLOWED_NUMBERS=.*|ALLOWED_NUMBERS=${ALLOWED_NUMBERS_CSV}|" "$INSTALL_DIR/kuun.config"
else
  printf '\nALLOWED_NUMBERS=%s\n' "$ALLOWED_NUMBERS_CSV" >> "$INSTALL_DIR/kuun.config"
fi
rm -f "$INSTALL_DIR/kuun.config.bak"
echo "✅ ALLOWED_NUMBERS saved."

echo
echo "==> Gemini API key setup (required backup)"
echo "Primary auth can be your Gemini subscription via: gemini auth login"
echo "This API key is stored as backup in kuun.config (GOOGLE_API_KEY)."
while true; do
  prompt_text GEMINI_API_KEY "Enter GEMINI API key: "
  if [ -n "${GEMINI_API_KEY}" ]; then
    break
  fi
  echo "API key cannot be empty."
done

if grep -q '^GOOGLE_API_KEY=' "$INSTALL_DIR/kuun.config"; then
  sed -i.bak "s|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=${GEMINI_API_KEY}|" "$INSTALL_DIR/kuun.config"
else
  printf '\nGOOGLE_API_KEY=%s\n' "$GEMINI_API_KEY" >> "$INSTALL_DIR/kuun.config"
fi
rm -f "$INSTALL_DIR/kuun.config.bak"
echo "✅ Gemini API key saved to kuun.config (GOOGLE_API_KEY)."

touch "$SHELL_RC"
if grep -Fqx "$PATH_LINE" "$SHELL_RC"; then
  echo "==> PATH already configured in $SHELL_RC"
else
echo "==> Adding Kuun to PATH in $SHELL_RC"
  printf '\n%s\n' "$PATH_LINE" >> "$SHELL_RC"
fi

echo
echo "==> WhatsApp bridge/link step"
echo "'kuun whatsapp' starts the WhatsApp bridge in foreground."
echo "During first run it opens QR link mode so you can pair this device in WhatsApp Linked Devices."
echo "After pairing, inbound WhatsApp messages can be routed to Kuun."
prompt_text RUN_WHATSAPP "Run 'kuun whatsapp' now? (yes/no): "
RUN_WHATSAPP="$(printf '%s' "$RUN_WHATSAPP" | tr '[:upper:]' '[:lower:]')"
if [ "$RUN_WHATSAPP" = "yes" ] || [ "$RUN_WHATSAPP" = "y" ]; then
  "$INSTALL_DIR/kuun" whatsapp
else
  echo "Skipped. You can run it later with: kuun whatsapp"
fi

echo
echo "✅ Kuun installation complete."
echo "Next steps:"
echo "1) Reload shell: source $SHELL_RC"
echo "2) Authenticate Gemini subscription (recommended): gemini auth login"
echo "3) Start Kuun services: kuun start"
echo "4) If you skipped pairing: kuun whatsapp"

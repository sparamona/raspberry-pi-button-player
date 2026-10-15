#!/bin/bash
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this as the normal jsheena user, not with sudo: ./install.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_USER="$(id -un)"
EXPECTED_DIR="$HOME/raspberry-pi-button-player"
USER_UNIT_DIR="$HOME/.config/systemd/user"
UNIT_NAME=button-mp3-player.service

if [[ "$SCRIPT_DIR" != "$EXPECTED_DIR" ]]; then
  echo "Move this project to $EXPECTED_DIR before installing." >&2
  exit 1
fi

groups_changed=false
for group in audio gpio; do
  if ! id -nG | tr ' ' '\n' | grep -qx "$group"; then
    echo "Adding $INSTALL_USER to the $group group..."
    sudo usermod -a -G "$group" "$INSTALL_USER"
    groups_changed=true
  fi
done

required_packages=(python3-gpiozero mpg123 alsa-utils)
missing_packages=()
for package in "${required_packages[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'ok installed'; then
    missing_packages+=("$package")
  fi
done
if ((${#missing_packages[@]})); then
  echo "Installing missing packages: ${missing_packages[*]}"
  sudo apt-get update
  sudo apt-get install -y "${missing_packages[@]}"
fi

# Remove the previous root-managed installation, if present.
sudo systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
sudo rm -f "/etc/systemd/system/$UNIT_NAME"
sudo systemctl daemon-reload

mkdir -p "$USER_UNIT_DIR" "$SCRIPT_DIR/music"
install -m 0644 "$SCRIPT_DIR/button-mp3-player.service" "$USER_UNIT_DIR/$UNIT_NAME"
chmod 0755 "$SCRIPT_DIR/button_player.py" "$SCRIPT_DIR/play_mp3_test.py" \
  "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/uninstall.sh"

# Allow the user's service manager to run at boot without an interactive login.
sudo loginctl enable-linger "$INSTALL_USER"

systemctl --user daemon-reload
systemctl --user enable "$UNIT_NAME"
if [[ "$groups_changed" == true ]]; then
  echo
  echo "Installation complete, but group membership changed."
  echo "Log out and back in (or reboot), then run ./install.sh again to start the service."
  exit 0
fi
systemctl --user restart "$UNIT_NAME"
if ! systemctl --user is-active --quiet "$UNIT_NAME"; then
  echo "Service failed to start. Check:" >&2
  echo "  journalctl --user-unit=$UNIT_NAME -n 50 --no-pager" >&2
  exit 1
fi

echo
echo "Installed and started the user service."
echo "MP3 directory: $SCRIPT_DIR/music/"
echo "Playlist: $SCRIPT_DIR/playlist.txt"
echo "Restart: systemctl --user restart button-mp3-player"
echo "Logs: journalctl --user-unit=button-mp3-player -f"

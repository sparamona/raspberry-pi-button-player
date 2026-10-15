#!/bin/bash
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this as the normal jsheena user, not with sudo: ./install.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_DIR="$HOME/raspberry-pi-button-player"
USER_UNIT_DIR="$HOME/.config/systemd/user"
UNIT_NAME=button-mp3-player.service

if [[ "$SCRIPT_DIR" != "$EXPECTED_DIR" ]]; then
  echo "Move this project to $EXPECTED_DIR before installing." >&2
  exit 1
fi

for group in audio gpio; do
  if ! id -nG | tr ' ' '\n' | grep -qx "$group"; then
    echo "Adding $USER to the $group group..."
    sudo usermod -a -G "$group" "$USER"
    echo "Log out and back in before using the player." >&2
  fi
done

echo "Installing required packages..."
sudo apt-get update
sudo apt-get install -y python3-gpiozero mpg123 alsa-utils

# Remove the previous root-managed installation, if present.
sudo systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
sudo rm -f "/etc/systemd/system/$UNIT_NAME"
sudo systemctl daemon-reload

mkdir -p "$USER_UNIT_DIR" "$SCRIPT_DIR/music"
install -m 0644 "$SCRIPT_DIR/button-mp3-player.service" "$USER_UNIT_DIR/$UNIT_NAME"
chmod 0755 "$SCRIPT_DIR/button_player.py" "$SCRIPT_DIR/play_mp3_test.py" \
  "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/uninstall.sh"

# Allow the user's service manager to run at boot without an interactive login.
sudo loginctl enable-linger "$USER"

systemctl --user daemon-reload
systemctl --user enable "$UNIT_NAME"
systemctl --user restart "$UNIT_NAME"

echo
echo "Installed and started the user service."
echo "MP3 directory: $SCRIPT_DIR/music/"
echo "Playlist: $SCRIPT_DIR/playlist.txt"
echo "Restart: systemctl --user restart button-mp3-player"
echo "Logs: journalctl --user-unit=button-mp3-player -f"

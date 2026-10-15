#!/bin/bash
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this as the normal user, not with sudo: ./uninstall.sh" >&2
  exit 1
fi

UNIT_NAME=button-mp3-player.service
UNIT_PATH="$HOME/.config/systemd/user/$UNIT_NAME"

systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
rm -f "$UNIT_PATH"
systemctl --user daemon-reload
printf 'User service removed. Program, music, playlist, and settings remain in %s.\n' \
  "$HOME/raspberry-pi-button-player"

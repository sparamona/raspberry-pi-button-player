#!/usr/bin/env python3
"""Play one MP3 using the button player's exact playback mechanism."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shlex

from button_player import (
    env_int,
    find_mpg123,
    Mpg123Player,
    set_default_volume,
    TrackLibrary,
)

LOG = logging.getLogger("button-player-test")
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS = PROJECT_DIR / "button-mp3-player.default"


def load_environment_file(path: Path) -> None:
    """Load simple KEY=VALUE settings without overriding the current environment."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        try:
            values = shlex.split(raw_value, comments=True)
        except ValueError as exc:
            raise ValueError(f"Invalid setting in {path}: {raw_line}") from exc
        if len(values) > 1:
            raise ValueError(
                f"Unsupported unquoted whitespace in setting: {raw_line}"
            )
        value = values[0] if values else ""
        os.environ.setdefault(key, value)


class SingleTrackLibrary:
    """Present one explicitly selected file to Mpg123Player."""

    def __init__(self, track: Path):
        self.track = track
        self.music_dir = track.parent
        self.playlist_path = track

    def current_track(self) -> Path:
        return self.track

    def advance(self) -> None:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Play one MP3 through mpg123 and the configured ALSA device, "
            "using the same Mpg123Player class as the GPIO service."
        )
    )
    parser.add_argument(
        "mp3",
        nargs="?",
        type=Path,
        help="MP3 to play; if omitted, play the first configured playlist track",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=DEFAULT_SETTINGS,
        help=f"settings file (default: {DEFAULT_SETTINGS})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment_file(args.settings)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    music_dir = Path(
        os.environ.get("MUSIC_DIR", str(PROJECT_DIR / "music"))
    ).expanduser()
    playlist_path = Path(
        os.environ.get("PLAYLIST_FILE", str(PROJECT_DIR / "playlist.txt"))
    ).expanduser()
    alsa_device = os.environ.get("ALSA_DEVICE", "").strip()
    try:
        playback_scale = env_int("PLAYBACK_SCALE", 32768, minimum=1)
        default_volume = env_int("DEFAULT_VOLUME", 80, minimum=0, maximum=100)
    except ValueError as exc:
        LOG.error("Configuration error: %s", exc)
        return 1
    mpg123 = find_mpg123()
    if not mpg123:
        LOG.error("mpg123 is not installed")
        return 1

    if args.mp3 is not None:
        track = args.mp3.expanduser().resolve()
        if not track.is_file() or track.suffix.lower() != ".mp3":
            LOG.error("Not a readable MP3 file: %s", track)
            return 1
        library = SingleTrackLibrary(track)
    else:
        library = TrackLibrary(music_dir, playlist_path)

    set_default_volume(
        default_volume,
        os.environ.get("ALSA_CARD", "Headphones"),
        os.environ.get("ALSA_MIXER_CONTROL", "PCM"),
    )
    player = Mpg123Player(library, mpg123, alsa_device, playback_scale)
    player.play_next()
    if player.process is None:
        return 1

    LOG.info(
        "Waiting for playback to finish%s",
        f" on ALSA device {alsa_device}" if alsa_device else "",
    )
    try:
        return_code = player.process.wait()
    except KeyboardInterrupt:
        LOG.info("Interrupted; stopping playback")
        player.stop()
        return 130

    if return_code != 0:
        LOG.error("mpg123 exited with status %d", return_code)
        return return_code

    LOG.info("Playback completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Push-button MP3 player for Raspberry Pi.

Each button press starts the next track only when playback is idle. Button
presses during playback are ignored. The playlist wraps after the last track.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
from typing import Callable, Sequence

LOG = logging.getLogger("button-player")
PROJECT_DIR = Path(__file__).resolve().parent


def load_tracks(music_dir: Path, playlist_path: Path) -> list[Path]:
    """Load playlist order, or scan the music directory alphabetically."""
    music_dir = music_dir.resolve()
    requested: list[Path] = []

    if playlist_path.is_file():
        for raw_line in playlist_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            candidate = Path(line)
            if not candidate.is_absolute():
                candidate = music_dir / candidate
            requested.append(candidate.resolve())

    if requested:
        tracks = []
        for track in requested:
            if track.is_file() and track.suffix.lower() == ".mp3":
                tracks.append(track)
            else:
                LOG.warning("Skipping missing or non-MP3 playlist entry: %s", track)
        return tracks

    if not music_dir.is_dir():
        return []
    return sorted(
        (path.resolve() for path in music_dir.iterdir()
         if path.is_file() and path.suffix.lower() == ".mp3"),
        key=lambda path: path.name.casefold(),
    )


class TrackLibrary:
    """Reloadable track list that preserves its position until the list changes."""

    def __init__(self, music_dir: Path, playlist_path: Path):
        self.music_dir = music_dir
        self.playlist_path = playlist_path
        self.tracks: list[Path] = []
        self.index = 0

    def next_track(self) -> Path | None:
        updated = load_tracks(self.music_dir, self.playlist_path)
        if updated != self.tracks:
            self.tracks = updated
            self.index = 0
            if updated:
                LOG.info("Loaded %d track(s)", len(updated))

        if not self.tracks:
            return None

        track = self.tracks[self.index]
        self.index = (self.index + 1) % len(self.tracks)
        return track


class Mpg123Player:
    def __init__(
        self,
        library: TrackLibrary,
        mpg123: str,
        alsa_device: str = "",
        playback_scale: int | None = None,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ):
        self.library = library
        self.mpg123 = mpg123
        self.alsa_device = alsa_device
        self.playback_scale = playback_scale
        self.popen_factory = popen_factory
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def _stop_unlocked(self) -> None:
        if self.process is None or self.process.poll() is not None:
            self.process = None
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        self.process = None

    def stop(self) -> None:
        with self.lock:
            self._stop_unlocked()

    def play_next(self) -> None:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                LOG.info("Ignoring button press while a track is playing")
                return
            self.process = None

            track = self.library.next_track()
            if track is None:
                LOG.error(
                    "No MP3 files found. Add files to %s or edit %s",
                    self.library.music_dir,
                    self.library.playlist_path,
                )
                return

            command = [self.mpg123, "-q", "-o", "alsa"]
            if self.alsa_device:
                command.extend(["-a", self.alsa_device])
            if self.playback_scale is not None:
                command.extend(["-f", str(self.playback_scale)])
            command.append(str(track))
            LOG.info("Playing: %s", track.name)
            try:
                self.process = self.popen_factory(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                LOG.exception("Could not start mpg123")
                self.process = None


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


def set_default_volume(
    percent: int,
    card: str = "0",
    control: str = "PCM",
    run_factory: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool:
    """Set and unmute the ALSA mixer used by the analog headphone jack."""
    if not 0 <= percent <= 100:
        LOG.error("DEFAULT_VOLUME must be between 0 and 100")
        return False
    command = [
        "amixer", "-c", card, "sset", control, f"{percent}%", "unmute"
    ]
    try:
        result = run_factory(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError:
        LOG.exception("Could not run amixer")
        return False
    if result.returncode != 0:
        LOG.error("Could not set volume: %s", (result.stderr or "").strip())
        return False
    LOG.info("Set startup volume to %d%%", percent)
    return True


class AlsaVolumeController:
    """Thread-safe stepped volume control for a rotary encoder."""

    def __init__(
        self,
        initial_percent: int,
        step_percent: int = 5,
        minimum_percent: int = 0,
        maximum_percent: int = 100,
        card: str = "0",
        control: str = "PCM",
        run_factory: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ):
        if not 0 <= minimum_percent <= maximum_percent <= 100:
            raise ValueError("Volume limits must satisfy 0 <= minimum <= maximum <= 100")
        if step_percent <= 0:
            raise ValueError("Volume step must be positive")
        self.minimum_percent = minimum_percent
        self.maximum_percent = maximum_percent
        self.step_percent = step_percent
        self.card = card
        self.control = control
        self.run_factory = run_factory
        self.percent = max(minimum_percent, min(maximum_percent, initial_percent))
        self.lock = threading.Lock()

    def _apply_unlocked(self) -> bool:
        command = [
            "amixer", "-c", self.card, "sset", self.control,
            f"{self.percent}%", "unmute",
        ]
        try:
            result = self.run_factory(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError:
            LOG.exception("Could not run amixer")
            return False
        if result.returncode != 0:
            LOG.error("Could not set volume: %s", (result.stderr or "").strip())
            return False
        LOG.info("Volume: %d%%", self.percent)
        return True

    def change(self, delta_percent: int) -> bool:
        with self.lock:
            self.percent = max(
                self.minimum_percent,
                min(self.maximum_percent, self.percent + delta_percent),
            )
            return self._apply_unlocked()

    def increase(self) -> bool:
        return self.change(self.step_percent)

    def decrease(self) -> bool:
        return self.change(-self.step_percent)


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    gpio_pin = int(os.environ.get("BUTTON_GPIO", "17"))
    bounce_seconds = float(os.environ.get("BOUNCE_SECONDS", "0.08"))
    music_dir = env_path("MUSIC_DIR", str(PROJECT_DIR / "music"))
    playlist_path = env_path("PLAYLIST_FILE", str(PROJECT_DIR / "playlist.txt"))
    alsa_device = os.environ.get("ALSA_DEVICE", "").strip()
    playback_scale = int(os.environ.get("PLAYBACK_SCALE", "32768"))
    if playback_scale <= 0:
        LOG.error("PLAYBACK_SCALE must be a positive integer")
        return 1
    default_volume = os.environ.get("DEFAULT_VOLUME", "").strip()
    alsa_card = os.environ.get("ALSA_CARD", "0")
    alsa_control = os.environ.get("ALSA_MIXER_CONTROL", "PCM")
    volume_percent = 80
    mpg123 = (
        shutil.which("mpg123")
        or shutil.which("mpg123-alsa")
        or shutil.which("mpg123.bin")
    )
    if not mpg123:
        LOG.error("mpg123 is not installed")
        return 1

    if default_volume:
        try:
            volume_percent = int(default_volume)
        except ValueError:
            LOG.error("DEFAULT_VOLUME is not an integer: %s", default_volume)
        else:
            set_default_volume(
                volume_percent,
                alsa_card,
                alsa_control,
            )

    # Import only on the Pi so playlist logic can be tested elsewhere.
    from gpiozero import Button, RotaryEncoder

    library = TrackLibrary(music_dir, playlist_path)
    player = Mpg123Player(library, mpg123, alsa_device, playback_scale)
    button = Button(gpio_pin, pull_up=True, bounce_time=bounce_seconds)
    button.when_pressed = player.play_next

    encoder = None
    encoder_clk = os.environ.get("ENCODER_CLK_GPIO", "").strip()
    encoder_dt = os.environ.get("ENCODER_DT_GPIO", "").strip()
    if encoder_clk and encoder_dt:
        volume = AlsaVolumeController(
            initial_percent=volume_percent,
            step_percent=int(os.environ.get("VOLUME_STEP", "5")),
            minimum_percent=int(os.environ.get("VOLUME_MIN", "0")),
            maximum_percent=int(os.environ.get("VOLUME_MAX", "100")),
            card=alsa_card,
            control=alsa_control,
        )
        encoder = RotaryEncoder(
            int(encoder_clk),
            int(encoder_dt),
            bounce_time=float(os.environ.get("ENCODER_BOUNCE_SECONDS", "0.005")),
            max_steps=100,
            wrap=True,
        )
        reverse = os.environ.get("ENCODER_REVERSE", "false").lower() in {
            "1", "true", "yes", "on",
        }
        if reverse:
            encoder.when_rotated_clockwise = volume.decrease
            encoder.when_rotated_counter_clockwise = volume.increase
        else:
            encoder.when_rotated_clockwise = volume.increase
            encoder.when_rotated_counter_clockwise = volume.decrease
        LOG.info(
            "Rotary volume ready: GPIO%s/GPIO%s, %d%% steps",
            encoder_clk,
            encoder_dt,
            volume.step_percent,
        )

    def shutdown(signum, _frame):
        LOG.info("Stopping after signal %s", signum)
        button.close()
        if encoder is not None:
            encoder.close()
        player.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    LOG.info(
        "Ready: GPIO%d to GND; each press plays the next MP3", gpio_pin
    )
    signal.pause()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from play_mp3_test import load_environment_file

from button_player import (
    AlsaVolumeController,
    env_int,
    load_tracks,
    set_default_volume,
    TrackLibrary,
    Mpg123Player,
)


class FakeProcess:
    def __init__(self):
        self.running = True
        self.terminated = False

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated = True
        self.running = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.running = False


class PlayerTests(unittest.TestCase):
    def test_failed_launch_retries_the_same_track(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            music = root / "music"
            music.mkdir()
            (music / "1.mp3").touch()
            (music / "2.mp3").touch()
            playlist = root / "playlist.txt"
            playlist.write_text("1.mp3\n2.mp3\n", encoding="utf-8")
            calls = []

            def fake_popen(command, **kwargs):
                calls.append(command)
                if len(calls) == 1:
                    raise OSError("launch failed")
                return FakeProcess()

            player = Mpg123Player(
                TrackLibrary(music, playlist),
                "/usr/bin/mpg123",
                popen_factory=fake_popen,
            )
            with self.assertLogs("button-player", level="ERROR"):
                player.play_next()
            player.play_next()

            self.assertEqual(len(calls), 2)
            self.assertTrue(calls[0][-1].endswith("1.mp3"))
            self.assertTrue(calls[1][-1].endswith("1.mp3"))

    def test_integer_environment_validation(self):
        with mock.patch.dict("os.environ", {"TEST_VALUE": "bad"}):
            with self.assertRaisesRegex(ValueError, "TEST_VALUE"):
                env_int("TEST_VALUE", 5)
        with mock.patch.dict("os.environ", {"TEST_VALUE": "0"}):
            with self.assertRaisesRegex(ValueError, "at least 1"):
                env_int("TEST_VALUE", 5, minimum=1)

    def test_environment_file_rejects_unquoted_whitespace(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "settings"
            settings.write_text("MUSIC_DIR=/tmp/music files\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unquoted whitespace"):
                load_environment_file(settings)

    def test_playback_scale_is_passed_to_mpg123(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            music = root / "music"
            music.mkdir()
            (music / "track.mp3").touch()
            playlist = root / "playlist.txt"
            playlist.write_text("track.mp3\n", encoding="utf-8")
            calls = []

            def fake_popen(command, **kwargs):
                calls.append(command)
                return FakeProcess()

            player = Mpg123Player(
                TrackLibrary(music, playlist),
                "/usr/bin/mpg123",
                playback_scale=49152,
                popen_factory=fake_popen,
            )
            player.play_next()

            self.assertEqual(calls[0][-3:], ["-f", "49152", str((music / "track.mp3").resolve())])

    def test_rotary_volume_changes_in_steps_and_stays_in_bounds(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)

        volume = AlsaVolumeController(
            initial_percent=80,
            step_percent=5,
            minimum_percent=10,
            maximum_percent=90,
            card="Headphones",
            control="PCM",
            run_factory=fake_run,
        )

        self.assertTrue(volume.increase())
        self.assertTrue(volume.increase())
        self.assertTrue(volume.increase())
        self.assertTrue(volume.decrease())

        self.assertEqual(volume.percent, 85)
        self.assertEqual([command[5] for command in calls], ["85%", "90%", "85%"])
        self.assertTrue(all(command[-1] == "unmute" for command in calls))

    def test_sets_default_volume_with_amixer(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        self.assertTrue(set_default_volume(80, "0", "PCM", fake_run))
        self.assertEqual(
            calls[0][0],
            ["amixer", "-c", "0", "sset", "PCM", "80%", "unmute"],
        )

    def test_explicit_playlist_order_and_cycle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            music = root / "music"
            music.mkdir()
            (music / "b.mp3").touch()
            (music / "a.mp3").touch()
            playlist = root / "playlist.txt"
            playlist.write_text("b.mp3\na.mp3\n", encoding="utf-8")
            library = TrackLibrary(music, playlist)
            self.assertEqual(library.current_track().name, "b.mp3")
            library.advance()
            self.assertEqual(library.current_track().name, "a.mp3")
            library.advance()
            self.assertEqual(library.current_track().name, "b.mp3")

    def test_comments_only_falls_back_to_alphabetical_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            music = root / "music"
            music.mkdir()
            (music / "Z.mp3").touch()
            (music / "a.MP3").touch()
            (music / "ignore.wav").touch()
            playlist = root / "playlist.txt"
            playlist.write_text("# no explicit order\n", encoding="utf-8")
            self.assertEqual(
                [path.name for path in load_tracks(music, playlist)],
                ["a.MP3", "Z.mp3"],
            )

    def test_press_while_playing_is_ignored_then_next_press_advances(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            music = root / "music"
            music.mkdir()
            (music / "1.mp3").touch()
            (music / "2.mp3").touch()
            playlist = root / "playlist.txt"
            playlist.write_text("1.mp3\n2.mp3\n", encoding="utf-8")
            calls = []
            processes = []

            def fake_popen(command, **kwargs):
                calls.append(command)
                process = FakeProcess()
                processes.append(process)
                return process

            player = Mpg123Player(TrackLibrary(music, playlist), "/usr/bin/mpg123", popen_factory=fake_popen)
            player.play_next()
            player.play_next()

            self.assertEqual(len(calls), 1)
            self.assertFalse(processes[0].terminated)
            self.assertTrue(calls[0][-1].endswith("1.mp3"))

            processes[0].running = False
            player.play_next()

            self.assertEqual(len(calls), 2)
            self.assertTrue(calls[1][-1].endswith("2.mp3"))


if __name__ == "__main__":
    unittest.main()

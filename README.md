# Raspberry Pi button-controlled MP3 player

Target: Raspberry Pi 3 (board revision 1.2), Raspberry Pi OS Lite.

## Behavior

- Boot completes and the service waits silently.
- First button press plays track 1.
- Button presses during playback are ignored.
- After a track finishes, the next press starts the next track.
- After the last track, the next press returns to track 1.
- No network is used during normal operation.

## Hardware

- Raspberry Pi 3 and microSD card
- Correct Raspberry Pi power supply
- Normally-open momentary push button
- Two female jumper wires (or soldered wires)
- Powered speakers, amplified speaker, or headphones with suitable volume

The Pi 3 jack is line/headphone-level; it cannot directly drive a bare passive speaker well.

## Wiring (power disconnected)

Use BCM GPIO17:

- Button terminal 1 -> physical pin 11 (`GPIO17`)
- Button terminal 2 -> physical pin 9 (`GND`)

The software enables the GPIO's internal pull-up resistor, so no external resistor is required.
For a four-legged tactile switch, the two legs on each side are normally common; use one leg
from each opposite side. Verify with a meter if uncertain.

```text
Pi 40-pin header                    Normally-open button
physical pin 11 / BCM GPIO17  -----[             ]-----  physical pin 9 / GND
```

Never connect this button circuit to 5 V.

### KY-040 volume knob

Keep the original button connected, then wire the encoder by its printed labels:

- `DT` -> physical pin 13 (`GPIO27`)
- `GND` -> physical pin 14 (`GND`)
- `CLK` -> physical pin 15 (`GPIO22`)
- `SW` -> physical pin 16 (`GPIO23`; intentionally unused by software)
- `+` -> physical pin 17 (`3.3V`, never 5V)

Clockwise rotation raises volume by 5%; counter-clockwise rotation lowers it.
The configured range is 55% to 100%, so the knob cannot mute the output.
The encoder's push action intentionally does nothing. If rotation works backwards,
set `ENCODER_REVERSE=true` in `button-mp3-player.default` and restart the service.

## OS and one-time setup

1. Use Raspberry Pi Imager to write **Raspberry Pi OS Lite (64-bit)** to the microSD card.
2. Boot the Pi with a monitor and keyboard, or temporarily enable SSH in Imager.
3. Copy this whole project directory to the Pi.
4. Run:

   ```bash
   cd raspberry-pi-button-player
   chmod +x install.sh uninstall.sh
   ./install.sh
   ```

The installer needs package access once to install `python3-gpiozero`, `mpg123`, and
`alsa-utils`. After installation, playback and boot operation require no Ethernet, Wi-Fi,
or internet connection.

## Sound through the 3.5 mm jack

The supplied configuration targets `sysdefault:CARD=Headphones`, the documented ALSA
device name for the analog jack on Raspberry Pi 4 and earlier. If that device is not
listed by `aplay -L`, use the following fallback.

Run:

```bash
sudo raspi-config
```

Choose **System Options -> Audio -> Headphones**, then finish and reboot. You can also
clear `ALSA_DEVICE` in `~/raspberry-pi-button-player/button-mp3-player.default` to use the
OS default. If there is no HDMI audio device, Raspberry Pi OS normally selects the
headphone jack automatically.

The player sets and unmutes the analog output whenever it starts. Change this line in
`button-mp3-player.default` to select another startup level:

```bash
DEFAULT_VOLUME=80
```

Playback also uses 150% software sample scaling:

```bash
PLAYBACK_SCALE=49152
```

The normal unamplified value is `32768`. Software scaling can increase perceived volume,
but especially loud recordings may clip or distort.

Restart after changing it:

```bash
systemctl --user restart button-mp3-player
```

Connect powered speakers or headphones and test sound before relying on the button:

```bash
speaker-test -t sine -f 440 -c 2
```

Press `Ctrl+C` to stop the test.

## Add and order tracks

Copy files:

```bash
cp /path/to/your/files/*.mp3 ~/raspberry-pi-button-player/music/
```

Choose either method:

- **Alphabetical:** leave `~/raspberry-pi-button-player/playlist.txt` with comments/blank lines only.
  Prefix names with `01-`, `02-`, etc. for a predictable order.
- **Explicit list:** put one filename per line in `playlist.txt`, for example:

  ```text
  welcome.mp3
  instructions.mp3
  finale.mp3
  ```

Changes are detected on the next button press. A changed list starts again at track 1.

## Test one MP3 without pressing the button

The test program imports the same `Mpg123Player` class, reads the same
`~/raspberry-pi-button-player/button-mp3-player.default` settings, invokes `mpg123` with the same arguments, and
uses the same ALSA device as the service.

Play the first track selected by the normal playlist configuration:

```bash
/usr/bin/python3 ~/raspberry-pi-button-player/play_mp3_test.py
```

Or play a specific MP3:

```bash
/usr/bin/python3 ~/raspberry-pi-button-player/play_mp3_test.py \
  ~/raspberry-pi-button-player/music/example.mp3
```

Press `Ctrl+C` to stop early. Avoid pressing the GPIO button during the test, since the
background service would start its own player process.

## Verify

```bash
systemctl --user status button-mp3-player --no-pager
journalctl --user-unit=button-mp3-player -n 50 --no-pager
```

You should see a `Ready: GPIO17 to GND` log line. Press the button and look for a `Playing:`
line.

Test automatic startup:

```bash
sudo reboot
```

After the Pi boots, wait about 30 seconds and press the button.

## Adjust volume

```bash
alsamixer
```

Select the analog/headphone output if prompted, adjust with arrow keys, then save:

```bash
sudo alsactl store
```

## Change the GPIO pin or ALSA device

Edit:

```bash
nano ~/raspberry-pi-button-player/button-mp3-player.default
systemctl --user restart button-mp3-player
```

GPIO numbers are **BCM numbers**, not physical header numbers. If audio goes to the wrong
ALSA device, run `aplay -L` and set `ALSA_DEVICE` to the appropriate device name.

## Troubleshooting

- **No button response:** recheck physical pins 11 and 9; run `pinout`; inspect the service log.
- **Multiple skips per press:** increase `BOUNCE_SECONDS` from `0.08` to `0.15`.
- **No audio:** force Headphones in `raspi-config`, verify powered speakers, run the speaker test,
  and inspect `aplay -L`.
- **Permission error for GPIO/audio:** verify `jsheena` is in `gpio` and `audio`, then log out and
  back in: `id jsheena`.
- **Track not found:** filenames in `playlist.txt` are case-sensitive.
- **Service restart:** `systemctl --user restart button-mp3-player`.

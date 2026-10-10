# n4haiGeoDetector
Provides city, county, state, and gridsquare location information on a Raspberry Pi equipped with a 3.5" LCD screen.  Other display options to be developed in the future.

## Test the LCD directly on the Pi

The LCD driver must already expose a 480x320 RGB565 framebuffer compatible with
`displaygeo.py`. This test runs directly on Raspberry Pi OS without Docker, GPS,
or boundary files. It shows **sample** county and grid information with the Pi's
current UTC time, IP address, and CPU temperature for five seconds, then color
bars and a grayscale ramp for five seconds. It repeats this sequence 10 times
(about 100 seconds total), then clears the screen and exits.

Install Git and Python, then clone this repository from GitHub:

```sh
sudo apt update
sudo apt install -y git python3 python3-venv fonts-dejavu-core
git clone https://github.com/n4haiham/n4haiGeoDetector.git
cd n4haiGeoDetector
```

For an existing checkout, run `git pull --ff-only` from its directory to fetch
the latest code. Create a virtual environment and install the dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

If the project's Docker boot service is running, stop it first so it does not
overwrite the test screen:

```sh
sudo systemctl stop n4hai-geodetector.service
```

Run the test with the virtual environment's Python:

```sh
sudo .venv/bin/python test_lcd.py
```

If the LCD is on `/dev/fb1`, or you want different sample values:

```sh
sudo .venv/bin/python test_lcd.py --framebuffer /dev/fb1 \
  --county Loudoun --abbr LDN --grid FM18kv
```

The framebuffer path must match your LCD driver. The test and main app write
RGB565 pixels in native byte order (little-endian on the Pi). If colors still
do not match the labels, check the driver's pixel format with
`fbset -fb /dev/fb0 -i` (install with `sudo apt install fbset`, and substitute
your LCD device). The writer expects 16-bit RGB565: red offset 11, green offset
5, and blue offset 0. Framebuffer color layouts are driver-specific; see the
[Linux framebuffer API](https://docs.kernel.org/fb/api.html).
After testing, restart the boot service if you
previously stopped it:

```sh
sudo systemctl start n4hai-geodetector.service
```

## Install Docker on the Raspberry Pi

These steps are for **64-bit Raspberry Pi OS Bookworm or Trixie** and follow
[Docker's official Debian installation guide](https://docs.docker.com/engine/install/debian/).
Check your OS and package architecture first:

```sh
cat /etc/os-release
dpkg --print-architecture
```

The architecture should be `arm64`. For `armhf`, consult
[Docker's 32-bit Raspberry Pi OS guidance](https://docs.docker.com/engine/install/raspberry-pi-os/)
instead; the Raspbian packages stop at Docker Engine v28. Older ARMv6 models
(Pi 1 and original Pi Zero/Zero W) are unsupported by official Docker packages.

On a fresh Pi, install prerequisites and add Docker's signing key:

```sh
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

If this Pi already has distribution packages such as `docker.io`, `podman-docker`,
`containerd`, or `runc`, follow the official guide's conflicting-package removal
steps before continuing.

Add the repository, then install Docker Engine and its CLI plugins:

```sh
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker.service
sudo docker run --rm hello-world
```

The last command should print a successful installation message. Use `sudo` for
Docker commands on the Pi; the project's boot service runs as root and does not
require adding your user to the `docker` group. Continue with the project setup
below after this check passes.

## Docker and Raspberry Pi boot startup

Use Raspberry Pi OS with systemd and Docker Engine installed. A 64-bit OS is
recommended. Build on the Pi to select its native architecture. The LCD driver
must already expose a 480x320 RGB565 framebuffer compatible with `displaygeo.py`;
the container does not install or configure LCD drivers.

Install the image, launcher, and boot service from this checkout:

```sh
sudo bash scripts/install-boot-service.sh
sudo nano /etc/n4hai-geodetector.env
```

Set `GPS_DEVICE` to the GPS serial device (default `/dev/ttyUSB0`), `GPS_RATE`
to its baud rate, and `FB_DEVICE` to the LCD framebuffer (often `/dev/fb0` or
`/dev/fb1`). A `/dev/serial/by-id/...` GPS path avoids changes to USB numbering.

For a USB GPS running at 4800 baud and an LCD on `/dev/fb0`, edit the existing
lines in `/etc/n4hai-geodetector.env` to read:

```sh
GPS_DEVICE=/dev/ttyUSB0
GPS_RATE=4800
FB_DEVICE=/dev/fb0
```

For a GPS exposed as `/dev/ttyACM0` running at 9600 baud and an LCD on `/dev/fb1`:

```sh
GPS_DEVICE=/dev/ttyACM0
GPS_RATE=9600
FB_DEVICE=/dev/fb1
```

Use the baud rate specified by your GPS receiver. To find available serial
devices and framebuffers on the Pi:

```sh
ls -l /dev/serial/by-id/
ls -l /dev/ttyUSB* /dev/ttyACM* /dev/fb*
```

Missing paths may produce "No such file or directory" messages. If a stable
serial path is listed, you can use its full name as `GPS_DEVICE`, for example:

```sh
GPS_DEVICE=/dev/serial/by-id/usb-YOUR_GPS_RECEIVER_ID
GPS_RATE=4800
FB_DEVICE=/dev/fb1
```

Replace `usb-YOUR_GPS_RECEIVER_ID` with the actual name listed on your Pi.
Save the file and restart the service using the commands below to apply changes.

For an upside-down LCD, add this line to `/etc/n4hai-geodetector.env`:

```sh
FLIP_SCREEN=true
```

This rotates the entire LCD image 180 degrees. Use `FLIP_SCREEN=false` (the
default) for normal orientation. Direct Python runs can use
`python3 displaygeo.py --port /dev/ttyUSB0 --flip-screen`.
When first upgrading to this feature, rerun
`sudo bash scripts/install-boot-service.sh` to rebuild the image and update the
installed launcher, then restart the service. The installer preserves your
existing environment file.

By default, all KML files in this checkout's `./boundaries` directory are included
in the image and loaded together. Keep that directory on the Pi before building;
it is excluded from Git. Rebuild the image after updating its KML files.
Optionally set `BOUNDARY_FILE` to an absolute host path to a KML file or directory
to mount and load instead. Quote file paths containing spaces.

Start it now, then check the service:

```sh
sudo systemctl restart n4hai-geodetector.service
sudo systemctl status n4hai-geodetector.service
sudo journalctl -u n4hai-geodetector.service -f
```

The installer enables startup at every boot. The service retries every 10 seconds
if devices are unavailable or the container exits. A stopped GPS thread causes
the LCD app to exit so the service can reconnect. SIGTERM saves settings during
normal shutdown. Settings and GPS logs persist in the Docker volume
`n4hai-geodetector-data`, under `/data/arGeoDetector` inside the container.
The LCD shows `Entered at HH:MM` in GMT for the current county. County changes
highlight the county abbreviation as black text in a large white box for
60 seconds, then restore white text on black. Repeated GPS updates in the same
county do not extend the highlight.
County changes
and each live app startup are appended to `county_entries.csv` in that same
directory (locally, `~/.config/arGeoDetector/county_entries.csv`). Columns are
`datetime_gmt,event,grid_square,county,county_abbr,state_abbr`. Startup records
show Unknown and an unavailable grid until the GPS supplies a location; the
first known county gets its own entry. GPS dropouts do not create county entries
or reset the entry time. State abbreviations come from the supplied
`Overlay<State>...kml` filenames; custom filenames leave the state blank.
Entry timestamps use the Pi's UTC clock, so keep its system clock synchronized.
The launcher uses host networking so the LCD shows the Pi's IP address, and
passes only the configured GPS and framebuffer devices. The app runs as root
inside the container to access those devices. CPU temperature shows `n/a` if
the host thermal sensor is unavailable inside Docker.

After changing code, rebuild and restart:

```sh
sudo docker build -t n4hai-geodetector:local .
sudo systemctl restart n4hai-geodetector.service
```

To stop it and disable boot startup:

```sh
sudo systemctl disable --now n4hai-geodetector.service
```

For a manual LCD run, stop the service first, then run
`sudo bash scripts/run-container.sh /etc/n4hai-geodetector.env`.
The installer preserves an existing configuration file on subsequent runs.

You can also build and preview the container without Pi hardware:

```sh
docker build -t n4hai-geodetector:local .
docker run --rm --init -p 8080:8080 n4hai-geodetector:local \
  python displaygeo_web.py --host 0.0.0.0
```

Open `http://localhost:8080/` to see the mock LCD image.

## County history in a web browser

The LCD app also serves a county history table at `http://<pi-ip-address>:8081/`.
For example, open `http://n4haimap3:8081/` from a browser on the same network,
or use the Pi's IP shown on the LCD. The table shows all county entries recorded
in the last 24 hours, newest first, with GMT date/time, grid square, county name,
county abbreviation, and state abbreviation. It refreshes every 15 seconds.
Startup records remain in the CSV but are excluded from the county-change table.
History survives container restarts because it reads the persistent CSV log.

To install this feature on an existing Pi setup:

```sh
cd ~/repos/n4haiGeoDetector
git pull --ff-only
sudo bash scripts/install-boot-service.sh
sudo systemctl restart n4hai-geodetector.service
```

The browser server starts automatically with the LCD app. To change its port,
add `HISTORY_PORT=8082` to `/etc/n4hai-geodetector.env` and restart the service,
then browse to port 8082. Set `HISTORY_PORT=0` to disable it. The launcher uses
host networking, so no Docker port mapping is needed. Anyone able to reach this
port can read the location history; use it on your trusted local network.

For a direct Python LCD run, use `--history-port 8081` (the default), or
`--history-host 127.0.0.1` to restrict browser access to the Pi itself.
To view an existing CSV without starting the LCD/GPS app:

```sh
.venv/bin/python county_history_web.py \
  --log ~/.config/arGeoDetector/county_entries.csv --port 8081
```

Use an unused port if the LCD app's history server is already running.

## Browser LCD preview

Local GPS/replay runs also default to the `boundaries` directory beside the
Python scripts, unless saved settings or `--boundary` select another path.
`--boundary` accepts either one KML file or a directory of KML files.

`displaygeo_web.py` serves the same 480x320 PIL image produced by
`generateLCDImage()` as a browser-refreshing PNG.

Install runtime dependencies if needed:

```sh
python3 -m pip install -r requirements.txt
```

Run locally with mock location data:

```sh
python3 displaygeo_web.py
```

Then open:

```text
http://localhost:8080/
```

Mock values can be changed from the command line:

```sh
python3 displaygeo_web.py --county Loudoun --abbr LDN --grid FM18kv
```

Or while it is running:

```text
http://localhost:8080/set?county=Loudoun&abbr=LDN&grid=FM18kv
```

On a Raspberry Pi, bind to all interfaces so another machine can view it:

```sh
python3 displaygeo_web.py --host 0.0.0.0
```

To preview live GPS/replay data instead of mock data, add `--live` and use the
same GPS/replay options as `displaygeo.py`, for example:

```sh
python3 displaygeo_web.py --live --port /dev/ttyUSB0 --rate 4800 --boundary counties.kml --host 0.0.0.0
python3 displaygeo_web.py --live --nmea sample.nmea --boundary counties.kml
```

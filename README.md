# n4haiGeoDetector
Provides city, county, state, and gridsquare location information on a Raspberry Pi equipped with a 3.5" LCD screen.  Other display options to be developed in the future.

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

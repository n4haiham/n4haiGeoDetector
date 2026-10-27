# Using GPSD with Chrony and n4haiGeoDetector

The recommended configuration has **GPSD as the only process opening the USB GPS**.
The detector and cgps connect to GPSD over TCP port 2947. Chrony uses its
existing GPSD reference-clock integration; this change does not modify Chrony.

## Before changing the working installation

On the Pi:

```bash
sudo systemctl cat n4hai-geodetector.service
sudo systemctl cat gpsd.service gpsd.socket
chronyc sources -v
sudo cp -a /etc/n4hai-geodetector.env /etc/n4hai-geodetector.env.pre-gpsd
sudo cp -a /etc/systemd/system/n4hai-geodetector.service /etc/systemd/system/n4hai-geodetector.service.pre-gpsd
```

Check the override shown by `systemctl cat`. In particular, the previously used
`ExecStartPre=/usr/bin/gpsctl -f -n /dev/ttyACM0` must NOT run in GPSD mode:
it changes GPS settings while GPSD is using the receiver. Remove only that
override directive (and any other direct-device prestart commands), retaining
unrelated local customizations. The installer does **not** remove systemd
drop-ins automatically.

## Deploy

```bash
cd ~/n4haiGeoDetector
git fetch origin
git switch feature/gpsd-shared-chrony
sudo systemctl stop n4hai-geodetector.service
sudo systemctl enable --now gpsd.socket
sudo systemctl start gpsd.service
gpspipe -w -n 10
```

Confirm a TPV with mode 2 or 3, valid latitude/longitude, and a GPS time.
If GPSD has no fix or the existing Chrony setup is not working, repair that
first; do not redeploy the detector.

Ensure the override no longer runs gpsctl, then:

```bash
sudo bash scripts/install-boot-service.sh
sudo sed -i '/^GPSD_HOST=/d; /^GPSD_PORT=/d' /etc/n4hai-geodetector.env
printf 'GPSD_HOST=127.0.0.1\nGPSD_PORT=2947\n' | sudo tee -a /etc/n4hai-geodetector.env
sudo systemctl daemon-reload
sudo systemctl restart n4hai-geodetector.service
docker logs --tail 30 n4hai-geodetector
chronyc sources -v
chronyc tracking
```

The detector should display county/grid after a valid TPV. GPSD reader logs
`Connecting to GPSD at 127.0.0.1:2947` and location updates.
The JSON TPV `time` is used for county-entry timestamps; it does not set
the operating-system clock. Chrony continues to manage the system clock.

`--gpsd-host` works only for `displaygeo.py`; the other tools remain unchanged.
The serial mode is retained for compatibility.

## Rollback

```bash
sudo systemctl stop n4hai-geodetector.service
cd ~/n4haiGeoDetector
git switch main
sudo cp -a /etc/n4hai-geodetector.env.pre-gpsd /etc/n4hai-geodetector.env
sudo bash scripts/install-boot-service.sh
```

Restore the previous systemd override only if it was modified, then run
`sudo systemctl daemon-reload`. If returning to exclusive direct-serial mode,
stop GPSD first to avoid having two readers of the same receiver, then
restart the detector. Do not stop GPSD if Chrony still needs GPS time.

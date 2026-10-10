"""Rotating Pi status line, with graceful fallbacks for unavailable sensors."""

from pathlib import Path
import datetime
import shutil
import subprocess
import time


def command(args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL,
                                       timeout=1).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def host_status(index):
    if index == 8:
        return datetime.datetime.now(datetime.timezone.utc).strftime('%d %b %Y %H:%M:%S GMT')
    sys_root = Path('/host-sys') if Path('/host-sys').is_dir() else Path('/sys')
    try:
        if index == 0:
            addresses = command(['hostname', '-I']).split()
            return f"IP: {addresses[0] if addresses else 'n/a'}"
        if index == 1:
            temp = int((sys_root / 'class/thermal/thermal_zone0/temp').read_text()) / 1000
            return f"CPU temp: {temp:.1f} C"
        if index == 4:
            for alarm in sorted(sys_root.glob('class/hwmon/hwmon*/in0_lcrit_alarm')):
                return f"Undervolt: {'YES' if int(alarm.read_text()) else 'OK'}"
            return 'Undervolt: n/a'
        if index == 5:
            path = Path('/host-uptime') if Path('/host-uptime').exists() else Path('/proc/uptime')
            minutes = int(float(path.read_text().split()[0])) // 60
            days, remainder = divmod(minutes, 1440)
            hours, minutes = divmod(remainder, 60)
            return f"Uptime: {days}d {hours:02d}h {minutes:02d}m"
        if index == 6:
            disk = shutil.disk_usage('/data' if Path('/data').is_dir() else '/')
            return f"Disk free: {disk.free / 2**30:.1f} GiB ({disk.free / disk.total:.0%})"
        if index == 7:
            interfaces = command(['iw', 'dev']).splitlines()
            for line in interfaces:
                if line.strip().startswith('Interface '):
                    interface = line.split()[1]
                    for detail in command(['iw', 'dev', interface, 'link']).splitlines():
                        if detail.strip().startswith('signal:'):
                            return f"Wi-Fi {interface}: {detail.strip().split(':', 1)[1].strip()}"
            # Older drivers expose signal level directly in /proc/net/wireless.
            for line in Path('/proc/net/wireless').read_text().splitlines()[2:]:
                parts = line.split()
                if len(parts) >= 4:
                    return f"Wi-Fi {parts[0].rstrip(':')}: {parts[3].rstrip('.')} dBm"
            return 'Wi-Fi: n/a (disconnected/unavailable)'
    except (OSError, ValueError, IndexError):
        pass
    return {1: 'CPU temp: n/a', 4: 'Undervolt: n/a',
            5: 'Uptime: n/a', 6: 'Disk free: n/a', 7: 'Wi-Fi: n/a'}.get(index, 'IP: n/a')


class StatusCycle:
    def __init__(self):
        self.started = time.monotonic()
        self.cached_index = None
        self.cached_until = 0
        self.cached_text = ''

    def text(self, display):
        now = time.monotonic()
        index = int((now - self.started) // 5) % 10
        if index == 9:
            count = display.get_known_counties() if hasattr(display, 'get_known_counties') else 'n/a'
            return f'Known Counties: {count}'
        if index in (2, 3):
            return display.get_gps_status(index == 3) if hasattr(display, 'get_gps_status') else (
                'GPS update: n/a' if index == 3 else 'GPS fix/sats: n/a')
        if index != self.cached_index or now >= self.cached_until:
            self.cached_text = host_status(index)
            self.cached_index = index
            self.cached_until = now + 1
        return self.cached_text

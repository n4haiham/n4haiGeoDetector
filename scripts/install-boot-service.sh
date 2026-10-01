#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo bash scripts/install-boot-service.sh" >&2
    exit 1
fi
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
command -v systemctl >/dev/null
if [[ ! -x /usr/bin/docker ]]; then
    echo "Install Docker Engine first (expected /usr/bin/docker)." >&2
    exit 1
fi
systemctl enable --now docker.service
# Build on the Pi so Docker selects its native CPU architecture.
docker build -t n4hai-geodetector:local "$repo_dir"
install -m 755 "$repo_dir/scripts/run-container.sh" /usr/local/bin/n4hai-geodetector-run
install -m 644 "$repo_dir/deploy/n4hai-geodetector.service" /etc/systemd/system/n4hai-geodetector.service
if [[ ! -e /etc/n4hai-geodetector.env ]]; then
    install -m 600 "$repo_dir/deploy/geodetector.env.example" /etc/n4hai-geodetector.env
fi
systemctl daemon-reload
systemctl enable n4hai-geodetector.service
echo "Installed and enabled for boot. Configure /etc/n4hai-geodetector.env, then run:"
echo "  sudo systemctl restart n4hai-geodetector.service"

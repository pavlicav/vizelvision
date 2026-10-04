#!/bin/sh
# Installs/restarts the master stack and retires the duplicate Roku web service.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
unit_dir=/home/vivian/.config/systemd/user
cd "$project_dir"

test -x vendor/mediamtx/1.21.0/mediamtx
/usr/bin/python3 - <<'PY'
from roku_stream.config import load_config
from roku_stream.master import diagnostics
config = load_config('config.master.json')
if not config.master.enabled:
    raise SystemExit('Enable master in config.master.json before installing the stack')
if config.server.host not in ('127.0.0.1', '0.0.0.0') or config.server.port != 6970:
    raise SystemExit('The candidate stack expects port 6970 with a loopback or LAN listener')
checks = diagnostics()
if not checks.get('bench_available') or checks.get('missing_live_elements'):
    raise SystemExit('Missing GStreamer dependencies; run /usr/bin/python3 -m roku_stream master-check')
PY

systemd-analyze --user verify \
    "$script_dir/vizelvision-stack.target" \
    "$script_dir/vizelvision-mediamtx.service" \
    "$script_dir/vizelvision-master.service" \
    "$script_dir/vizelvision-web.service" \
    "$script_dir/vizelvision-admute.service" \
    "$script_dir/vizelvision-admute-recordings.service" \
    "$script_dir/vizelvision-admute-recordings.timer"

mkdir -p "$unit_dir"
for unit in vizelvision-stack.target vizelvision-mediamtx.service vizelvision-master.service vizelvision-web.service vizelvision-admute.service \
        vizelvision-admute-recordings.service vizelvision-admute-recordings.timer; do
    install -m 0644 "$script_dir/$unit" "$unit_dir/$unit"
done
systemctl --user daemon-reload
systemctl --user enable vizelvision-stack.target vizelvision-admute-recordings.timer
# Both web apps use the same capture device; keep only master control running.
if systemctl --user cat vizelvision.service >/dev/null 2>&1; then
    systemctl --user disable --now vizelvision.service
fi
# Restart also applies updated unit files when the installer is run again.
systemctl --user restart vizelvision-stack.target
/usr/bin/python3 "$script_dir/check-master-stack.py"
systemctl --user --no-pager --full status \
    vizelvision-stack.target vizelvision-mediamtx.service vizelvision-master.service vizelvision-web.service vizelvision-admute.service

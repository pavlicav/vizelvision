#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
unit_dir=/home/vivian/.config/systemd/user

mkdir -p "$unit_dir"
install -m 0644 "$script_dir/vizelvision-user.service" "$unit_dir/vizelvision.service"
systemctl --user daemon-reload
systemctl --user enable --now vizelvision.service
systemctl --user --no-pager --full status vizelvision.service

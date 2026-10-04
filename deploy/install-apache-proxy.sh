#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

sudo install -o root -g root -m 0644 \
  "$script_dir/vizelvision-apache.conf" \
  /etc/apache2/conf-available/vizelvision.conf
sudo /usr/sbin/a2enmod proxy proxy_http
sudo /usr/sbin/a2enconf vizelvision
sudo /usr/sbin/apache2ctl configtest
sudo systemctl reload apache2.service

echo "Apache proxy installed: http://viviserv/vizelvision/"

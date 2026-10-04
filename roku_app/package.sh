#!/usr/bin/env bash
# Package the Roku app as vizelvision.zip for sideloading.
# Usage: ./package.sh
set -e
cd "$(dirname "$0")"
rm -f vizelvision.zip
zip -r vizelvision.zip manifest source/ components/
echo "Built vizelvision.zip"
echo "Sideload at: http://<ROKU_IP>/ → Development Application Installer → Upload"

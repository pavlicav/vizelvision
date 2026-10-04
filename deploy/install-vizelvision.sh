#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

"$script_dir/install-user-service.sh"
"$script_dir/install-apache-proxy.sh"

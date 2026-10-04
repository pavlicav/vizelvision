#!/usr/bin/env python3
"""Fetch the pinned Linux amd64 test server; never install/start a service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import tarfile
import tempfile
import urllib.request

VERSION = "1.21.0"
ARCHIVE = f"mediamtx_v{VERSION}_linux_amd64.tar.gz"
URL = f"https://github.com/bluenviron/mediamtx/releases/download/v{VERSION}/{ARCHIVE}"
# Digest from the upstream v1.21.0 release metadata/checksums.
SHA256 = "e02e34c3337a35f20ac9e5aa31524566108964e6e37dbc46cf8292169f6c792b"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "vendor" / "mediamtx" / VERSION)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        parser.error("This pinned asset is for Linux amd64 only")
    target = args.directory.resolve()
    if target.exists():
        parser.error(f"Destination already exists; choose a new --directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mediamtx-fetch-", dir=target.parent) as work:
        stage = Path(work)
        archive = stage / ARCHIVE
        digest = hashlib.sha256()
        size = 0
        request = urllib.request.Request(URL, headers={"User-Agent": "VizelVision"})
        with urllib.request.urlopen(request, timeout=30) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 40 * 1024 * 1024:
                    raise RuntimeError("Unexpectedly large MediaMTX archive")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != SHA256:
            raise RuntimeError("MediaMTX archive checksum mismatch")
        extracted = stage / "files"
        extracted.mkdir()
        with tarfile.open(archive, "r:gz") as package:
            for name in ("mediamtx", "mediamtx.yml", "LICENSE"):
                member = package.getmember(name)
                if not member.isfile() or member.size > 160 * 1024 * 1024:
                    raise RuntimeError(f"Unexpected archive member: {name}")
                with package.extractfile(member) as source, (extracted / name).open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
        os.chmod(extracted / "mediamtx", 0o755)
        (extracted / "origin.json").write_text(json.dumps({"version": VERSION, "url": URL, "sha256": SHA256}, indent=2) + "\n")
        extracted.rename(target)
    print(target / "mediamtx")


if __name__ == "__main__":
    main()

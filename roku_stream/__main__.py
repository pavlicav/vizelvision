from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .api import build_roku, serve
from .config import load_config
from .errors import RokuStreamError


def _log_events() -> None:
    """The services' own INFO lines (the station ID's end card, early preparations, the join
    bumper...) were dropped: with no logging set up only warnings reached the journal.
    Other libraries stay at warnings; lines keep their bare format."""
    logging.basicConfig(format="%(message)s")
    logging.getLogger("roku_stream").setLevel(logging.INFO)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control YouTube TV on the Roku")
    parser.add_argument(
        "--config",
        default=os.environ.get("ROKU_STREAM_CONFIG", "config.json"),
        help="JSON configuration path (default: config.json)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Run the HTTP API and scheduler")
    commands.add_parser("master-check", help="Inspect GStreamer/MediaMTX dependencies without starting media")
    commands.add_parser("master-worker", help="Run the persistent master publisher and private control socket")
    commands.add_parser("master-status", help="Read the persistent master's status")
    smoke = commands.add_parser("master-smoke", help="Run bounded synthetic A/V cuts; no capture or publication")
    smoke.add_argument("--duration", type=float, default=8, help="Synthetic bench duration, 8–30 seconds")
    publication = commands.add_parser("master-publication-test", help="Publish synthetic A/V to isolated MediaMTX and verify RTSP/HLS readers")
    publication.add_argument("--mediamtx", help="MediaMTX executable (default: PATH or pinned vendor copy)")
    publication.add_argument("--duration", type=float, default=20, help="Verified playout duration after startup, 16–30 seconds")
    commands.add_parser("roku-status", help="Show the source Roku, as TV Thing's Roku lane reports it")
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "master-publication-test":
            from .publication import publication_test
            print(json.dumps(publication_test(executable=args.mediamtx, duration=args.duration), indent=2, sort_keys=True))
            return
        if args.command in ("master-check", "master-smoke"):
            from .master import diagnostics, smoke_test
            result = diagnostics() if args.command == "master-check" else smoke_test(args.duration)
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        config = load_config(args.config)
        if args.command == "master-worker":
            from .master_worker import serve_worker
            _log_events()
            serve_worker(config)
            return
        if args.command == "master-status":
            from .master_worker import MasterClient
            print(json.dumps(MasterClient(config.master).request(), indent=2, sort_keys=True))
            return
        if args.command == "serve":
            _log_events()
            serve(config)
            return
        if args.command == "roku-status":
            # The Roku's navigation, calibration and capture are TV Thing's since 2026-10-06.
            roku = build_roku(config)
            if roku is None:
                raise SystemExit("TV-Thing is not configured (tv_thing.enabled)")
            lane, lock = roku.lane()
            print(json.dumps({"lane": lane, "lock": lock}, indent=2, sort_keys=True))
            return
        raise AssertionError(args.command)  # pragma: no cover - argparse prevents this.
    except KeyboardInterrupt:
        print(json.dumps({"error": {"code": "interrupted", "message": "Operation interrupted"}}), file=sys.stderr)
        raise SystemExit(130)
    except RokuStreamError as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "details": exc.details,
                    }
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

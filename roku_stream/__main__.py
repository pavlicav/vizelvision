from __future__ import annotations

import argparse
import json
import os
import sys

from .api import serve
from .config import load_config
from .controller import RokuStreamController
from .errors import RokuStreamError


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
    commands.add_parser("status", help="Probe Roku and capture readiness")
    commands.add_parser("state", help="Detect the current Roku/YouTube TV screen")
    plan = commands.add_parser("plan", help="Show keys without controlling the Roku")
    plan.add_argument("channel")
    play = commands.add_parser("play", help="Play a channel immediately")
    play.add_argument("channel")
    calibrate = commands.add_parser(
        "calibrate", help="Save a visual template for the currently selected guide row"
    )
    calibrate.add_argument("channel")
    calibrate_frame = commands.add_parser(
        "calibrate-guide-frame",
        help="Save a guide template from an observed raw PPM frame",
    )
    calibrate_frame.add_argument("channel")
    calibrate_frame.add_argument("ppm_path")
    calibrate_network = commands.add_parser(
        "calibrate-network",
        help="Save the logo from the currently open YouTube TV network page",
    )
    calibrate_network.add_argument("channel")
    calibrate_current_network = commands.add_parser(
        "calibrate-current-network",
        help="Verify the selected guide row, safely open its page, and calibrate it",
    )
    calibrate_current_network.add_argument("channel")
    verify = commands.add_parser(
        "verify", help="Verify the visibly selected guide row without pressing a key"
    )
    verify.add_argument("channel")
    commands.add_parser(
        "calibrate-profile",
        help="Save the currently selected first profile as the Vivian safety template",
    )
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
            serve_worker(config)
            return
        if args.command == "master-status":
            from .master_worker import MasterClient
            print(json.dumps(MasterClient(config.master).request(), indent=2, sort_keys=True))
            return
        controller = RokuStreamController(config)
        if args.command == "serve":
            serve(config, controller)
            return
        if args.command == "status":
            result = controller.status()
            exit_code = 0 if result.get("ready") else 1
        elif args.command == "state":
            result = controller.current_state()
            exit_code = 0
        elif args.command == "plan":
            result = controller.plan(args.channel)
            exit_code = 0
        elif args.command == "play":
            result = controller.play(args.channel)
            exit_code = 0
        elif args.command == "calibrate":
            result = controller.calibrate(args.channel)
            exit_code = 0
        elif args.command == "calibrate-guide-frame":
            result = controller.calibrate_guide_frame(args.channel, args.ppm_path)
            exit_code = 0
        elif args.command == "calibrate-profile":
            result = controller.calibrate_profile()
            exit_code = 0
        elif args.command == "calibrate-network":
            result = controller.calibrate_network(args.channel)
            exit_code = 0
        elif args.command == "calibrate-current-network":
            result = controller.calibrate_current_network(args.channel)
            exit_code = 0
        elif args.command == "verify":
            result = controller.verify_current_row(args.channel)
            exit_code = 0
        else:  # pragma: no cover - argparse prevents this.
            raise AssertionError(args.command)
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(exit_code)
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

"""The Schedule page on real data, without the station.

Serves this tree's pages and the real API handler for /v1/programming, /v1/playback,
/v1/favorites and /v1/sports over tests/dev_schedule.py's Programming (its own state folder,
a queue that runs nothing). Every other read is fetched from the live station; every other
write is refused. So the page can be tried, and changed, against tonight's listings and
games while the station airs on undisturbed.

    python3 -m tests.dev_schedule_server /tmp/vv-dev-state [port] [host]

It listens on this machine only unless a host is given (0.0.0.0 for the whole network).
"""
from __future__ import annotations

from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from roku_stream import playback
from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig
from roku_stream.favorites import FavoritesPlanner

from tests.dev_schedule import LIVE, build, get

OURS = ('/v1/programming', '/v1/playback', '/v1/favorites', '/v1/sports')


def main(folder, port=6971, host='127.0.0.1'):
    built = build(folder)
    programming, queue, sports = built['programming'], built['queue'], built['sports']

    class Master:  # What the live master has on air, for the projection.
        def request(self):
            return get(LIVE + 'v1/master', timeout=10)

    projector = playback.Projector(queue=queue, programming=programming, master=Master(), sports=sports)
    planner = FavoritesPlanner(built['favorites'], programming, sports)
    config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(),
                             master=MasterConfig(socket_path=Path(folder) / 'master.sock'))
    base = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(), playout=queue,
                           programming=programming, sports=sports, projector=projector, favorites=planner,
                           sports_slots=built['sports_slots'], discovery=built['discovery'])

    class Handler(base):
        def _ours(self):
            path = self.path.split('?', 1)[0]
            return not path.startswith('/v1/') or path.startswith(OURS)

        def _relay(self):
            try:
                with urlopen(Request(LIVE.rstrip('/') + self.path, headers={'Accept': 'application/json'}), timeout=30) as response:
                    body, status, kind = response.read(), response.status, response.headers.get('Content-Type')
            except HTTPError as exc:
                body, status, kind = exc.read(), exc.code, exc.headers.get('Content-Type')
            self.send_response(status)
            self.send_header('Content-Type', kind or 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            return super().do_GET() if self._ours() else self._relay()

        def _refuse(self):
            self._json(403, {'error': {'code': 'dev', 'message': 'The dev server only changes its own schedule'}})

        def do_POST(self):  # noqa: N802
            return super().do_POST() if self._ours() else self._refuse()

        def do_DELETE(self):  # noqa: N802
            return super().do_DELETE() if self._ours() else self._refuse()

        def log_message(self, *args):
            pass

    built['sports_slots'].start()   # Sports slots put their games on this schedule, as on the station.
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'Dev schedule on http://{host}:{port}/schedule (state in {folder}) at {datetime.now(timezone.utc):%H:%M:%S}Z', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/vv-dev-state', int(sys.argv[2]) if len(sys.argv) > 2 else 6971,
         sys.argv[3] if len(sys.argv) > 3 else '127.0.0.1')

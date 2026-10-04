"""Real Chromium HLS playback through the production API handler and CSP.

Generated media, isolated MediaMTX/HTTP ports, fake control/catalog, no hardware.
"""
import json
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig
from roku_stream.master_media import MasterMedia, DecodedInput
from roku_stream.publication import LocalMediaMtx


def main():
    with tempfile.TemporaryDirectory(prefix="vv-browser-master-") as directory:
        with LocalMediaMtx(Path("vendor/mediamtx/1.21.0/mediamtx").resolve(), Path(directory)) as server:
            output = MasterMedia(server.rtsp_url)
            decoder = DecodedInput(output, 1, "", test_pattern=4)
            http = None
            try:
                deadline = time.monotonic()+12
                while not (output.healthy() and decoder.ready()) and time.monotonic()<deadline:
                    output.poll(); decoder.poll(); time.sleep(.05)
                assert output.healthy() and decoder.ready()
                output.take(1)
                config = SimpleNamespace(server=SimpleNamespace(api_key=None), master=MasterConfig(enabled=True, hls_url=server.hls_url.rsplit('/',1)[0]+'/'))
                state = {"state":"live","on_air":{"id":"fixture","source_id":"tv-thing-digital","channel_id":"red"},
                         "publisher_ready":True,"preview_enabled":True,"can_take":False,"can_prepare":False}
                def command(action="status", body=None):
                    if action=="fallback":
                        output.take(0); state.update(state="fallback", on_air=None)
                        return {"accepted":True}
                    assert action=="status"
                    return dict(state)
                sources=SimpleNamespace(list=lambda:{"sources":[],"warnings":[]})
                with patch('roku_stream.api.MasterClient') as client:
                    client.return_value.request.side_effect=command
                    Base=handler_factory(config,SimpleNamespace(),SimpleNamespace(),sources=sources)
                class Handler(Base):
                    def log_message(self,*_):
                        pass
                    def do_GET(self):
                        assert self.path.startswith('/vizelvision/')
                        self.path=self.path[len('/vizelvision'):]
                        super().do_GET()
                    def do_POST(self):
                        assert self.path.startswith('/vizelvision/')
                        self.path=self.path[len('/vizelvision'):]
                        super().do_POST()
                http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                threading.Thread(target=http.serve_forever,daemon=True).start()
                result=subprocess.run(['node','tests/browser_master_media.cjs',sys.argv[1],f'http://127.0.0.1:{http.server_port}/vizelvision/air'],capture_output=True,text=True,timeout=75)
                if result.returncode:
                    raise AssertionError(result.stdout+result.stderr)
                report=json.loads(result.stdout)
                Path('docs/master-browser-validation.json').write_text(json.dumps(report,indent=2)+'\n')
                print(result.stdout)
            finally:
                if http:
                    http.shutdown();http.server_close()
                decoder.close();output.close()


if __name__=='__main__':
    main()

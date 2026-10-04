"""Selection-bound HLS proxy. Browsers receive only opaque manifest-derived URLs."""
from collections import OrderedDict
import hashlib
import re
import threading
from urllib.parse import urljoin, urlsplit, unquote
from urllib.request import build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

from .errors import ConfigError
from .master import MasterStreamError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class InputPreview:
    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, master, *, opener=None):
        self.master = master
        self.opener = opener or build_opener(NoRedirect()).open
        self.lock = threading.Lock()
        self.paths = OrderedDict()
        self.readers = threading.BoundedSemaphore(6)

    @staticmethod
    def _validate_url(root, url):
        target, allowed = urlsplit(url), urlsplit(root)
        prefix = allowed.path.rsplit('/', 1)[0] + '/'
        decoded = unquote(target.path)
        if (target.scheme not in ('http', 'https') or target.netloc != allowed.netloc
                or not decoded.startswith(prefix) or any(p in ('.', '..') for p in decoded.split('/'))
                or target.fragment or target.username or target.password
                or not re.search(r'\.(m3u8|ts|mp4|m4s|aac)$', target.path)):
            raise MasterStreamError('Source playlist referenced media outside its stream directory')

    def _reference(self, key, root, parent, reference):
        url = urljoin(parent, reference)
        self._validate_url(root, url)
        target = urlsplit(url)
        extension = target.path.rsplit('.', 1)[-1]
        token = hashlib.sha256(url.encode()).hexdigest()[:32] + '.' + extension
        with self.lock:
            self.paths[(key, token)] = (root, url)
            self.paths.move_to_end((key, token))
            while len(self.paths) > 1024:
                self.paths.popitem(last=False)
        return token

    def read(self, key, name):
        if not re.fullmatch(r'[a-f0-9]{32}', key) or not re.fullmatch(r'(index|[a-f0-9]{32})\.(m3u8|ts|mp4|m4s|aac)', name):
            raise ConfigError('Unknown source preview media')
        if not self.readers.acquire(False):
            raise MasterStreamError('Source previews are busy; retry shortly')
        try:
            selection = self.master.request('preview', {'input_id': key})
            root = selection['url']
            if name == 'index.m3u8':
                url = root
            else:
                with self.lock:
                    entry = self.paths.get((key, name))
                if not entry or entry[0] != root:
                    raise MasterStreamError('Source preview reference expired')
                url = entry[1]
            try:
                # MediaMTX redirects its initial playlist to a session URL.
                # Follow only bounded redirects within the same stream directory.
                for attempt in range(4):
                    try:
                        with self.opener(url, timeout=5) as response:
                            raw = response.read(self.MAX_BYTES + 1)
                        break
                    except HTTPError as exc:
                        location = exc.headers.get('Location')
                        exc.close()
                        if attempt == 3 or exc.code not in (301, 302, 303, 307, 308) or not location:
                            raise
                        url = urljoin(url, location)
                        self._validate_url(root, url)
                if len(raw) > self.MAX_BYTES:
                    raise MasterStreamError('Source media exceeded the response limit')
            except OSError as exc:
                raise MasterStreamError('Source preview media is unavailable') from exc
            # Reject responses fetched across a cancellation/retune, not just subsequent requests.
            if self.master.request('preview', {'input_id': key}) != selection:
                raise MasterStreamError('Source selection changed during preview')
            if name.endswith('.m3u8'):
                if not raw.startswith(b'#EXTM3U'):
                    raise MasterStreamError('Source did not return an HLS playlist')
                try:
                    playlist = raw.decode('utf-8')
                except UnicodeError as exc:
                    raise MasterStreamError('Source playlist is not valid UTF-8') from exc
                lines = []
                for line in playlist.splitlines():
                    if line and not line.startswith('#'):
                        line = self._reference(key, root, url, line.strip())
                    elif 'URI="' in line:
                        line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="'+self._reference(key, root, url, m[1])+'"', line)
                    lines.append(line)
                return ('\n'.join(lines)+'\n').encode(), 'application/vnd.apple.mpegurl'
            return raw, ('video/mp2t' if name.endswith('.ts') else 'audio/aac' if name.endswith('.aac') else 'video/mp4')
        finally:
            self.readers.release()

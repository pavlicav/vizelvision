from __future__ import annotations

import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

from .errors import EcpError


@dataclass(frozen=True)
class RokuApp:
    id: str | None
    name: str
    version: str | None = None


class EcpClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        sleeper: Callable[[float], None] = time.sleep,
        launch_timeout: float = 40.0,
        poll_interval: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._sleep = sleeper
        self.launch_timeout = launch_timeout
        self.poll_interval = poll_interval

    def _request(self, method: str, path: str) -> bytes:
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=b"" if method == "POST" else None,
            method=method,
            headers={"User-Agent": "VizelVision-RokuStream/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace").strip()
            raise EcpError(
                f"Roku ECP returned HTTP {exc.code}: {body or exc.reason}",
                details={"status": exc.code, "path": path},
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EcpError(
                f"Cannot reach Roku ECP at {self.base_url}: {exc}",
                details={"path": path},
            ) from exc
        if body.startswith(b"ECP command not allowed"):
            raise EcpError(body.decode("utf-8", errors="replace"), details={"path": path})
        return body

    @staticmethod
    def _xml(body: bytes, endpoint: str) -> ET.Element:
        try:
            return ET.fromstring(body)
        except ET.ParseError as exc:
            excerpt = body[:200].decode("utf-8", errors="replace")
            raise EcpError(
                f"Invalid XML from Roku {endpoint}: {excerpt}",
                details={"path": endpoint},
            ) from exc

    def device_info(self) -> dict[str, str]:
        root = self._xml(self._request("GET", "query/device-info"), "query/device-info")
        return {child.tag: child.text or "" for child in root}

    def apps(self) -> list[RokuApp]:
        root = self._xml(self._request("GET", "query/apps"), "query/apps")
        return [
            RokuApp(app.get("id"), (app.text or "").strip(), app.get("version"))
            for app in root.findall("app")
        ]

    def active_app(self) -> RokuApp:
        root = self._xml(self._request("GET", "query/active-app"), "query/active-app")
        app = root.find("app")
        if app is None:
            return RokuApp(None, "")
        return RokuApp(app.get("id"), (app.text or "").strip(), app.get("version"))

    def media_player(self) -> dict[str, object]:
        root = self._xml(
            self._request("GET", "query/media-player"), "query/media-player"
        )
        plugin = root.find("plugin")
        result: dict[str, object] = dict(root.attrib)
        if plugin is not None:
            result["plugin"] = {
                "id": plugin.get("id"),
                "name": plugin.get("name"),
            }
        media_format = root.find("format")
        if media_format is not None:
            result["format"] = dict(media_format.attrib)
        for field in ("position", "duration", "is_live", "runtime"):
            element = root.find(field)
            if element is not None:
                result[field] = element.text or ""
        return result

    def launch(self, app_id: str, *, content_id: str | None = None, media_type: str | None = None) -> None:
        safe_id = urllib.parse.quote(app_id, safe="")
        path = f"launch/{safe_id}"
        if content_id is not None:
            path += "?" + urllib.parse.urlencode({"contentID": content_id, "mediaType": media_type or "live"})
        deadline = time.monotonic() + self.launch_timeout
        try:
            self._request("POST", path)
        except EcpError as exc:
            # Older Roku firmware can accept launch but never finish its HTTP
            # response. Do not replay the command: confirm the resulting app.
            cause = exc.__cause__
            if isinstance(cause, urllib.error.URLError):
                cause = cause.reason
            if not isinstance(cause, TimeoutError):
                raise
            # A single read-back can race a launch still in progress. Keep
            # observing within the launch budget; never resend this POST.
            while True:
                try:
                    if self.active_app().id == app_id:
                        return
                except EcpError:
                    pass
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise exc
                self._sleep(min(max(self.poll_interval, 0.05), remaining))

    def keypress(self, key: str) -> None:
        safe_key = urllib.parse.quote(key, safe="_")
        self._request("POST", f"keypress/{safe_key}")

    def wait_for_active_app(
        self, app_id: str, *, timeout: float, interval: float
    ) -> RokuApp:
        deadline = time.monotonic() + timeout
        last = RokuApp(None, "")
        while time.monotonic() < deadline:
            last = self.active_app()
            if last.id == app_id:
                return last
            self._sleep(interval)
        raise EcpError(
            f"Timed out waiting for Roku app {app_id} to become active",
            details={"active_app": last.__dict__},
        )

    def wait_for_player(
        self, app_id: str, *, timeout: float, interval: float
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        last: dict[str, object] = {}
        while time.monotonic() < deadline:
            if self.active_app().id != app_id:
                raise EcpError("YouTube TV stopped being the active Roku app")
            last = self.media_player()
            plugin = last.get("plugin")
            plugin_id = plugin.get("id") if isinstance(plugin, dict) else None
            if last.get("state") == "play" and plugin_id == app_id:
                return last
            if last.get("error") == "true":
                raise EcpError("Roku media player reported an error", details=last)
            self._sleep(interval)
        raise EcpError(
            "Timed out waiting for YouTube TV playback",
            details={"media_player": last},
        )


def discover_roku(
    *, bind_address: str = "0.0.0.0", timeout: float = 2.0
) -> list[str]:
    """Return ECP base URLs found with Roku's documented SSDP request."""
    message = (\
        "M-SEARCH * HTTP/1.1\r\n"
        "Host: 239.255.255.250:1900\r\n"
        'Man: "ssdp:discover"\r\n'
        "ST: roku:ecp\r\n"
        "MX: 2\r\n\r\n"
    ).encode("ascii")
    locations: set[str] = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(timeout)
        sock.bind((bind_address, 0))
        sock.sendto(message, ("239.255.255.250", 1900))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                payload, _ = sock.recvfrom(65535)
            except socket.timeout:
                break
            headers = payload.decode("iso-8859-1", errors="replace").split("\r\n")
            for header in headers:
                if header.lower().startswith("location:"):
                    location = header.split(":", 1)[1].strip()
                    parsed = urllib.parse.urlsplit(location)
                    if parsed.hostname:
                        locations.add(f"http://{parsed.hostname}:8060")
    except OSError as exc:
        raise EcpError(f"Roku SSDP discovery failed: {exc}") from exc
    finally:
        sock.close()
    return sorted(locations)

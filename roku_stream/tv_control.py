"""Explicit TV-Thing controls, kept separate from the read-only guide client."""
from __future__ import annotations

import json
import math
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

from .errors import ConfigError
from .master import MasterStreamError


def target_from(data):
    source = data.get("source_id")
    channel = data.get("channel_id")
    if source not in ("tv-thing-digital", "tv-thing-analog"):
        raise ConfigError("Master input must be TV-Thing digital or analog")
    if source == "tv-thing-digital":
        if not isinstance(channel, str) or not channel or len(channel) > 200:
            raise ConfigError("Digital channel_id must be a catalog channel ID")
    else:
        # The source catalog exposes IDs as strings; normalize only decimal IDs.
        if isinstance(channel, str) and channel.isascii() and channel.isdigit():
            channel = int(channel)
        if type(channel) is not int or not 1 <= channel <= 135:
            raise ConfigError("Analog channel_id must be a channel number")
    quality = data.get("quality", "medium")
    if quality not in ("low", "medium", "high"):
        raise ConfigError("quality must be low, medium, or high")
    return {"source_id": source, "channel_id": channel, "quality": quality}


class TvControl:
    def __init__(self, config, *, opener=urlopen):
        self.config, self.opener = config, opener
        self.owner = "VizelVision master " + uuid.uuid4().hex[:12]

    def request(self, path, body=None):
        if not self.config.enabled:
            raise MasterStreamError("TV-Thing is disabled in the worker configuration")
        request = Request(self.config.base_url + "api/v1/" + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Accept": "application/json", "Content-Type": "application/json"})
        try:
            # A retune can wait for the old encoder and hardware to stop, and
            # a Roku tune may first check that the Roku still plays (about 5 s);
            # ordinary status/lease calls retain the short control timeout.
            timeout = 15 if path in ("tune", "roku/check", "roku/cancel") \
                else min(4, self.config.request_timeout_seconds)
            with self.opener(request, timeout=timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("Oversized response")
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("api_version") != "v1" or result.get("ok") is False:
                raise ValueError("Invalid control response")
            if path == "status" and (not isinstance(result.get("lanes"), dict) or not isinstance(result.get("locks"), dict)):
                raise ValueError("Invalid tuner status")
            return result
        except HTTPError as exc:
            message = "TV-Thing tuner is reserved by another owner" if exc.code == 423 else f"TV-Thing rejected {path} (HTTP {exc.code})"
            exc.close()
            raise MasterStreamError(message, details={"http_status": exc.code}) from exc
        except (URLError, OSError, ValueError) as exc:
            raise MasterStreamError(f"TV-Thing {path} failed ({type(exc).__name__}); no automatic tune retry") from exc

    def acquire(self, target):
        lease = Lease(self, target)
        try:
            lease.acquire()
        except MasterStreamError as exc:
            if exc.details.get("http_status") != 423:
                raise
            return SharedLease.join(self, target, exc)
        return lease


class Lease:
    def __init__(self, client, target):
        self.client, self.target = client, target
        self.lane = "digital" if target["source_id"] == "tv-thing-digital" else "analog"
        self.owner = client.owner
        self.token = None
        self.deadline = self.renew_at = 0.
        self.generation = None

    def _lock(self, renew):
        body = {"lane": self.lane, "owner": self.owner, "duration_seconds": 90, "until": "duration"}
        if renew:
            if not self.token or time.monotonic() >= self.deadline:
                raise MasterStreamError("Tuner lease expired; prepare the source again")
            body["token"] = self.token
        started = time.monotonic()
        wall_started = time.time()
        result = self.client.request("tuner/lock", body)
        token = result.get("token")
        if not isinstance(token, str) or not token:
            raise MasterStreamError("TV-Thing did not return a lease token; wait for its lease to expire")
        if renew and (result.get("renewed") is not True or token != self.token):
            # Upstream can acquire a NEW lease with an expired token. That does
            # not establish continuity of ownership. Release it and fail closed.
            self.token = token
            self.release()
            raise MasterStreamError("Tuner ownership changed; prepare the source again")
        self.token = token
        public_lock = result.get("lock")
        expiry = public_lock.get("expires_at") if isinstance(public_lock, dict) else None
        if type(expiry) not in (int, float) or not math.isfinite(expiry):
            raise MasterStreamError("TV-Thing returned an invalid lease expiry")
        # Never extend authority using a local wall-clock jump after acquisition.
        granted = min(90, expiry - wall_started)
        self.deadline = started + granted - 2
        self.renew_at = started + granted / 2
        if self.deadline - time.monotonic() < 8:
            raise MasterStreamError("TV-Thing granted too little lease time")

    def acquire(self):
        try:
            self._lock(False)
        except BaseException:
            self.release()
            raise

    def renew(self, *, force=False):
        if force or time.monotonic() >= self.renew_at:
            self._lock(True)

    def tune(self):
        target = self.target
        body = {"source": "digital" if self.lane == "digital" else "cable",
                "quality": target["quality"], "token": self.token,
                "channel_id" if self.lane == "digital" else "channel": target["channel_id"]}
        response = self.client.request("tune", body)
        self.generation = response.get("stream", {}).get("generation")
        if not self.generation:
            raise MasterStreamError("TV-Thing tune returned no stream generation")
        self._verify(response)

    def _verify(self, lane):
        if not isinstance(lane, dict) or not isinstance(lane.get("selection"), dict) or not isinstance(lane.get("stream"), dict):
            raise MasterStreamError("TV-Thing returned invalid lane metadata")
        selection = lane.get("selection") or {}
        selected = selection.get("id" if self.lane == "digital" else "channel")
        if selected != self.target["channel_id"] or lane.get("quality") != self.target["quality"]:
            raise MasterStreamError("TV-Thing selection changed; prepare the source again")
        stream = lane.get("stream") or {}
        if stream.get("generation") != self.generation:
            raise MasterStreamError("TV-Thing stream generation changed; prepare the source again")
        return stream

    def _check_owner(self, status):
        public = status.get("locks", {}).get(self.lane) or {}
        if not isinstance(public, dict) or public.get("owner") != self.owner or time.monotonic() >= self.deadline:
            raise MasterStreamError("TV-Thing tuner ownership was lost")

    def check(self):
        self.renew()
        status = self.client.request("status")
        self._check_owner(status)
        stream = self._verify(status.get("lanes", {}).get(self.lane) or {})
        if stream.get("state") == "failed":
            raise MasterStreamError("TV-Thing input failed")
        if not stream.get("ready"):
            return None
        playback = stream.get("playback")
        if not isinstance(playback, list):
            raise MasterStreamError("TV-Thing returned invalid playback descriptors")
        for descriptor in playback:
            if not isinstance(descriptor, dict):
                continue
            if descriptor.get("protocol") == "hls":
                if not isinstance(descriptor.get("url"), str):
                    raise MasterStreamError("TV-Thing returned an invalid playback URL")
                url = urljoin(self.client.config.base_url, descriptor.get("url", ""))
                base, parsed = urlsplit(self.client.config.base_url), urlsplit(url)
                if ((parsed.scheme, parsed.netloc) != (base.scheme, base.netloc)
                        or not parsed.path.startswith(base.path + "stream/")
                        or not parsed.path.endswith(".m3u8") or ".." in unquote(parsed.path).split("/")):
                    raise MasterStreamError("TV-Thing playback URL is outside its configured application")
                return url
        raise MasterStreamError("TV-Thing has no HLS playback descriptor")

    def release(self):
        if self.token:
            try:
                self.client.request("tuner/lock/release", {"lane": self.lane, "token": self.token})
            except MasterStreamError:
                # No stop/override/reacquire. The 90-second server lease bounds
                # cleanup after a network failure or an ungraceful worker exit.
                return False
            finally:
                self.token = None
        return True


class SharedLease(Lease):
    """Reads a lane another owner has locked, only while it carries the requested channel.

    TV-Thing's lock guards changes (tune/stop/scan), not viewing; e.g. its VCR
    records from a separate tap while the lane's HLS stays public. A shared
    lease never locks, tunes, or releases, and fails closed when the holder
    changes the selection or restarts the stream.
    """

    @classmethod
    def join(cls, client, target, refusal):
        status = client.request("status")
        lease = cls(client, target)
        lane = status.get("lanes", {}).get(lease.lane) or {}
        holder = status.get("locks", {}).get(lease.lane) or {}
        selection = lane.get("selection") if isinstance(lane.get("selection"), dict) else {}
        selected = selection.get("id" if lease.lane == "digital" else "channel")
        stream = lane.get("stream") if isinstance(lane.get("stream"), dict) else {}
        if selected != target["channel_id"] or not stream.get("generation"):
            who = holder.get("owner") if isinstance(holder, dict) else None
            why = holder.get("reason") if isinstance(holder, dict) else None
            label = selection.get("number") or selection.get("name") or selected or "nothing"
            raise MasterStreamError(
                f"TV-Thing {lease.lane} tuner is reserved by {who or 'another owner'}"
                f"{f' ({why})' if why else ''} on {label}; only that channel can be shared",
                details=refusal.details) from refusal
        # The holder chose the encoding; a reader cannot change it without tuning.
        lease.target = {**target, "quality": lane.get("quality")}
        lease.generation = stream["generation"]
        lease.shared_with = holder.get("owner") if isinstance(holder, dict) else None
        return lease

    def renew(self, *, force=False):
        pass

    def tune(self):
        # Joining is not a tune: confirm the holder's selection is still the one joined.
        self._verify((self.client.request("status").get("lanes", {}) or {}).get(self.lane) or {})

    def _check_owner(self, status):
        pass

    def release(self):
        return True


# The web app holds the Roku lane's lock (tv_roku.RokuHold) under this name:
# it navigates under it and keeps it while the worker plays the Roku. The
# worker's lease only checks that the lock is still ours.
ROKU_OWNER = "VizelVision master"


def same_roku_target(left, right):
    return all((left or {}).get(key) == (right or {}).get(key) for key in ("source_id", "channel_id", "date"))


class RokuLease(Lease):
    """The worker's view of TV Thing's Roku lane, while it plays a verified selection.

    It never locks, navigates, renews or releases: the web app holds the lock
    and moves the Roku. It fails closed when the lock is not ours any more, or
    the Roku's generation changes -- a navigation, the remote, a capture
    restart -- or its selection stops being the target.
    """

    def __init__(self, client, target, *, generation=None, resolved_source=None):
        super().__init__(client, target)
        self.lane = "roku"
        self.owner = ROKU_OWNER
        self.generation = generation
        self.resolved_source = resolved_source
        # The lock's expiry is TV Thing's to enforce; _check_owner reads it each check.
        self.deadline = float("inf")

    @classmethod
    def adopt(cls, client, target, handoff):
        """The worker's side of a handoff: the generation the web app verified."""
        if not isinstance(handoff, dict) or not isinstance(handoff.get("generation"), str) \
                or not handoff["generation"]:
            raise MasterStreamError("The Roku must be prepared by master control before its feed is used")
        return cls(client, target, generation=handoff["generation"],
                   resolved_source=handoff.get("resolved_source"))

    def acquire(self):
        raise MasterStreamError("The Roku lane is locked by the web app, not the worker")

    def renew(self, *, force=False):
        pass

    def release(self):
        return True

    def _check_owner(self, status):
        public = status.get("locks", {}).get(self.lane) or {}
        if not isinstance(public, dict) or public.get("owner") != self.owner:
            who = public.get("owner") if isinstance(public, dict) else None
            raise MasterStreamError(f"The Roku's lock was taken over{f' by {who}' if who else ''}")

    def _verify(self, lane):
        if not isinstance(lane, dict) or not isinstance(lane.get("stream"), dict):
            raise MasterStreamError("TV-Thing returned invalid Roku lane metadata")
        selection = lane.get("selection") or {}
        if selection.get("manual") or not same_roku_target(selection, self.target):
            raise MasterStreamError("The Roku no longer shows the verified selection; prepare it again")
        stream = lane["stream"]
        if stream.get("generation") != self.generation:
            raise MasterStreamError("The Roku changed since it was verified; prepare it again")
        return stream

    def tune(self):
        # Adopting is not tuning: confirm the Roku still shows what was verified, under our lock.
        status = self.client.request("status")
        self._check_owner(status)
        self._verify((status.get("lanes", {}) or {}).get("roku") or {})

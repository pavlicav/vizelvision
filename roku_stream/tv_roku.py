"""The source Roku, now TV Thing's Roku lane: navigation and verification there.

Since 2026-10-06 TV Thing owns the Roku and its HD PVR capture (controller,
screen recognition, the capture and its HLS). VizelVision puts a target on it
under the roku lane's lock and plays the lane's stream like a tuner's.

The web app holds that lock (RokuHold). It navigates under it, and keeps it
while the master worker plays the Roku, whose lease (tv_control.RokuLease)
only checks that the lock, the selection and its generation are unchanged.
The token is kept beside the master socket, so a web restart keeps the Roku
on air instead of dropping it.

TV Thing decides whether the Roku must move: a recent verified selection is
reused, and a Roku that still plays its selection after a capture blip is
resumed after a brief check, both without navigating.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time

from .errors import ControlBusyError, CueCancelledError
from .master import MasterStreamError
from .tv_control import ROKU_OWNER, same_roku_target

POLL_SECONDS = .5
CANCEL_WAIT_SECONDS = 20
LOCK_SECONDS = 90
RENEW_SECONDS = 30
IDLE_RELEASE_SECONDS = 60
# TV Thing's reading of the Roku's player older than this says nothing about it now.
PLAYER_MAX_AGE = 30


class RokuHold:
    """The roku lane's lock, held by the web app while the Roku is wanted.

    ``in_use()`` says whether master has a Roku input prepared or on air, or an
    operation on the Roku is running; while it does the lock is renewed, and a
    minute after it stops the lock is released for people and the VCR.
    """

    def __init__(self, control, token_path, *, in_use=lambda: False, clock=time.monotonic):
        self.control, self.token_path, self.in_use = control, token_path, in_use
        self._clock = clock
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._idle_since = None
        self.token = self._load()

    def _load(self):
        try:
            record = json.loads(self.token_path.read_text())
            token = record.get("token") if isinstance(record, dict) else None
            return token if isinstance(token, str) and token else None
        except (OSError, ValueError):
            return None

    def _save(self):
        try:
            if self.token is None:
                self.token_path.unlink(missing_ok=True)
                return
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.token_path.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump({"token": self.token}, handle)
            os.replace(temporary, self.token_path)
        except OSError as exc:
            # Only costs keeping the Roku across a web restart.
            logging.getLogger(__name__).warning("Could not keep the Roku lock's token: %s", exc)

    def hold(self):
        """Hold the Roku, renewing our lock or taking a free one. Returns the token.

        Someone else's lock is never overridden: ControlBusyError.
        """
        with self._lock:
            body = {"lane": "roku", "owner": ROKU_OWNER, "duration_seconds": LOCK_SECONDS,
                    "until": "duration", "reason": "VizelVision master: the Roku is on air or being prepared"}
            if self.token:
                body["token"] = self.token
            try:
                result = self.control.request("tuner/lock", body)
            except MasterStreamError as exc:
                if exc.details.get("http_status") == 423:
                    self.token = None
                    self._save()
                    raise ControlBusyError("The Roku is locked by someone else in TV-Thing") from exc
                raise
            token = result.get("token")
            expiry = (result.get("lock") or {}).get("expires_at")
            if not isinstance(token, str) or not token or type(expiry) not in (int, float) \
                    or not math.isfinite(expiry):
                raise MasterStreamError("TV-Thing returned an invalid Roku lock")
            if token != self.token:
                self.token = token
                self._save()
            self._idle_since = None
            return token

    def release(self):
        with self._lock:
            if not self.token:
                return
            try:
                self.control.request("tuner/lock/release", {"lane": "roku", "token": self.token})
            except MasterStreamError as exc:
                logging.getLogger(__name__).warning("Could not release the Roku: %s", exc)
                return  # It expires within LOCK_SECONDS anyway.
            self.token = None
            self._save()

    def keep(self):
        """One renewal pass: renew while in use, release a minute after."""
        with self._lock:
            if not self.token:
                return
            if self.in_use():
                try:
                    self.hold()
                except (MasterStreamError, ControlBusyError) as exc:
                    logging.getLogger(__name__).warning("Could not renew the Roku lock: %s", exc)
                return
            now = self._clock()
            if self._idle_since is None:
                self._idle_since = now
            if now - self._idle_since >= IDLE_RELEASE_SECONDS:
                self.release()

    def run(self):
        while not self._stopping.wait(RENEW_SECONDS):
            try:
                self.keep()
            except Exception as exc:  # The keeper must not die.
                logging.getLogger(__name__).warning("Roku lock keeper: %s", exc)

    def start(self):
        thread = threading.Thread(target=self.run, name="roku-lock", daemon=True)
        thread.start()
        if self.token:
            # A web restart: pick the lock up again at once, before it lapses.
            try:
                self.keep()
            except Exception as exc:
                logging.getLogger(__name__).warning("Roku lock after restart: %s", exc)
        return thread

    def stop(self):
        # The lock is kept: the worker may still be playing the Roku.
        self._stopping.set()


class TvRoku:
    def __init__(self, control, hold, *, sleep=time.sleep, clock=time.monotonic):
        self.control, self.hold = control, hold
        self._sleep, self._clock = sleep, clock

    # -- what TV Thing says -------------------------------------------------
    def lane(self):
        """(lanes.roku, its public lock) from TV Thing's status."""
        status = self.control.request("status")
        lane = (status.get("lanes") or {}).get("roku")
        if not isinstance(lane, dict) or not lane.get("available", True):
            raise MasterStreamError("TV-Thing has no Roku lane")
        return lane, (status.get("locks") or {}).get("roku")

    @staticmethod
    def _roku(lane):
        return lane.get("roku") or {}

    def ready(self, target):
        """Whether the Roku shows target, verified recently on its current capture."""
        try:
            lane, _lock = self.lane()
        except MasterStreamError:
            return False
        selection = lane.get("selection") or {}
        operation = self._roku(lane).get("operation") or {}
        return bool(not selection.get("manual") and same_roku_target(selection, target)
                    and selection.get("reusable") and not operation.get("active"))

    def playing(self, target):
        """Feed recovery: whether the Roku still plays target, briefly checked. Never navigates."""
        try:
            lane, _lock = self.lane()
            selection = lane.get("selection") or {}
            if selection.get("manual") or not same_roku_target(selection, target):
                return False
            check = self.control.request("roku/check", {})
        except MasterStreamError as exc:
            logging.getLogger(__name__).warning("Could not check the Roku: %s", exc)
            return False
        if not check.get("playing"):
            logging.getLogger(__name__).warning("The Roku no longer plays it (%s)", check.get("reason"))
        return bool(check.get("playing"))

    def player(self):
        """What TV Thing last read from the Roku (it asks every few seconds), for the on-air
        watch: {'playing': bool, 'reason'}. None when it cannot say: a navigation running, the
        Roku moved by hand, nothing verified, or no fresh reading. Never asks the Roku itself."""
        try:
            lane, _lock = self.lane()
        except MasterStreamError:
            return None
        roku, selection = self._roku(lane), lane.get("selection") or {}
        want = (selection.get("app") or {}).get("id")
        player = roku.get("player") or {}
        data, age = player.get("data") or {}, player.get("age_seconds")
        if ((roku.get("operation") or {}).get("active") or selection.get("manual") or not want
                or player.get("error") or not data or type(age) not in (int, float) or age > PLAYER_MAX_AGE):
            return None
        app, media = data.get("app") or {}, data.get("media_player") or {}
        if app.get("id") != want:
            return {"playing": False, "reason": f"the Roku is in {app.get('name') or 'its home screen'}"}
        if media.get("state") != "play" or media.get("error") == "true":
            return {"playing": False, "reason": f"its player is {media.get('state') or 'stopped'}"}
        return {"playing": True, "reason": None}

    def snapshot(self):
        """The last verified selection, in the shape the control room shows."""
        try:
            lane, _lock = self.lane()
        except MasterStreamError:
            return None
        selection = lane.get("selection")
        if not selection or selection.get("manual"):
            return None
        target = {key: selection[key] for key in ("source_id", "channel_id", "date") if key in selection}
        reusable = bool(selection.get("reusable"))
        return {"target": target, "prepared_at": selection.get("verified_at"),
                "selection_id": (lane.get("stream") or {}).get("generation"),
                "resolved_source": selection.get("resolved_source"),
                "age_seconds": selection.get("age_seconds"),
                "max_age_seconds": self._roku(lane).get("reuse_max_age_seconds"),
                "reusable": reusable,
                "reason": None if reusable else
                "The Roku's capture restarted or its verification is old; it is checked again first"}

    # -- preparing ----------------------------------------------------------
    def prepare(self, target, *, force=False, navigate=True, resume=True, stop=lambda: None):
        """Put target on the Roku under our lock. Returns the worker's handoff:
        {"generation", "resolved_source"}.

        ``stop()`` returns a reason to give up ("cancelled", "late") or None; a
        navigation is then stopped on TV Thing and CueCancelledError raised. A
        lock someone else holds raises ControlBusyError: it is never overridden.
        """
        token = self.hold.hold()
        body = {"source": target["source_id"], "channel_id": target["channel_id"], "token": token,
                "force": bool(force), "navigate": bool(navigate), "resume": bool(resume)}
        if target.get("date"):
            body["date"] = target["date"]
        try:
            response = self.control.request("tune", body)
        except MasterStreamError as exc:
            status = exc.details.get("http_status")
            if status == 409 and not navigate:
                raise MasterStreamError("No recent matching Roku preparation; prepare it first") from exc
            if status == 423:
                raise ControlBusyError("The Roku was taken over by someone else in TV-Thing") from exc
            raise
        if not response.get("reused"):
            self._follow((response.get("operation") or {}).get("id"), stop)
        lane, lock = self.lane()
        if not lock or lock.get("owner") != ROKU_OWNER:
            raise MasterStreamError("The Roku's lock was taken over during its navigation")
        selection = lane.get("selection") or {}
        if selection.get("manual") or not same_roku_target(selection, target):
            raise MasterStreamError("The Roku did not end on the requested channel or game")
        generation = (lane.get("stream") or {}).get("generation")
        if not generation:
            raise MasterStreamError("The Roku's capture is not running")
        return {"generation": generation, "resolved_source": selection.get("resolved_source")}

    def _follow(self, operation_id, stop):
        """Wait out a navigation, renewing the lock and honouring stop()."""
        renew_at = self._clock() + RENEW_SECONDS
        while True:
            reason = stop()
            if reason:
                self._cancel()
                raise CueCancelledError(f"Roku navigation stopped ({reason})")
            if self._clock() >= renew_at:
                self.hold.hold()
                renew_at = self._clock() + RENEW_SECONDS
            lane, _lock = self.lane()
            operation = self._roku(lane).get("operation") or {}
            if operation_id and operation.get("id") != operation_id:
                raise MasterStreamError("Another navigation replaced this one in TV-Thing")
            state = operation.get("state")
            if state == "succeeded":
                return
            if state == "failed":
                raise MasterStreamError(f"The Roku could not find it: {operation.get('message')}")
            if state == "cancelled":
                raise CueCancelledError("The Roku's navigation was stopped in TV-Thing")
            self._sleep(POLL_SECONDS)

    def _cancel(self):
        try:
            self.control.request("roku/cancel", {"token": self.hold.token})
        except MasterStreamError as exc:
            logging.getLogger(__name__).warning("Could not stop the Roku's navigation: %s", exc)
            return
        deadline = self._clock() + CANCEL_WAIT_SECONDS
        while self._clock() < deadline:
            try:
                lane, _lock = self.lane()
            except MasterStreamError:
                return
            if not (self._roku(lane).get("operation") or {}).get("active"):
                return
            self._sleep(POLL_SECONDS)

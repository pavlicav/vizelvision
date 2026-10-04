"""Periodic viewer Roku / cable return checks. Never override a TV-Thing lock.

The manual app launch talks only to the viewer Roku over ECP; it never touches
TV-Thing, so it works while TV-Thing is locked.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from .ecp import EcpClient
from .feed_match import capture_return
from .errors import ConfigError, ControlBusyError, RokuStreamError
from .tv_control import Lease, TvControl

DEFAULTS = {'enabled': False, 'roku_ip': '10.0.0.111', 'cable_channel': 70,
            'app_id': 'dev', 'interval_hours': 6}
RETRY_SECONDS = 15 * 60
LOG = logging.getLogger(__name__)


class Deferred(Exception):
    pass


class ProductionMonitor:
    def __init__(self, config, *, tv=None, ecp_factory=EcpClient,
                 capture=capture_return, clock=time.time, sleeper=time.sleep):
        self.config = config
        self.path = Path(config.master.socket_path).with_name('production-monitor.json')
        self.tv = tv or TvControl(config.tv_thing)
        self.tv.owner = 'VizelVision production monitor ' + self.tv.owner.rsplit(' ', 1)[-1]
        self.ecp_factory, self.capture, self.clock, self.sleep = ecp_factory, capture, clock, sleeper
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread = None
        self.running = self.pending = False
        self.storage_error = None
        self.state = {'settings': copy.deepcopy(DEFAULTS), 'next_check_at': None,
                      'last_check': None, 'history': []}
        try:
            saved = json.loads(self.path.read_text())
            saved['settings'] = self.validate(saved['settings'])
            if (not isinstance(saved.get('history'), list)
                    or not isinstance(saved.get('last_check'), (dict, type(None)))
                    or (saved.get('next_check_at') is not None and
                        (type(saved['next_check_at']) not in (int, float) or not math.isfinite(saved['next_check_at'])))):
                raise ValueError('Invalid monitor state')
            self.state.update({k: saved[k] for k in self.state})
            last = self.state['last_check']
            if (last and last.get('status') in ('healthy', 'recovered')
                    and (last.get('cable') or {}).get('comparison', {}).get('matches_master') is not True):
                last.update(status='inconclusive', message='Previous check did not compare the master picture; run a new check')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, ConfigError) as exc:
            self.storage_error = f'Cannot load monitor settings ({type(exc).__name__}); monitoring disabled'

    @staticmethod
    def validate(value):
        if not isinstance(value, dict) or set(value) != set(DEFAULTS):
            raise ConfigError('Provide enabled, roku_ip, cable_channel, app_id and interval_hours')
        if type(value['enabled']) is not bool:
            raise ConfigError('enabled must be true or false')
        try:
            address = ipaddress.IPv4Address(value['roku_ip']) if isinstance(value['roku_ip'], str) else None
            if address is None or not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
                raise ValueError()
        except ValueError as exc:
            raise ConfigError('roku_ip must be a private LAN IPv4 address') from exc
        if type(value['cable_channel']) is not int or not 1 <= value['cable_channel'] <= 135:
            raise ConfigError('cable_channel must be an integer from 1 through 135')
        if not isinstance(value['app_id'], str) or not re.fullmatch(r'dev|[0-9]{1,12}', value['app_id']):
            raise ConfigError('app_id must be dev or a numeric Roku app ID')
        hours = value['interval_hours']
        if type(hours) not in (int, float) or not math.isfinite(hours) or not 1 <= hours <= 168:
            raise ConfigError('interval_hours must be between 1 and 168')
        return copy.deepcopy(value)

    def _persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.production-monitor-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.state, stream, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def status(self):
        with self.lock:
            return {**copy.deepcopy(self.state), 'running': self.running, 'pending': self.pending,
                    'storage_error': self.storage_error, 'retry_seconds': RETRY_SECONDS}

    def save(self, value):
        settings = self.validate(value)
        with self.lock:
            if self.running or self.pending:
                raise ControlBusyError('Wait for the current production check before changing its settings')
            before = copy.deepcopy(self.state)
            self.state['settings'] = settings
            self.state['next_check_at'] = self.clock() if settings['enabled'] else None
            try:
                self._persist()
            except Exception:
                self.state = before
                raise
            self.storage_error = None
        self.wake.set()
        return self.status()

    def request_check(self):
        with self.lock:
            if self.running or self.pending:
                raise ControlBusyError('A production check is already queued or running')
            self.pending = True
        self.wake.set()
        return self.status()

    def launch_app(self):
        """Launch VizelVision on the viewer Roku now. ECP only; no TV-Thing lock or tune."""
        with self.lock:
            if self.running:
                raise ControlBusyError('A production check is running; launch after it finishes')
            settings = copy.deepcopy(self.state['settings'])
        ecp = self.ecp_factory(f"http://{settings['roku_ip']}:8060", launch_timeout=20)
        if not any(app.id == settings['app_id'] and app.name.casefold() == 'vizelvision' for app in ecp.apps()):
            raise RokuStreamError('Configured app ID is not an installed VizelVision app; no launch sent')
        ecp.launch(settings['app_id'])
        return {'launched': True, 'app_id': settings['app_id'], 'roku_ip': settings['roku_ip'],
                'active_app': ecp.active_app().__dict__}

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='production-monitor', daemon=True)
            self.thread.start()

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=25)

    def _run(self):
        while not self.stopping.is_set():
            self.wake.clear()
            try:
                self.tick()
            except Exception as exc:
                LOG.exception('Production monitor check failed')
                with self.lock:
                    self.storage_error = f'Monitor failed ({type(exc).__name__})'
            self.wake.wait(5)

    def tick(self):
        with self.lock:
            due = self.state['next_check_at']
            if self.running or not (self.pending or (self.state['settings']['enabled'] and
                                                     (due is None or self.clock() >= due))):
                return
            self.pending = False
            self.running = True
            settings = copy.deepcopy(self.state['settings'])
            # Persist the attempt before any device commands. Restarting the web
            # process must not cause an immediate repeat of a recovery command.
            self.state['next_check_at'] = self.clock() + settings['interval_hours'] * 3600 if settings['enabled'] else None
            try:
                self._persist()
            except Exception:
                self.running = False
                raise
        result = {'started_at': self.clock(), 'settings': settings, 'status': 'error',
                  'recovery_attempted': False, 'roku': None, 'cable': None}
        try:
            self._check(settings, result)
        except Deferred as exc:
            result.update(status='deferred', message=str(exc))
        except Exception as exc:
            result.update(status='error', message=str(exc))
        finally:
            result['finished_at'] = self.clock()
            with self.lock:
                self.state['last_check'] = result
                summary = {k: result[k] for k in ('started_at', 'finished_at', 'status', 'message', 'recovery_attempted')}
                self.state['history'] = ([summary] + self.state['history'])[:20]
                delay = RETRY_SECONDS if result['status'] == 'deferred' else settings['interval_hours'] * 3600
                self.state['next_check_at'] = self.clock() + delay if settings['enabled'] else None
                self.running = False
                self._persist()
                self.storage_error = None

    def _available(self, status, *, owned=False):
        locks, lanes = status.get('locks'), status.get('lanes')
        if not isinstance(locks, dict) or not {'analog', 'digital'} <= locks.keys() or not isinstance(lanes, dict):
            raise Deferred('TV-Thing lock status is incomplete; check deferred')
        for lane, held in locks.items():
            if held is not None and not (owned and lane == 'analog' and isinstance(held, dict) and held.get('owner') == self.tv.owner):
                owner = held.get('owner', 'another owner') if isinstance(held, dict) else 'unknown owner'
                raise Deferred(f'TV-Thing {lane} is locked by {owner}; retry in 15 minutes')
        if status.get('busy_reason') or status.get('recording') or any((status.get('scanning') or {}).values()):
            raise Deferred('TV-Thing is busy recording or scanning; retry in 15 minutes')
        analog = lanes.get('analog')
        if not isinstance(analog, dict) or not isinstance(analog.get('stream'), dict):
            raise Deferred('TV-Thing analog status is incomplete; check deferred')
        return analog

    @staticmethod
    def _observe(ecp, app_id):
        active, player = ecp.active_app(), ecp.media_player()
        plugin = player.get('plugin') or {}
        playing = active.id == app_id and player.get('state') == 'play' and player.get('error') != 'true' and plugin.get('id') == app_id
        return {'active_app': active.__dict__, 'player': player, 'playing': playing}

    def _guard(self, lease):
        if self.stopping.is_set():
            raise Deferred('Service stopping; check deferred')
        lease.renew()
        status = self.tv.request('status')
        self._available(status, owned=True)
        lease._check_owner(status)
        return status

    def _check(self, settings, result):
        # Fail closed before even contacting the Roku, including manual checks.
        analog = self._available(self.tv.request('status'))
        selection, stream = analog.get('selection') or {}, analog['stream']
        if stream.get('active') and selection.get('channel') != settings['cable_channel']:
            raise Deferred('TV-Thing is viewing another cable channel; retry in 15 minutes')
        target = {'source_id': 'tv-thing-analog', 'channel_id': settings['cable_channel'],
                  'quality': analog.get('quality') or 'medium'}
        # Deliberately use an exclusive Lease, never SharedLease or override.
        lease = Lease(self.tv, target)
        tuned = False
        was_active = False
        try:
            try:
                lease.acquire()
            except RokuStreamError as exc:
                if exc.details.get('http_status') == 423:
                    raise Deferred('TV-Thing was locked before acquisition; retry in 15 minutes') from exc
                raise
            # Re-read under the lease: another client could tune before acquisition.
            analog = self._guard(lease)['lanes']['analog']
            was_active = bool(analog['stream'].get('active'))
            if was_active and (analog.get('selection') or {}).get('channel') != settings['cable_channel']:
                raise Deferred('TV-Thing changed cable channel before acquisition; retry in 15 minutes')
            ecp = self.ecp_factory(f"http://{settings['roku_ip']}:8060", launch_timeout=20)
            device = ecp.device_info()
            result['device'] = {key: device.get(key) for key in ('model-name', 'model-number', 'friendly-device-name')}
            apps = ecp.apps()
            if not any(app.id == settings['app_id'] and app.name.casefold() == 'vizelvision' for app in apps):
                raise RokuStreamError('Configured app ID is not an installed VizelVision app; no launch sent')
            result['roku'] = self._observe(ecp, settings['app_id'])
            result['roku_before'] = copy.deepcopy(result['roku'])
            if not result['roku']['playing']:
                # Allow an existing app to finish buffering before recovery.
                for _ in range(3):
                    self.sleep(2)
                    self._guard(lease)
                    result['roku'] = self._observe(ecp, settings['app_id'])
                    if result['roku']['playing']:
                        break
                if not result['roku']['playing']:
                    self._guard(lease)
                    result['recovery_attempted'] = True
                    ecp.launch(settings['app_id'])
                    for _ in range(10):
                        self.sleep(2)
                        self._guard(lease)
                        result['roku'] = self._observe(ecp, settings['app_id'])
                        if result['roku']['playing']:
                            break
            if not result['roku']['playing']:
                result.update(status='unhealthy', message='VizelVision playback did not resume after one launch attempt')
                return
            self._guard(lease)
            # Even when already on channel 70, tune is token protected and reuses
            # the current stream. Do not stop an existing viewer's stream later.
            tuned = True
            lease.tune()
            url = None
            for _ in range(15):
                self._guard(lease)
                url = lease.check()
                if url:
                    break
                self.sleep(1)
            if not url:
                raise RokuStreamError('Cable return stream did not become ready')
            # Renew immediately before the bounded concurrent captures (55s).
            lease.renew(force=True)
            result['cable'] = self.capture(url, self.config.master.hls_url + 'index.m3u8')
            self._guard(lease)
            if lease.check() != url:
                raise RokuStreamError('Cable return changed while sampling')
            result['roku'] = self._observe(ecp, settings['app_id'])
            if not result['roku']['playing']:
                result.update(status='unhealthy', message='Roku playback stopped during cable verification')
            elif result['cable'].get('comparison', {}).get('matches_master') is False:
                result.update(status='unhealthy', message='Cable picture does not match the VizelVision master within the sampled delay window')
            elif result['cable'].get('comparison', {}).get('matches_master') is not True:
                result.update(status='inconclusive', message='Roku reports playback, but a match to the VizelVision master could not be verified')
            else:
                result.update(status='recovered' if result['recovery_attempted'] else 'healthy',
                              message='Cable ' + str(settings['cable_channel']) + ' picture matches the VizelVision master')
        finally:
            if lease.token:
                try:
                    if tuned and not was_active:
                        # Stop only our temporary stream while we still own it.
                        status = self.tv.request('status')
                        lease._check_owner(status)
                        lease._verify(status['lanes']['analog'])
                        self.tv.request('stop', {'lane': 'analog', 'token': lease.token})
                except Exception as exc:
                    result['cleanup_error'] = str(exc)
                if not lease.release():
                    result['cleanup_error'] = 'Lease release failed; it will expire automatically'

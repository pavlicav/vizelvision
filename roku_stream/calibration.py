"""Read-only capture diagnostics. Never open a second video reader or change inputs."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from .direct_capture import DirectCaptureFeedback


def device_diagnostics(device: Path, usb_root: Path = Path('/sys/bus/usb/devices')) -> dict:
    result = {'path': str(device), 'resolved_path': str(device.resolve()), 'state': 'missing',
              'label': 'Capture device missing', 'usb': None}
    try:
        info = device.stat()
        if not stat.S_ISCHR(info.st_mode):
            result.update(state='invalid', label='Configured path is not a capture device')
        elif not os.access(device, os.R_OK | os.W_OK):
            result.update(state='permission_denied', label='Capture device permission denied')
        else:
            result.update(state='ready', label='Capture device available')
    except FileNotFoundError:
        pass
    except OSError as exc:
        result.update(state='inaccessible', label='Capture device inaccessible', error=str(exc))

    # Match the configured unit's serial, not an arbitrary Hauppauge on the bus.
    # A reconnect can keep USB visible while leaving the video driver unbound.
    try:
        for entry in usb_root.iterdir():
            try:
                serial = (entry / 'serial').read_text().strip()
                product = (entry / 'product').read_text().strip()
                if not serial or f'_{serial}-video-index' not in device.name:
                    continue
                interfaces = list(entry.glob(entry.name + ':*'))
                drivers = sorted({(p / 'driver').resolve().name for p in interfaces if (p / 'driver').exists()})
                result['usb'] = {'port': entry.name, 'product': product, 'serial': serial, 'drivers': drivers}
                if result['state'] == 'missing':
                    result.update(state='driver_missing' if not drivers else 'node_missing',
                                  label='USB detected · capture driver not attached' if not drivers
                                  else 'USB detected · capture path missing')
                break
            except OSError:
                continue
    except OSError:
        pass
    return result


def calibration_status(feedback: DirectCaptureFeedback) -> dict:
    signal = feedback.input_signal()
    rate = signal.get('rate')
    matches = (signal['state'] == 'locked' and signal.get('width') == 1280
               and signal.get('height') == 720 and signal.get('scan') == 'progressive'
               and isinstance(rate, (int, float))
               and any(abs(rate - expected) < .02 for expected in (59.94, 60)))
    return {'signal': signal, 'device': device_diagnostics(feedback.device),
            'capture': feedback.status(), 'input_index': feedback.config.input_index,
            'source_name': feedback.config.source_name,
            'target': {'label': '720p60', 'width': 1280, 'height': 720,
                       'scan': 'progressive', 'rates': [59.94, 60], 'matches': matches}}

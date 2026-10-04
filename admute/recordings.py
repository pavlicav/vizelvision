"""Training recordings: games recorded on TV-Thing, then learnt from.

  python -m admute.recordings sync        plan timers for upcoming games, process finished ones
  python -m admute.recordings status      what is planned, recording and processed

Run every 10 minutes by vizelvision-admute-recordings.timer (a oneshot: a long
processing run simply delays the next).

Plan. For each game in VizelVision's own schedule (GET /v1/playback) in the next
HORIZON that airs on an over-the-air network TV-Thing can tune (NETWORKS), a TV-Thing
timer records it from LEAD before its start to LENGTH after. Skipped, with a reason:
  * a timer already covers it (the operator's own included)
  * VizelVision means to air a *different* TV-Thing channel meanwhile (TV-Thing can
    stream the channel it is recording, but cannot change channel while it records)
  * the operator cancelled it on the page (admute-recordings-skip.json)
Recordings stay in TV-Thing's library, like any other.

Process. Once TV-Thing has finished a recording:
  1. picture and sound features, Whisper words and sound fingerprints (cached, as for
     any tape: admute.replay / admute.speech / admute.fingerprint);
  2. for an MLB game, its breaks from the play-by-play (admute.seed.game_spans: the
     broadcast's lag found from black frames, edges snapped to them, kept only if the
     detector finds them ad-like), sent to the sidecar's known-ads inbox;
  3. training labels in admute/truth/auto/: those breaks as "ad", play in progress
     (first pitch to last pitch of each half-inning) as "show", the rest "ignore".
     The next `admute.train` uses them.
State: admute-recordings.json beside the master socket (the page reads it).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from roku_stream.admute_settings import AdMuteSettings  # noqa: E402

NETWORKS = {"FOX": "WTTG", "NBC": "WRC", "CBS": "WUSA", "ABC": "WJLA"}   # the Washington stations
LEAD, LENGTH = 5 * 60, 4 * 3600
HORIZON = 24 * 3600
LIVE_AFTER = 10.0
AUTO_TRUTH = ROOT / "admute" / "truth" / "auto"


class Recordings:
    def __init__(self, config_path: str):
        cfg = json.loads(Path(config_path).read_text())
        sock = Path(cfg["master"]["socket_path"])
        if not sock.is_absolute():
            sock = Path(config_path).resolve().parent / sock
        self.state_path = sock.with_name("admute-recordings.json")
        self.skip_path = sock.with_name("admute-recordings-skip.json")
        self.settings = AdMuteSettings(sock, lenient=True).read()
        server = cfg.get("server", {})
        self.web = f"http://127.0.0.1:{server.get('port', 6969)}"
        self.api_key = server.get("api_key")
        self.tv = (cfg.get("tv_thing") or {}).get("base_url", "http://127.0.0.1:8080/").rstrip("/")
        self.state = self._load()

    # io -------------------------------------------------------------------------------
    def _load(self):
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {"recordings": {}, "skipped": {}, "updated": None}

    def save(self):
        self.state["updated"] = round(time.time(), 1)
        tmp = self.state_path.with_name(".admute-recordings.tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        os.replace(tmp, self.state_path)

    def _get(self, url, headers=None):
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=20) as r:
            return json.load(r)

    def _post(self, url, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def playback(self):
        until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + HORIZON))
        return self._get(f"{self.web}/v1/playback?until={until}",
                         {"X-API-Key": self.api_key} if self.api_key else {})["segments"]

    def tv_recordings(self):
        return self._get(f"{self.tv}/api/v1/recordings")

    def channels(self):
        items = self._get(f"{self.tv}/api/v1/sources/digital").get("items") or []
        return {c["name"].split("-")[0].upper(): c for c in items if c.get("name")}

    # plan -------------------------------------------------------------------------------
    @staticmethod
    def key(game):
        return f"{game.get('league', 'mlb')}-{game.get('game_pk')}"

    def plan(self):
        if not self.settings.get("record_games", True):
            return []
        segments = self.playback()
        tv = self.tv_recordings()
        stations = self.channels()
        try:
            skip = set(json.loads(self.skip_path.read_text()).get("games", []))
        except (OSError, ValueError):
            skip = set()
        timers = tv.get("timers") or []
        now, made = time.time(), []
        for seg in segments:
            game = seg.get("game")
            if seg.get("kind") != "game" or not game or not game.get("game_pk"):
                continue
            key = self.key(game)
            if key in self.state["recordings"] or key in skip:
                continue
            target = seg.get("target") or {}
            if target.get("source_id") == "tv-thing-digital":
                channel = next((c for c in stations.values() if c["id"] == target.get("channel_id")), None)
            else:
                station = NETWORKS.get(str(target.get("channel_id") or "").upper())
                channel = stations.get(station) if station else None
            if channel is None:              # cable only: TV-Thing cannot record it
                if _ts(seg["start"]) > now - 3600:
                    self.state["skipped"][key] = {"title": game.get("title"), "start": round(_ts(seg["start"])),
                                                  "why": f"on {target.get('channel_id')}: cable only, TV-Thing cannot record it"}
                continue
            start = _ts(seg["start"]) - LEAD
            end = start + LEAD + LENGTH
            if start < now - 60 or start > now + HORIZON:
                continue
            overlap = [t for t in timers if t.get("start", 0) < end and t.get("end", 0) > start
                       and t.get("status") in ("scheduled", "recording")]
            same = [t for t in overlap if t.get("channel_id") == channel["id"]]
            if same:      # already being recorded (the operator's own timer, say): learn from that one
                t = same[0]
                self.state["recordings"][key] = {"game": game, "timer": t["id"], "channel": channel["name"],
                                                 "channel_id": channel["id"], "start": t["start"], "end": t["end"],
                                                 "title": t.get("title") or game.get("title"), "status": "scheduled",
                                                 "adopted": True}
                self.state["skipped"].pop(key, None)
                print(f"learning from the existing timer {t['id']} for {game.get('title')}")
                continue
            why = None
            if overlap:
                t = overlap[0]
                why = (f"TV-Thing is recording {t.get('channel_name') or t.get('channel_id')} then"
                       + (f" ({t.get('title')})" if t.get("title") else "") + ": one channel at a time")
            for other in segments:
                tgt = other.get("target") or {}
                if (tgt.get("source_id") == "tv-thing-digital" and tgt.get("channel_id") != channel["id"]
                        and _ts(other["start"]) < end and _ts(other["end"]) > start):
                    why = f"VizelVision airs {tgt.get('channel_id')} from TV-Thing then"
            if why:
                self.state["skipped"][key] = {"title": game.get("title"), "start": round(start + LEAD), "why": why}
                continue
            title = f"{game.get('title') or key} {time.strftime('%m-%d', time.localtime(start + LEAD))} (ad training)"
            try:
                got = self._post(f"{self.tv}/api/v1/recordings", {"mode": "manual", "channel_id": channel["id"],
                                                                  "start": int(start), "end": int(end), "title": title})
            except Exception as exc:
                self.state["skipped"][key] = {"title": game.get("title"), "start": round(start + LEAD),
                                              "why": f"TV-Thing refused the timer: {exc}"}
                continue
            timer = got.get("timer") or {}
            self.state["recordings"][key] = {"game": game, "timer": timer.get("id"), "channel": channel["name"],
                                             "channel_id": channel["id"], "start": int(start), "end": int(end),
                                             "title": title, "status": "scheduled"}
            self.state["skipped"].pop(key, None)
            made.append(key)
            print(f"scheduled {title} on {channel['name']}")
        return made

    def adopt(self, timer_id, game):
        """A timer made by hand, for a game: treat it as a training recording."""
        tv = self.tv_recordings()
        t = next((t for t in (tv.get("timers") or []) + (tv.get("history") or []) if t["id"] == timer_id), None)
        if t is None:
            raise SystemExit(f"no TV-Thing timer {timer_id}")
        self.state["recordings"][self.key(game)] = {"game": game, "timer": timer_id, "channel": t["channel_name"],
                                                    "channel_id": t["channel_id"], "start": t["start"], "end": t["end"],
                                                    "title": t.get("title"), "status": "scheduled"}

    def cancelled(self):
        """Games the operator cancelled on the page: our own timers are cancelled in TV-Thing;
        an adopted timer (the operator's own) is only no longer learnt from."""
        try:
            skip = set(json.loads(self.skip_path.read_text()).get("games", []))
        except (OSError, ValueError):
            return
        for key in skip:
            rec = self.state["recordings"].get(key)
            if rec is None or rec["status"] not in ("scheduled", "recording"):
                continue
            if not rec.get("adopted") and rec.get("timer"):
                try:
                    self._post(f"{self.tv}/api/v1/recordings/cancel", {"id": rec["timer"]})
                except Exception as exc:
                    rec["error"] = f"cannot cancel in TV-Thing: {exc}"[:200]
            rec["status"] = "cancelled"

    # process ----------------------------------------------------------------------------
    def follow(self):
        """Statuses from TV-Thing; returns finished recordings not yet processed."""
        tv = self.tv_recordings()
        by_id = {t["id"]: t for t in (tv.get("timers") or []) + (tv.get("history") or [])}
        library = tv.get("storage", {}).get("directory")
        ready = []
        for key, rec in self.state["recordings"].items():
            t = by_id.get(rec.get("timer"))
            if t is None:
                if rec["status"] in ("scheduled", "recording"):
                    rec["status"] = "gone"
                continue
            if rec["status"] in ("processed", "failed", "processing", "cancelled"):
                continue
            rec["status"] = {"scheduled": "scheduled", "recording": "recording", "done": "recorded"}.get(
                t.get("status"), t.get("status"))
            if t.get("status") == "done" and t.get("file"):
                rec.update(file=t["file"], path=os.path.join(library, t["file"]), started_at=t.get("started_at"),
                           bytes=t.get("bytes"))
                ready.append(key)
        return ready

    def process(self, key):
        from admute import fingerprint, replay, seed, speech, sports
        rec = self.state["recordings"][key]
        rec["status"] = "processing"
        self.save()
        path, game = rec["path"], rec["game"]
        steps = rec.setdefault("steps", {})
        try:
            sig = replay.extract(path)
            steps["features"] = True
            if not speech.words_for(path):
                speech.transcribe_tape(path, threads=2)
            steps["words"] = True
            fingerprint.prints_for(path)
            steps["fingerprints"] = True
            self.save()
            length = float(sig["emb"].shape[0])
            tape_start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(rec.get("started_at") or rec["start"]))
            if game.get("league", "mlb") == "mlb":
                feed = seed._feed(game["game_pk"])
                halves, subs, _ = sports.halves_from_feed(feed)
                info = {}
                spans = seed.game_spans(path, game["game_pk"], tape_start, length, halves=halves, info=info)
                ads = [s for s in spans if s[2] == "ad"]
                seed.save_recording(path, spans, f"mlb feed {game['game_pk']}")
                inbox = Path(seed.INBOX)
                inbox.mkdir(parents=True, exist_ok=True)
                got = seed.build(os.path.join(seed.WORK, "inbox.tmp.npz"), only={os.path.basename(path)})
                if got:
                    os.replace(got, inbox / f"recording-{game['game_pk']}-{time.strftime('%H%M%S')}.npz")
                steps["known_ads"] = len(ads)
                steps["lag"] = info.get("lag")
                truth = self.truth(path, game, tape_start, ads, halves, info.get("lag"), length, subs)
                steps["training_labels"] = truth
            else:
                steps["known_ads"] = None
                steps["training_labels"] = None
                rec["note"] = "no play-by-play for this league yet: recorded and transcribed only"
            try:           # known ads heard in this game: their scripts and pictures, if they lack them
                from admute import scripts
                steps["scripts"] = scripts.run([path], quiet=True)["scripted"]
            except Exception as exc:
                steps["scripts_error"] = str(exc)[:200]
            rec["status"] = "processed"
            rec["processed_at"] = round(time.time())
        except Exception as exc:
            rec["status"] = "failed"
            rec["error"] = str(exc)[:300]
        self.save()

    @staticmethod
    def truth(path, game, tape_start, ads, halves, lag, length, subs=()):
        """Training labels: the breaks as ad, play in progress as show, the rest ignored.
        A pitching change stops play mid-inning, often for ads: around each one (the sports
        gate's window) nothing is labelled."""
        from admute import sports
        off = sports._ts(tape_start) - (lag or 0.0)
        holes = sorted((s - off - sports.SUB_BEFORE, s - off + sports.SUB_AFTER) for s in subs)
        spans = []
        for f, l in halves:
            a, b = f - off + LIVE_AFTER, l - off
            for h0, h1 in holes:            # cut each pitching change's window out of the show
                if h1 <= a or h0 >= b:
                    continue
                if h0 - a > 5:
                    spans.append((round(a, 1), round(h0, 1), "show"))
                a = max(a, h1)
            if b - a > 5:
                spans.append((round(a, 1), round(b, 1), "show"))
        spans += [(a, b, "ad") for a, b, _ in ads]
        spans = sorted((max(0.0, a), min(length, b), lab) for a, b, lab in spans if b > a)
        out, cur = [], 0.0
        for a, b, lab in spans:
            if a < cur:
                a = cur
            if b <= a:
                continue
            if a > cur:
                out.append([cur, a, "ignore"])
            out.append([a, b, lab])
            cur = b
        if cur < length:
            out.append([cur, length, "ignore"])
        AUTO_TRUTH.mkdir(parents=True, exist_ok=True)
        name = os.path.basename(path)
        target = AUTO_TRUTH / (os.path.splitext(name)[0] + ".json")
        target.write_text(json.dumps({"file": name, "spans": out, "source": "mlb play-by-play (admute.recordings)",
                                      "feed": {"game_pk": game["game_pk"], "tape_start": tape_start}}, indent=1))
        return str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target)

    def sync(self, process=True):
        self.cancelled()
        try:
            self.plan()
        except Exception as exc:
            self.state["plan_error"] = str(exc)[:300]
        else:
            self.state.pop("plan_error", None)
        ready = self.follow()
        self.save()
        if process:
            for key in ready:
                print(f"processing {self.state['recordings'][key]['title']}")
                self.process(key)
        self.save()


def _ts(iso: str) -> float:
    from admute import sports
    return sports._ts(iso)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="admute.recordings", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("sync", "plan", "status", "adopt"))
    ap.add_argument("--config", default=str(ROOT / "config.master.json"))
    ap.add_argument("--timer")
    ap.add_argument("--game", help='JSON: {"league": "mlb", "game_pk": N, "title": "..."}')
    args = ap.parse_args(argv)
    r = Recordings(args.config)
    if args.cmd == "sync":
        r.sync()
    elif args.cmd == "plan":
        r.sync(process=False)
    elif args.cmd == "adopt":
        r.adopt(args.timer, json.loads(args.game))
        r.save()
    print(json.dumps({k: {f: v.get(f) for f in ("title", "status", "channel", "start", "steps", "error", "note")}
                      for k, v in r.state["recordings"].items()}, indent=1))
    if r.state.get("skipped"):
        print("skipped:", json.dumps(r.state["skipped"], indent=1))


if __name__ == "__main__":
    main()

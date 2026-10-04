"""When the programme audio goes quiet, given the detector's P(ad).

Everything leans towards sound: a wrongly muted programme is worse than an ad
that gets through.

  * Mute (provisionally) when P(ad) >= t_provisional with enough evidence behind
    the moment about to air, never during the grace after a take, never while
    the sports feed says play is live, and only at a seam (a black frame or a hard
    cut) after a retraction.
  * Confirm when P(ad) reaches t_confirm within confirm_window; otherwise unmute
    and record a *retracted* mute.
  * Unmute as soon as P(ad) < t_unmute, at the cap, or when the sports feed says
    play resumed. After the cap or an "it's the show" override, stay audible until
    a stretch of show has passed.
  * Stable within a break (hysteresis from the lookahead, so nothing is delayed): a
    mute starts only if the seconds already seen beyond it stay ad-like, and ends on a
    dip only if everything seen beyond it agrees it is the programme. Early in an
    inning break MLB's feed knows about, only a seam into clearly the programme ends
    it: not the detector changing its mind mid-shot or about a game-looking spot.

Times are input times of the stretch being aired (the analysis edge minus the
lookahead).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class PolicyConfig:
    lookahead: float = 3.0
    t_provisional: float = 0.9
    t_confirm: float = 0.98
    t_unmute: float = 0.6
    confirm_window: float = 10.0
    min_evidence: float = 2.0
    max_mute: float = 300.0           # TV breaks run up to ~4.5 min
    max_mute_gated: float = 240.0     # with a sports feed: MLB breaks are ~2:00-2:55
    grace: float = 20.0
    show_reset: float = 60.0
    seam_after_unmute: float = 30.0   # after an unmute, re-mute only at a seam of these kinds until this much show
    rearm: tuple = ("black", "cut")   # (only "black" before 2026-10-03: TBS cuts into ads without it)
    # At a hard cut (no black), a mute starts or re-arms only if what follows the cut is clearly
    # an ad (mean per-second logit): a camera cut inside the programme is no break.
    cut_z: float = 2.0
    rearm_gap: float = 10.0           # ... and re-arms only this long after the sound came back (a black
                                      # frame at once): the programme's first seconds may look like an ad
    # Sports breaks run to a clock (MLB: 2:00 between half-innings). Once a mute has run
    # this long with a sports feed, any seam brings the sound back unless what follows it
    # is clearly an ad (P(ad) saturates in a long break, so the evidence after the seam decides).
    typical_break: float = 100.0
    z_hold: float = 4.0               # ... unless what follows the seam is this clearly an ad
    # Where a mute may start: "any" piece the detector is sure of, only at a "seam" (a black
    # frame or a hard cut), or only at a "black" seam. A clearly known ad (audio fingerprint)
    # may start one anywhere.
    open_at: str = "any"
    # For this long after MLB's feed says the inning ended, a mute ends only at a seam
    # into clearly the programme (the seconds after it this show-like, per-second logit):
    # a dip mid-shot, or a seam into a spot that merely looks a bit like the game, is the
    # detector second-guessing a sports-looking ad.
    break_hold: float = 130.0          # MLB tape: the game came back 124-167 s after the feed's end of inning
    break_z: float = -2.5

    @classmethod
    def from_sensitivity(cls, sensitivity: float, **kw) -> "PolicyConfig":
        """0 = cautious, 1 = eager. The middle is the default."""
        s = min(1.0, max(0.0, sensitivity))
        base = cls(**kw)
        base.t_provisional = 0.97 - 0.14 * s       # 0.97 .. 0.83
        base.t_confirm = 0.995 - 0.04 * s          # 0.995 .. 0.955
        base.t_unmute = 0.75 - 0.3 * s             # 0.75 .. 0.45
        return base


@dataclass
class Span:
    start: float
    end: float | None = None
    confirmed: bool = False
    end_reason: str | None = None     # show | retracted | capped | gated | override | ended
    start_reason: str = "detector"    # detector | override
    peak: float = 0.0
    seam: str | None = None
    why: list | None = None           # [headline, detail]: the confidence and the evidence, when it began

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Policy:
    cfg: PolicyConfig = field(default_factory=PolicyConfig)
    start: float = 0.0
    gate: object = None               # callable(t) -> 'live' | 'break' | None
    spans: list[Span] = field(default_factory=list)
    current: Span | None = None
    suppressed: bool = False          # after a cap or override: wait for a show stretch
    need_seam: bool = False           # just unmuted: re-mute only at a seam (cfg.rearm)
    show_since: float | None = None
    held: str | None = None           # 'mute' while an operator's mute holds
    break_since: float | None = None  # when the feed's current between-innings window began
    unmuted_at: float | None = None

    @property
    def muted(self) -> bool:
        return self.current is not None

    def _open(self, t, reason="detector", seam=None, p=0.0):
        self.current = Span(start=t, start_reason=reason, seam=seam, peak=p)

    def _close(self, t, reason):
        span, self.current = self.current, None
        span.end, span.end_reason = t, reason
        self.spans.append(span)
        self.unmuted_at = t
        # Once the sound is back, only a new seam can take it away again: the detector
        # re-deciding that the break "never ended" is exactly the mistake to avoid.
        self.need_seam = True
        if reason in ("capped", "override"):
            self.suppressed = True
            self.show_since = None
        return span

    def step(self, segments, edge: float, ahead=()):
        """Apply the detector's view of the stretch about to air. ``ahead``: its view of
        what follows, up to the edge (not airing yet), for hysteresis."""
        c = self.cfg
        segments, ahead = list(segments), list(ahead)
        for i, seg in enumerate(segments):
            t, p = seg.start, seg.p_ad
            rest = [r.p_ad for r in segments[i + 1:] + ahead]
            gate = self.gate(t) if self.gate else None
            if gate != "break":
                self.break_since = None
            elif self.break_since is None:
                self.break_since = t
            if p < 0.5:
                self.show_since = t if self.show_since is None else self.show_since
                if self.suppressed and seg.end - self.show_since >= c.show_reset:
                    self.suppressed = False
                if self.need_seam and seg.end - self.show_since >= c.seam_after_unmute:
                    self.need_seam = False
            else:
                self.show_since = None
            if self.current:
                span = self.current
                span.peak = max(span.peak, p)
                if p >= c.t_confirm:
                    span.confirmed = True
                if self.held == "mute":
                    if (seg.seam and p < c.t_unmute) or t - span.start >= max(c.max_mute, c.max_mute_gated):
                        self.held = None
                        self._close(t, "show" if p < c.t_unmute else "capped")
                    continue
                if gate == "live":
                    self._close(t, "gated")
                elif (gate and seg.seam in ("black", "silence") and t - span.start >= c.typical_break
                      and (seg.post_z is None or seg.post_z < c.z_hold)):     # (not a cut: ads cut every few seconds)
                    self._close(t, "show")
                elif (p < c.t_unmute and all(r < c.t_unmute for r in rest)
                      and (gate != "break" or t - self.break_since >= c.break_hold
                           or (seg.seam and seg.post_z is not None and seg.post_z <= c.break_z))):
                    self._close(t, "show")
                elif not span.confirmed and t - span.start >= c.confirm_window:
                    self._close(t, "retracted")
                elif t - span.start >= (c.max_mute_gated if gate else c.max_mute):
                    self._close(t, "capped")
                continue
            known = getattr(seg, "known", False)
            clear_cut = seg.seam == "cut" and seg.post_z is not None and seg.post_z >= c.cut_z
            where = (c.open_at == "any" or known or seg.seam == "black" or (c.open_at == "seam" and clear_cut))
            rearmed = seg.seam == "black" or (seg.seam == "cut" and "cut" in c.rearm and clear_cut
                                              and t - (self.unmuted_at or -1e9) >= c.rearm_gap)
            if (p >= c.t_provisional and not self.suppressed and gate != "live"
                    and t >= self.start + c.grace and edge - t >= c.min_evidence and where
                    and (rearmed or not self.need_seam)
                    and all(r >= 0.5 for r in rest)):     # not a flash: what follows stays ad-like
                self.need_seam = False
                self._open(t, seam=seg.seam, p=p)
                if p >= c.t_confirm:
                    self.current.confirmed = True

    # operator overrides --------------------------------------------------------
    def override_unmute(self, t: float):
        """'It's the show': sound back now, and no new mute until a show stretch."""
        self.held = None
        if self.current:
            self._close(t, "override")
        else:
            self.suppressed, self.show_since = True, None

    def override_mute(self, t: float):
        """'It's an ad': quiet now, held until a seam into show or the cap."""
        if self.current:
            self.current.confirmed = True
        else:
            self._open(t, reason="override")
            self.current.confirmed = True
        self.held = "mute"
        self.suppressed = False

    def finish(self, t: float):
        if self.current:
            self._close(t, "ended")

    def learnable(self, aired: float, done: set, after: float = 600.0):
        """Closed breaks old enough to teach the ad libraries, each once: confirmed, and
        not cut short as the programme (a retraction, "it's the show", a pause)."""
        for sp in self.spans:
            if sp.start in done or sp.end is None or sp.end > aired - after:
                continue
            done.add(sp.start)
            if sp.confirmed and sp.end_reason not in ("retracted", "override", "paused"):
                yield sp

    def all_spans(self) -> list[Span]:
        return self.spans + ([self.current] if self.current else [])

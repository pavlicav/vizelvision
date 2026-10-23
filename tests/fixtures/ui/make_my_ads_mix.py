"""The Mix tab's fixtures (my_ads_mix*.json) from real ads and plays, trimmed and moved to the
harness's clock, with each ad's chance as ad_mix works it out (browser_ui_mix.cjs checks the page agrees).

    python3 tests/fixtures/ui/make_my_ads_mix.py state/master-candidate [tests/fixtures/ui] [36]
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from roku_stream import ad_mix, my_ads  # noqa: E402

STATE = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent
TRIM = int(sys.argv[3]) if len(sys.argv) > 3 else 36
NOW = 1790907400.0                              # tests/ui_harness.cjs: 2026-10-02T02:16:40Z
settings = my_ads.validate(json.load(open(STATE / 'my-ads.json')), lenient=True)
rows = [json.loads(line) for line in open(STATE / 'my-ads-plays.jsonl') if line.strip()]
real_now = max(r['at'] for r in rows) + 600
shift = NOW - real_now
mix = ad_mix.validate(json.load(open(STATE / 'my-ads-mix.json')))
ads = settings['ads']
if TRIM:
    # Every kind kept: the most played of each, then the newest, up to TRIM in all.
    plays = collections.Counter(r.get('id') for r in rows if r.get('kind', 'ad') == 'ad')
    kind = ad_mix.kinds_of(mix, ads)
    keep, by = [], collections.defaultdict(list)
    for a in sorted(ads, key=lambda a: -plays[a['id']]):
        by[kind[a['id']]].append(a)
    while len(keep) < TRIM and any(by.values()):
        for k in list(by):
            if by[k] and len(keep) < TRIM:
                keep.append(by[k].pop(0))
    ids = {a['id'] for a in keep}
    ads = [a for a in ads if a['id'] in ids]
    settings = {**settings, 'ads': ads}
    rows = [r for r in rows if r.get('kind', 'ad') != 'ad' or r.get('id') in ids]
    mix = ad_mix.validate({**mix, 'ads': {i: k for i, k in mix['ads'].items() if i in ids}})
for r in rows:
    r['at'] += shift
for a in ads:
    if a.get('added'):
        a['added'] = round(a['added'] + shift, 1)
times = collections.defaultdict(list)
for r in rows:
    if r.get('kind', 'ad') == 'ad' and my_ads.played(r):
        times[r['id']].append(r['at'])
kind = ad_mix.kinds_of(mix, ads)
day, sizes = collections.Counter(), collections.Counter(kind.values())
for r in rows:
    if r.get('kind', 'ad') == 'ad' and r['at'] >= NOW - 86400 and my_ads.played(r) and r.get('id') in kind:
        day[kind[r['id']]] += 1
breaks, per_break = ad_mix.pace([r for r in rows if r['at'] >= NOW - 7 * 86400], NOW)
view = {'mix': mix, 'now': NOW, 'order': settings['order'],
        'summary': {'enabled': mix['enabled'], 'aired_day': sum(day.values()),
                    'categories': [{**c, 'ads': sizes.get(c['key'], 0), 'day': day.get(c['key'], 0)} for c in mix['categories']],
                    'unsorted': {'ads': sizes.get('unsorted', 0), 'day': day.get('unsorted', 0), 'weight': mix['tuning']['unsorted']}},
        'ranges': {'tuning': ad_mix.TUNING, 'weight': ad_mix.WEIGHT, 'wear': ad_mix.WEAR, 'boost': ad_mix.BOOST},
        'pace': {'breaks_a_day': round(breaks, 1), 'per_break': per_break},
        'ads': [{'id': a['id'], 'name': a['name'], 'kind': kind[a['id']], 'enabled': a['enabled'], 'duration': a['duration'],
                 'added': a.get('added'), 'pics': a.get('pics', 0), 'plays': [round(t) for t in times.get(a['id'], [])]} for a in ads]}
preview = ad_mix.simulate(settings, rows, mix, NOW, days=3)
# Each ad's chance as ad_mix works it out, from the same rounded plays the page gets: the page must agree.
t = mix['tuning']
wear, boost = ad_mix.own(mix, kind)
chances = {}
for a in view['ads']:
    s = ad_mix.seen(a['plays'], NOW, t['half_life_days'])
    chances[a['id']] = ad_mix.chance(s, a['plays'][-1] if a['plays'] else None, NOW, t, wear=wear[a['id']], boost=boost[a['id']], added=a['added'])
OUT.mkdir(parents=True, exist_ok=True)
json.dump(view, open(OUT / 'my_ads_mix.json', 'w'), separators=(',', ':'), ensure_ascii=False)
json.dump(preview, open(OUT / 'my_ads_mix_preview.json', 'w'), separators=(',', ':'))
json.dump(chances, open(OUT / 'my_ads_mix_chances.json', 'w'), indent=0)
print(len(view['ads']), 'ads', sum(len(a['plays']) for a in view['ads']), 'plays', round((OUT / 'my_ads_mix.json').stat().st_size / 1024), 'KB')

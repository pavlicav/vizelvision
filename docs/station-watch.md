# Station watch

On October 8 a failed entry blocked Up next from Thursday night until Monday morning, and
nobody knew. The station watch (`roku_stream/station_watch.py`, in the web service) checks
every minute for what an operator would notice at a glance:

| Problem | Reported after |
| --- | --- |
| Up next paused (not for a held take or its hand-back) | 15 min |
| An entry blocked | 10 min |
| The test card while the schedule wants a program, or a held take is not on air | 5 min |
| Master (or Up next) not answering | 2 min |

A problem is reported once, after it has lasted that long, and again when it clears. Each
report is a `Station watch: …` warning in the web log. `GET /v1/alerts` lists what is
wrong now, for how long, and whether it was reported.

## Alerts on a phone

Off until a topic is chosen. Put `alerts.json` beside `queue.json`
(`state/master-candidate/alerts.json`). It is read at every check, so no restart is needed:

```json
{"ntfy": "https://ntfy.sh/<a long, private topic name>"}
```

Then subscribe to that topic in the ntfy app. Problems go out at high priority, all-clears at
default. ntfy.sh is a public service: anyone who knows the topic name can read the alerts,
so use an unguessable name. A self-hosted ntfy URL works the same way.

Tests: `tests/test_station_watch.py`.

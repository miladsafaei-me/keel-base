# gh-guard

A PATH shim for the GitHub CLI. It changes exactly one thing: a `gh run watch`
that does not name a refresh interval gets `--interval 20`.

## Why

`gh run watch` polls every 3 seconds by default, and each poll costs about five
REST calls — the run itself, its job list, and one annotations call per job. On
a two-job workflow that is roughly **100 requests per minute**, so a single
nine-minute deploy watch spends ~900 of a personal account's 5,000 requests per
hour.

Measured on 2026-09-04: 18.7 minutes of `gh run watch` consumed 1,863 requests,
confirming the ~5-calls-per-tick figure. Two coding agents each watching their
own deploy of the same repo exhausted the hourly quota twice in two days, and
every later `gh` call in both sessions failed with
`HTTP 403: API rate limit exceeded`.

At `--interval 20` the same watch costs ~15 requests a minute instead of ~100.

## What it does not change

Everything else is passed straight through. An explicit `--interval` or `-i`
always wins, `--help` is never touched, and `wt deploy` (which already passes
`--interval 15`) is unaffected.

`GH_WATCH_INTERVAL` overrides the injected value. `GH_GUARD_DRYRUN=1` prints the
command the shim would have run instead of running it.

## Install

```bash
bash tools/gh-guard/install.sh
```

The shim lands at `~/.local/bin/gh`, which sits ahead of `/usr/bin` on PATH, so
it covers every shell and every agent on the machine rather than one tool's
configuration.

## Diagnosing a rate-limit block

`gh api rate_limit` is useless here: it reports `used: 0` while real requests are
being rejected. Read the header off an actual call instead.

```bash
gh api -i user | grep -i x-ratelimit
```

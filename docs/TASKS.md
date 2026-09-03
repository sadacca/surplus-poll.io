# Surplus Hardware Poller — Task Breakdown

Derived from [REQUIREMENTS.md](./REQUIREMENTS.md). Each task lists the requirement(s) it satisfies (FRx), what it depends on, and the acceptance criteria that mark it done. Tasks are sized so that each one is a single reviewable PR.

Sizes: **S** = under half a day, **M** = about a day, **L** = 2–3 days.

## Decisions assumed (from §10 of the requirements)

These defaults are baked into the tasks below. Change the task set if any of them change.

| Decision | Assumed |
|---|---|
| Poll frequency | Once daily (`0 13 * * *`) — listings run 5-10 days, so 20 min was overkill |
| State storage | Commit-back to repo, `state/seen.json` |
| Notification channels | Discord required, Slack supported |
| Sites for v1 | PublicSurplus + GovDeals |
| Query curation | `queries.yaml` in repo; Issue Form flow is a stretch goal |
| Watchlist mode (FR13) | Stretch goal, after v1 ships |

## Milestones

| Milestone | Goal | Tasks |
|---|---|---|
| **M0 — Skeleton** | Repo runs an empty poll locally and in Actions | T01–T04 |
| **M1 — First alert** | One site, one query, Discord message, state persisted | T05–T07, T09, T10, T12, T13, T15, T17, T18 |
| **M2 — v1 complete** | Both sites, both channels, batching, failure handling, docs | T08, T11, T14, T16, T19, T20, T21, T28 |
| **M3 — Stretch** | Mobile curation, watchlist mode | T22–T27 |

## Phase 0 — Project scaffolding

### T01 — Repo layout and Python packaging  (S)
- **Covers:** §9 Runtime
- **Depends on:** none
- **Deliverable:** `pyproject.toml` (or `requirements.txt` + `requirements-dev.txt`), `poller/` package, `tests/`, `.gitignore`, `.editorconfig`.
- **Acceptance:**
  - Python 3.11+ declared as minimum.
  - Runtime deps limited to `requests`, `beautifulsoup4`, `lxml`, `pyyaml`.
  - Dev deps include `pytest` and `ruff` (lint + format).
  - `python -m poller --help` runs without network access.

### T02 — Core data models  (S)
- **Covers:** FR5, FR12, FR14
- **Depends on:** T01
- **Deliverable:** `poller/models.py` with frozen dataclasses `Query` and `Listing`.
- **Acceptance:**
  - `Query` fields mirror the YAML schema in FR1 (id, label, enabled, sites, keywords, exclude_keywords, category, max_price, state, zip, radius_miles, notify).
  - `Listing` carries site, listing_id, title, url, price/current_bid, bid_count, thumbnail_url, end_time, raw location.
  - `Listing.key` property returns `(site, listing_id)` for dedup (FR12).
  - Unit tests cover construction and the key property.

### T03 — Local dev loop and CI for tests  (S)
- **Covers:** §9 Cost (keep test runs cheap)
- **Depends on:** T01
- **Deliverable:** `.github/workflows/ci.yml` running ruff + pytest on push/PR; `Makefile` or `justfile` with `lint`, `test`, `run` targets.
- **Acceptance:**
  - CI passes on an empty test suite.
  - CI never hits live surplus sites (tests use fixtures only, enforced by a `no-network` pytest marker or socket block).

### T04 — Structured logging setup  (S)
- **Covers:** FR17
- **Depends on:** T01
- **Deliverable:** `poller/log.py` configuring stdlib logging with a compact single-line format, `LOG_LEVEL` env override.
- **Acceptance:**
  - Logs render readably in the Actions log viewer.
  - A run summary helper exists for "queries executed / listings found / new matches / errors" emitted once at end of run.

## Phase 1 — Query configuration (FR1, FR3, FR4)

### T05 — `queries.yaml` loader  (S)
- **Covers:** FR1, FR4
- **Depends on:** T02
- **Deliverable:** `poller/config.py` with `load_queries(path) -> list[Query]`.
- **Acceptance:**
  - Parses the example file from FR1 verbatim.
  - Disabled queries are loaded but flagged; the orchestrator skips them and logs that they were skipped.
  - Optional fields default sensibly (empty exclude list, no price cap, no location filter).

### T06 — Schema validation with clear errors  (M)
- **Covers:** FR3
- **Depends on:** T05, T08 (adapter registry, for the "known sites" check)
- **Deliverable:** validation layer in `poller/config.py`; `python -m poller validate` subcommand.
- **Acceptance:**
  - Rejects: missing `id`/`label`/`sites`/`keywords`, non-boolean `enabled`, unknown site names, duplicate `id`s, negative `max_price`, unknown `notify` channels.
  - Error message names the offending query id and field; exit code non-zero.
  - Validation runs before any network call in the main entry point.
  - Test fixtures: one valid file, one file per failure mode.

### T07 — Ship a starter `queries.yaml`  (S)
- **Covers:** FR1
- **Depends on:** T05
- **Deliverable:** `queries.yaml` at repo root with 2–3 real queries the owner wants, one disabled as an example.
- **Acceptance:** passes `python -m poller validate`.

## Phase 2 — Site adapters (FR5, FR6, FR7)

### T08 — Adapter interface and registry  (S)
- **Covers:** FR5, §9 Extensibility
- **Depends on:** T02
- **Deliverable:** `poller/adapters/base.py` (`Adapter` protocol with `name` and `search(query) -> list[Listing]`), `poller/adapters/__init__.py` with `ADAPTERS: dict[str, Adapter]`.
- **Acceptance:**
  - Adding a site means one new file plus one line in the registry.
  - Registry keys are the strings used in `queries.yaml` `sites`.
  - A `FakeAdapter` in `tests/` implements the protocol for orchestrator tests.

### T09 — Shared HTTP client with per-site rate limiting  (M)
- **Covers:** FR6, FR7, FR18
- **Depends on:** T08
- **Deliverable:** `poller/http.py` wrapping `requests.Session`.
- **Acceptance:**
  - Configurable minimum delay per site (default 2.5s), enforced across all requests for that site within a run.
  - Sensible User-Agent, timeouts (connect 10s, read 30s), at most one retry on 5xx/timeout.
  - Raises a typed `SiteError` (timeout / non-200 / parse) so the orchestrator can log and continue.
  - Unit tests use a mocked transport; verify delay enforcement with a fake clock.

### T10 — PublicSurplus adapter  (L)
- **Covers:** FR5, FR6
- **Depends on:** T08, T09
- **Deliverable:** `poller/adapters/publicsurplus.py` + HTML fixtures under `tests/fixtures/publicsurplus/`.
- **Acceptance:**
  - Builds a search URL from keywords, category, state, zip/radius, max price (whichever the site supports; document unsupported filters and apply them client-side).
  - Parses title, listing id, URL, current bid, bid count, thumbnail, end time from the results page.
  - Applies `exclude_keywords` and `max_price` client-side after parsing.
  - Follows pagination up to a configurable page cap (default 3).
  - Tests parse saved fixture pages; at least one fixture for "no results".
  - A manual `python -m poller search publicsurplus "nvidia"` smoke command exists for checking against the live site.

### T11 — GovDeals adapter  (L)
- **Covers:** FR5, FR6
- **Depends on:** T08, T09
- **Deliverable:** `poller/adapters/govdeals.py` + fixtures under `tests/fixtures/govdeals/`.
- **Acceptance:** same criteria as T10. Confirm during the spike that GovDeals search results are server-rendered; if the current site requires JS, record that in the task and fall back to any JSON endpoint the page uses.

## Phase 3 — State and deduplication (FR11, FR12)

### T12 — Seen-listing store  (M)
- **Covers:** FR11, FR12
- **Depends on:** T02
- **Deliverable:** `poller/state.py` reading/writing `state/seen.json`.
- **Acceptance:**
  - Schema: version field, per-key record with first_seen, last_seen, last_price, last_bid_count, matched query ids.
  - `is_new(listing)`, `mark_seen(listing)`, `save()` API; atomic write (temp file + rename).
  - Missing or empty file is treated as "nothing seen" on first run, with a log line.
  - Pruning: entries not seen in N days (default 60) are dropped to keep the file small.
  - Round-trip and pruning tests.

### T13 — Commit-back of state from the workflow  (S)
- **Covers:** FR11
- **Depends on:** T12, T17
- **Deliverable:** step in `poll.yml` that commits `state/seen.json` if changed.
- **Acceptance:**
  - Uses `permissions: contents: write` and the built-in `GITHUB_TOKEN`.
  - Commit message `chore(state): update seen listings [skip ci]` so it does not trigger the CI workflow.
  - No commit when the file is unchanged.
  - Concurrent runs are prevented with a `concurrency` group so two runs never race on the commit.

## Phase 4 — Notifications (FR10, FR14, FR15, FR16)

### T14 — Notifier interface and registry  (S)
- **Covers:** FR15
- **Depends on:** T02
- **Deliverable:** `poller/notify/base.py` (`Notifier.send(matches: list[Match])`), `poller/notify/__init__.py` registry keyed by channel name.
- **Acceptance:**
  - `Match` pairs a `Listing` with the `Query` that matched it.
  - Registry only instantiates a notifier when its webhook URL env var is set; a query routing to an unset channel logs a warning rather than failing.

### T15 — Discord webhook notifier with batching  (M)
- **Covers:** FR10, FR14, FR16
- **Depends on:** T14
- **Deliverable:** `poller/notify/discord.py`.
- **Acceptance:**
  - Reads `DISCORD_WEBHOOK_URL` from the environment only.
  - One message per run per channel; matches rendered as embeds (title linked to URL, price/bid, site, query label, thumbnail).
  - Respects Discord's 10-embeds-per-message limit by splitting into multiple posts with a short delay.
  - Handles 429 by honoring `Retry-After` once.
  - Tests assert payload shape against a mocked endpoint; no real webhook in tests.

### T16 — Slack webhook notifier with batching  (M)
- **Covers:** FR10, FR14, FR16
- **Depends on:** T14
- **Deliverable:** `poller/notify/slack.py` using Block Kit.
- **Acceptance:** same as T15, using `SLACK_WEBHOOK_URL` and Slack's block limits.

## Phase 5 — Orchestrator and failure handling (FR17, FR18, FR19)

### T17 — `poller.py` orchestrator  (M)
- **Covers:** §11 deliverable 3, FR17, FR18
- **Depends on:** T04, T06, T08, T12, T14
- **Deliverable:** `poller/__main__.py` `run` command: load + validate config → for each enabled query × site, run adapter → dedup against state → group matches by channel → notify → save state.
- **Acceptance:**
  - A failing adapter call is caught, logged with site/query id/error type, and the run continues (FR18).
  - Notification failure does not prevent state save for listings that were already notified successfully; listings whose notification failed are **not** marked seen, so they are retried next run.
  - End-of-run summary line (FR17).
  - `--dry-run` flag: search and dedup but print matches instead of notifying and do not write state.
  - Integration test using `FakeAdapter` and a mocked notifier covers: new listing notified, repeat listing suppressed, adapter error does not abort.

### T18 — Exit codes and run health signal  (S)
- **Covers:** FR17, FR18
- **Depends on:** T17
- **Deliverable:** exit code policy documented in code and README.
- **Acceptance:**
  - Exit 0 when the run completed even if some sites failed; exit 2 on config validation failure; exit 1 on unexpected crash.
  - Per-site success/failure is written to `state/health.json` (or a section of `seen.json`) for T19.

### T19 — Consecutive-failure alert  (M)
- **Covers:** FR19
- **Depends on:** T18, T15
- **Deliverable:** health tracker in `poller/health.py`.
- **Acceptance:**
  - Counts consecutive runs where a site returned zero successful searches.
  - On the third consecutive failure, sends one "adapter may be broken" notification to the default channel and sets a flag so it is not re-sent.
  - Flag clears and a "recovered" message is sent when the site succeeds again.
  - Tests cover the 2-fail/3-fail/recover sequence.

## Phase 6 — GitHub Actions scheduling (FR8, FR9, FR10)

### T20 — `.github/workflows/poll.yml`  (M)
- **Covers:** FR8, FR9, FR10, FR11
- **Depends on:** T17
- **Deliverable:** scheduled workflow.
- **Acceptance:**
  - Triggers: `schedule` (`0 13 * * *`, once daily) and `workflow_dispatch` with an optional `query_id` input to run a single query and a `dry_run` boolean.
  - Pip dependencies cached with `actions/cache` keyed on the lockfile.
  - Webhook URLs passed only via `secrets.*` into env.
  - Job `timeout-minutes: 5`; a run against the starter `queries.yaml` completes in under 2 minutes (record the measured time in the PR).
  - State commit-back step from T13 wired in.

### T21 — Runtime budget guardrail  (S)
- **Covers:** FR9
- **Depends on:** T20
- **Deliverable:** per-run timing in the summary log; a warning when total run time exceeds 90s.
- **Acceptance:** README documents how many queries × sites fit the budget at the default rate limit and page cap, and how to tune `radius`/page cap if it is exceeded.

## Phase 7 — Mobile curation via Issue Forms (FR2, stretch)

### T22 — Issue Form template  (S)
- **Covers:** FR2
- **Depends on:** T06 (field names must match the schema)
- **Deliverable:** `.github/ISSUE_TEMPLATE/new-query.yml`.
- **Acceptance:**
  - Fields: label (required), keywords (required, comma-separated), exclude keywords, sites (checkboxes), max price, state, zip, radius, notify channels (checkboxes).
  - Auto-applies the `new-query` label.

### T23 — Issue-to-PR workflow  (L)
- **Covers:** FR2
- **Depends on:** T22, T06
- **Deliverable:** `.github/workflows/add-query.yml` + `scripts/issue_to_query.py`.
- **Acceptance:**
  - Triggers on `issues: opened` with label `new-query`.
  - Parses the issue form body, generates a slug `id` from the label, appends to `queries.yaml`, runs validation.
  - Opens a PR with the diff, links the issue, and comments on the issue with the PR URL; closes the issue when the PR merges (`closes #N` in the PR body).
  - On validation failure, comments on the issue with the error instead of opening a PR.
  - Uses `permissions: contents: write, pull-requests: write, issues: write`.

### T24 — Pause/resume via issue comment (optional)  (M)
- **Covers:** FR4 from mobile
- **Depends on:** T23
- **Deliverable:** slash-command style comments (`/pause gpu-search`, `/resume gpu-search`) handled by a workflow that flips `enabled` and opens a PR.
- **Acceptance:** only the repo owner can trigger it.

## Phase 8 — Watchlist mode (FR13, stretch)

### T25 — Watchlist config and state  (M)
- **Covers:** FR13
- **Depends on:** T12
- **Deliverable:** `watchlist:` section in `queries.yaml` (explicit `(site, listing_id)` pins) plus a per-query `auto_watch: true` flag that pins every new match; state stores last price/bid count per pinned listing.

### T26 — Listing-detail fetch in adapters  (M)
- **Covers:** FR13
- **Depends on:** T10, T11, T25
- **Deliverable:** `Adapter.fetch(site, listing_id) -> Listing` implemented for both sites, with fixtures.

### T27 — Change detection and alerts  (M)
- **Covers:** FR13, FR14
- **Depends on:** T25, T26, T15
- **Deliverable:** watchlist pass in the orchestrator that re-fetches pinned listings each run, diffs price/bid count, and sends a distinct "bid changed" batched message; drops listings once their end time has passed.

## Phase 9 — Documentation and release

### T28 — README  (M)
- **Covers:** §11 deliverable 7
- **Depends on:** T20 (and T23 if shipped)
- **Deliverable:** `README.md`.
- **Acceptance:** covers creating the Discord/Slack webhook and adding secrets, first manual run via `workflow_dispatch`, adding/pausing a query by editing `queries.yaml`, adding a query from the mobile app (if T23 shipped), adding a new site adapter, reading the run log, and what the "adapter may be broken" alert means.

## Suggested implementation order

1. T01, T02, T03, T04 — scaffolding (parallelisable after T01)
2. T05, T08, T12, T14 — interfaces and loaders (parallelisable)
3. T09 → T10 — first adapter (PublicSurplus)
4. T06, T07 — validation and starter config
5. T15 — Discord
6. T17, T18 — orchestrator; first end-to-end dry run locally
7. T20, T13 — workflow and state commit-back; first live run
8. T11, T16, T19, T21 — second site, Slack, health alert, budget
9. T28 — README, tag v1.0
10. T22–T27 — stretch

## Risks to spike early

- **GovDeals markup.** Verify the search page is server-rendered before committing to T11; this is the biggest unknown and decides whether GovDeals stays in v1.
- **Location filtering.** Neither site may support zip + radius natively; the tasks assume state filtering server-side and radius client-side via a small zip centroid table, which is extra scope if required.
- **Commit-back churn.** One commit per 20-minute run is ~72 commits/day. Acceptable for a personal repo but noted; the `[skip ci]` marker and pruning in T12 keep it manageable.

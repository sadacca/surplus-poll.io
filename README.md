# Surplus Hardware Poller

A scheduled poller that searches [PublicSurplus](https://www.publicsurplus.com)
and [GovDeals](https://www.govdeals.com) for listings matching a set of
curated hardware searches, and posts new matches to Discord and/or Slack.
Runs on GitHub Actions — no server to maintain.

Full requirements: [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md). Task
breakdown this project was built from: [`docs/TASKS.md`](docs/TASKS.md).

> **Selector caveat.** The two site adapters (`poller/adapters/publicsurplus.py`,
> `poller/adapters/govdeals.py`) were written without live access to either
> site — see the module docstrings for why and what to verify. Before the
> first real run, follow **Verifying the adapters** below.

## How it works

1. `queries.yaml` at the repo root defines your searches.
2. Once a day (configurable — edit the `cron` line in
   `.github/workflows/poll.yml`), a GitHub Actions workflow runs
   `python -m poller run`, which:
   - validates `queries.yaml`,
   - runs each enabled query against its configured sites,
   - drops listings already seen (tracked in `state/seen.json`),
   - batches new matches per notification channel and sends them,
   - commits the updated `state/seen.json` back to the repo.
3. Three consecutive failed runs for a site send a one-time "adapter may be
   broken" alert (the site likely changed its markup); a later success sends
   a "recovered" alert.

## Setup

### 1. Add webhook secrets

Create an incoming webhook for whichever channel(s) you want:
- **Discord:** Server Settings → Integrations → Webhooks → New Webhook → Copy URL.
- **Slack:** create an [Incoming Webhook app](https://api.slack.com/messaging/webhooks) for your workspace and copy the webhook URL.

Add them as repository secrets (Settings → Secrets and variables → Actions):

| Secret | Used for |
|---|---|
| `DISCORD_WEBHOOK_URL` | any query with `notify: [discord, ...]`, and adapter-health alerts |
| `SLACK_WEBHOOK_URL` | any query with `notify: [..., slack]` |

You only need the secret(s) for channels you actually use in `queries.yaml`.
A query routed to a channel with no secret set logs a warning and skips that
channel rather than failing the run.

### 2. Verifying the adapters

This project's adapters were written against a best-effort guess at each
site's search-results markup — see the caveat at the top of this file. Before
relying on them:

```bash
pip install -r requirements.txt
python -m poller search publicsurplus "nvidia"
python -m poller search govdeals "nvidia"
```

Each command prints `listing_id  price  title  url` for whatever it parsed.
If it prints nothing (or wrong-looking data) but the site clearly has
results for that keyword in a browser, the selectors need updating:

1. Save the HTML of a real search-results page for that site.
2. Compare it to the `_ROW_SELECTOR` / `_TITLE_SELECTOR` / etc. constants
   near the top of `poller/adapters/<site>.py`.
3. Update the selectors and `build_search_url()` to match, and update the
   fixture at `tests/fixtures/<site>/search_results.html` (and re-run
   `pytest`) so the tests keep covering the real structure.

For GovDeals specifically, also confirm the search results are still
server-rendered HTML (no JavaScript required) — if not, this
`requests` + `BeautifulSoup` approach won't work for it and it should be
dropped from `sites:` in your queries until a different approach is added.

### 3. First run

Push this repo to GitHub with the secrets set, then either wait for the
next scheduled run or trigger one manually: **Actions → Poll → Run
workflow**. Leave `dry_run` unchecked to actually notify.

To test a single query without waiting for the schedule or touching
`state/seen.json`, use the same manual-run form and set `query_id` to the
query's `id`, with `dry_run` checked — it prints what it would notify
instead of sending it.

Locally, the equivalent is:

```bash
python -m poller run --query-id gpu-search --dry-run
```

## Adding a query from your phone

File a new issue using the **New search query** template (auto-tagged
`new-query`). A workflow parses it, appends the entry to `queries.yaml`,
opens a PR, comments on the issue with the PR link, and closes the issue.
Merge the PR to activate the search — no laptop or YAML editing required.
If the form doesn't parse (e.g. a required field left blank), the workflow
comments the specific problem on the issue instead of opening a PR, and
`queries.yaml` is left untouched.

## Adding or editing a query by hand

Edit `queries.yaml` at the repo root. Each query:

```yaml
- id: gpu-search              # unique, used as the state/health key
  label: "Server GPUs"        # shown in notifications
  enabled: true                # set false to pause without deleting
  sites: [publicsurplus, govdeals]
  keywords: ["nvidia", "gpu", "tesla"]
  exclude_keywords: ["case", "sleeve"]   # optional
  category: "Computer Equipment"          # optional
  max_price: 500                          # optional
  state: "CA"                             # optional
  zip: "94103"                            # optional, not yet used for filtering
  radius_miles: 200                       # optional, not yet used for filtering
  notify: [discord]             # discord, slack, or both
```

Run `python -m poller validate` (or `make validate`) after editing — it
checks required fields, that `sites`/`notify` values are ones this project
actually supports, and that `enabled` is a real boolean, and fails with a
specific error per problem rather than silently skipping a broken query.

`zip` and `radius_miles` are parsed and validated but not yet applied as a
filter — neither adapter currently does distance filtering. `state` is
passed through to the site's own search if the adapter's URL builder
includes it.

## Adding a new site

1. Create `poller/adapters/<site>.py` implementing the `Adapter` protocol
   (`name: str`, `search(query: Query) -> list[Listing]`) — see
   `poller/adapters/publicsurplus.py` for the shape (URL building, a
   `RateLimitedClient` for fetches, a pure `parse_results(html)` function
   you can unit-test against a saved fixture, client-side filtering for
   whatever the site's search doesn't support natively).
2. Register it in `poller/adapters/__init__.py`'s `register_builtin_adapters`.
3. Add the site name to `KNOWN_SITES` in `poller/__main__.py`.
4. Add fixtures under `tests/fixtures/<site>/` and a test module mirroring
   `tests/test_publicsurplus_adapter.py`.

## Reading the run log

Each run logs, per query/site: a warning line on any failure (timeout,
non-200, parse error) with the site and query id, plus a final summary
line: `queries=N listings_found=N new_matches=N errors=N duration=Xs`. A
run is never aborted by one bad site or query — failures are logged and
the rest of the run continues (exit code stays 0). Exit code 2 means
`queries.yaml` failed validation before anything ran; exit code 1 means an
unexpected crash.

If a run's duration exceeds 90 seconds, the log calls it out — the fix
is usually fewer queries per run, a smaller page cap, or a shorter
per-site rate-limit delay (see `poller/http.py`'s `RateLimitedClient`
and `poller/adapters/*.py`'s `page_cap`).

## What the "adapter may be broken" alert means

If a site fails three runs in a row (timeouts, non-200s, or the page
parsing to zero rows every time), you get a one-time alert on the
`discord` channel saying so — it almost always means the site changed its
HTML and the adapter's selectors need updating (see **Verifying the
adapters** above). You'll get a second, "recovered" alert once a run
against that site succeeds again.

## Development

```bash
pip install -e ".[dev]"
make lint      # ruff check .
make test      # pytest -q
make validate  # python -m poller validate
```

CI runs lint and tests on every push and PR. Tests never touch the live
sites — the adapter tests run entirely against saved HTML fixtures and a
mocked HTTP layer, and the notifier tests mock the webhook endpoint.

## Not in this repo yet

Watchlist mode — price/bid-change alerts on pinned listings, separate from
the new-listing alert (`docs/REQUIREMENTS.md` FR13) — is not implemented.
It's scoped as the rest of milestone M3 in `docs/TASKS.md`.

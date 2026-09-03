# Surplus Hardware Poller — Requirements

## 1. Purpose
An automated, scheduled poller that searches surplus/auction sites (PublicSurplus, GovDeals, extensible to others) for listings matching a user-curated set of hardware queries, and sends notifications on new or changed matches. Runs on GitHub Actions — no server to maintain.

## 2. Scope

**In scope (v1):**
- PublicSurplus.com and GovDeals.com search
- Keyword + category + location/price filtering per query
- New-listing detection and (optionally) price/bid-change detection on watchlisted lots
- Discord and/or Slack webhook notifications
- Config-driven query curation (no code changes to add/remove a search)

**Out of scope (v1):**
- Bidding or checkout automation
- CAPTCHA solving or anti-bot bypass
- Sites that require a headless browser / heavy JS rendering
- Multi-user accounts (single-owner repo/config)

## 3. Query Curation

**FR1 — Config file as source of truth.** All searches live in one version-controlled file, `queries.yaml`, at the repo root. Example:

```yaml
queries:
  - id: gpu-search
    label: "Server GPUs"
    enabled: true
    sites: [publicsurplus, govdeals]
    keywords: ["nvidia", "gpu", "tesla"]
    exclude_keywords: ["case", "sleeve"]
    category: "Computer Equipment"
    max_price: 500
    state: "CA"
    zip: "94103"
    radius_miles: 200
    notify: [discord]

  - id: rack-switches
    label: "10G Switches"
    enabled: false
    sites: [publicsurplus]
    keywords: ["switch", "10gbe", "sfp+"]
    max_price: 150
    notify: [discord, slack]
```

**FR2 — Curation without editing YAML by hand (optional, recommended for mobile use).** A GitHub Issue Form template (`.github/ISSUE_TEMPLATE/new-query.yml`) lets you file an issue from the GitHub mobile app with structured fields (label, keywords, price cap, sites). A separate workflow, triggered on issue creation with a specific label (e.g. `new-query`), parses the issue body and opens a PR appending the entry to `queries.yaml`, then closes the issue. This avoids needing a laptop to add a search.

**FR3 — Validation.** At the start of every run, `queries.yaml` is schema-validated (required fields present, `sites` values are known adapters, `enabled` is boolean). An invalid file fails the run with a clear error rather than silently skipping queries.

**FR4 — Enable/disable without deleting.** Each query has an `enabled` flag so searches can be paused without losing the definition.

## 4. Site Adapters

**FR5 — Common interface.** Each supported site is a self-contained adapter implementing:
```
search(query: Query) -> list[Listing]
```
so new sites can be added without touching the scheduler, dedup, or notification logic.

**FR6 — No headless browser for v1 sites.** PublicSurplus and GovDeals both expose server-side, query-param-driven search results, so `requests` + `BeautifulSoup`/`lxml` is sufficient — no Selenium/Playwright dependency.

**FR7 — Per-site rate limiting.** Minimum delay between requests per site (default 2–3s), a single well-formed run should complete in well under GitHub Actions' job limits.

## 5. Scheduling & Execution (GitHub Actions)

**FR8 — Triggers:** `schedule` (cron, default every 15–30 min) and `workflow_dispatch` (manual run button, useful for testing a new query immediately).

**FR9 — Job budget:** target under 2 minutes per run (all queries × all sites) to stay comfortably within free-tier minutes.

**FR10 — Secrets:** webhook URLs (`DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`) stored as repository secrets, never committed in plaintext.

## 6. State & Deduplication

**FR11 — Persistent seen-listing store.** Because each Actions run starts from a clean container, previously-seen listing IDs must be persisted across runs. Options (pick one for v1):
  - Commit a `state/seen.json` file back to the repo at the end of each run (simplest, no external dependency, small repos handle this fine).
  - Use GitHub Actions cache (faster, but not guaranteed durable long-term).
  - External key-value store (Gist, S3, etc.) — only needed if commit-back becomes a bottleneck.

  **Default for v1: commit-back to repo**, via a bot commit at the end of the workflow, gated on `permissions: contents: write`.

**FR12 — Dedup key.** Listing uniqueness is `(site, listing_id)`. A listing already in the seen-store is never re-notified unless price/bid-change tracking (FR13) is enabled for it.

**FR13 — Optional watchlist mode.** A listing can be pinned (manually or automatically once matched) for more frequent re-checks that alert specifically on price or bid-count change, separate from the "new listing" alert.

## 7. Notifications

**FR14 — Payload contents:** listing title, price/current bid, site, matched query label, listing URL, and thumbnail image if available.

**FR15 — Per-query routing.** Each query's `notify` field controls which channel(s) receive its matches, so noisy searches can go to a different channel than high-priority ones.

**FR16 — Batching.** Multiple matches from a single run are sent as one batched message per channel (not one message per listing) to avoid rate-limiting/spam on the webhook.

## 8. Logging & Failure Handling

**FR17** — Each run logs: queries executed, listings found per query, new matches, and any site errors (timeout, non-200, parse failure).

**FR18** — A single site/query failure must not abort the whole run; failures are logged and other queries still execute.

**FR19** — Three consecutive failed runs for the same site trigger a one-time "adapter may be broken" notification (site likely changed its HTML/markup).

## 9. Non-Functional Requirements

- **Runtime:** Python 3.11+, dependencies limited to `requests`, `beautifulsoup4` (or `lxml`), `pyyaml`, and a notification helper (`apprise` optional, or raw webhook POSTs).
- **Cost:** stays within GitHub Actions free tier for a personal/private repo at the default polling interval.
- **Portability:** no site-specific credentials or login required (both v1 sites support anonymous search).
- **Extensibility:** adding a new site = one new adapter file + registering it in a small adapter map.

## 10. Open Decisions (to confirm before implementation)

| Decision | Default assumption |
|---|---|
| Poll frequency | Every 20 minutes |
| State storage | Commit-back to repo (`state/seen.json`) |
| Notification channel(s) | Discord webhook |
| Sites for v1 | PublicSurplus + GovDeals |
| Query curation method | `queries.yaml` in repo, with optional Issue Form workflow |

## 11. Deliverables

1. `queries.yaml` — query config + schema
2. `adapters/publicsurplus.py`, `adapters/govdeals.py` — search adapters
3. `poller.py` — orchestrator: load config → run adapters → dedup → notify → persist state
4. `.github/workflows/poll.yml` — scheduled workflow
5. `.github/ISSUE_TEMPLATE/new-query.yml` + `.github/workflows/add-query.yml` — optional mobile curation flow
6. `requirements.txt` — Python dependencies
7. `README.md` — setup instructions (secrets, first run, adding a query)

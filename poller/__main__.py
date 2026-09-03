"""CLI entry point and orchestrator: load config -> run adapters -> dedup ->
notify -> persist state (FR17, FR18; see docs/TASKS.md T17/T18)."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from collections import defaultdict

from poller.adapters import ADAPTERS, register_builtin_adapters
from poller.adapters.base import SiteError
from poller.config import ConfigError, load_and_validate
from poller.health import ALERT_THRESHOLD, HealthTracker
from poller.http import RateLimitedClient
from poller.log import RunSummary, configure_logging
from poller.models import Match
from poller.notify import build_notifiers
from poller.notify.base import NotifyError
from poller.state import SeenStore

logger = logging.getLogger("poller")

DEFAULT_CONFIG_PATH = "queries.yaml"
DEFAULT_STATE_PATH = "state/seen.json"
DEFAULT_HEALTH_PATH = "state/health.json"
DEFAULT_ALERT_CHANNEL = "discord"
KNOWN_SITES = ("publicsurplus", "govdeals")

EXIT_OK = 0
EXIT_CRASH = 1
EXIT_CONFIG_ERROR = 2


def bootstrap() -> dict[str, RateLimitedClient]:
    """Populate the adapter and notifier registries. Must run before any
    config validation or orchestration, since validation checks query
    `sites`/`notify` values against these registries."""
    import poller.notify.discord  # noqa: F401 - registers "discord"
    import poller.notify.slack  # noqa: F401 - registers "slack"

    clients = {site: RateLimitedClient() for site in KNOWN_SITES}
    register_builtin_adapters(clients)
    return clients


def cmd_validate(args: argparse.Namespace) -> int:
    bootstrap()
    try:
        queries = load_and_validate(args.config)
    except ConfigError as e:
        logger.error(str(e))
        return EXIT_CONFIG_ERROR
    plural = "y" if len(queries) == 1 else "ies"
    logger.info("%s is valid: %d quer%s", args.config, len(queries), plural)
    return EXIT_OK


def cmd_search(args: argparse.Namespace) -> int:
    bootstrap()
    from poller.models import Query

    adapter = ADAPTERS.get(args.site)
    if adapter is None:
        logger.error("unknown site %r (known: %s)", args.site, ", ".join(ADAPTERS))
        return EXIT_CONFIG_ERROR

    query = Query(
        id="smoke-test",
        label="smoke test",
        enabled=True,
        sites=(args.site,),
        keywords=tuple(args.keywords),
    )
    try:
        listings = adapter.search(query)
    except SiteError as e:
        logger.error("search failed: %s", e)
        return EXIT_CRASH

    logger.info("%d listing(s) found", len(listings))
    for listing in listings:
        print(f"{listing.listing_id}\t{listing.price}\t{listing.title}\t{listing.url}")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    bootstrap()

    try:
        queries = load_and_validate(args.config)
    except ConfigError as e:
        logger.error(str(e))
        return EXIT_CONFIG_ERROR

    if args.query_id:
        matching = [q for q in queries if q.id == args.query_id]
        if not matching:
            logger.error("no query with id %r in %s", args.query_id, args.config)
            return EXIT_CONFIG_ERROR
        active_queries = [dataclasses.replace(matching[0], enabled=True)]
        logger.info("running single query %r (forced enabled)", args.query_id)
    else:
        active_queries = [q for q in queries if q.enabled]
        skipped = len(queries) - len(active_queries)
        if skipped:
            logger.info("skipping %d disabled quer%s", skipped, "y" if skipped == 1 else "ies")

    seen_store = SeenStore(args.state)
    health = HealthTracker(args.health)
    summary = RunSummary()

    matches_by_channel: dict[str, list[Match]] = defaultdict(list)
    new_matches: list[Match] = []
    alert_texts: list[str] = []

    for query in active_queries:
        for site_name in query.sites:
            adapter = ADAPTERS.get(site_name)
            if adapter is None:
                summary.add_error(site_name, query.id, "no adapter registered for this site")
                continue

            try:
                listings = adapter.search(query)
            except SiteError as e:
                logger.warning("%s/%s: %s", site_name, query.id, e)
                summary.add_error(site_name, query.id, str(e))
                if health.record_failure(site_name):
                    alert_texts.append(
                        f":warning: `{site_name}` adapter may be broken: "
                        f"{ALERT_THRESHOLD} consecutive failed runs. "
                        "The site likely changed its markup."
                    )
                continue

            if health.record_success(site_name):
                alert_texts.append(f":white_check_mark: `{site_name}` adapter has recovered.")

            summary.listings_found += len(listings)
            for listing in listings:
                if not seen_store.is_new(listing):
                    continue
                match = Match(listing=listing, query=query)
                new_matches.append(match)
                summary.new_matches += 1
                for channel in query.notify:
                    matches_by_channel[channel].append(match)

        summary.queries_executed += 1

    channels_needed = set(matches_by_channel) | ({DEFAULT_ALERT_CHANNEL} if alert_texts else set())
    notifiers = build_notifiers(channels_needed) if not args.dry_run else {}

    failed_channels: set[str] = set()
    if args.dry_run:
        logger.info("dry run: %d new match(es), not notifying or writing state", len(new_matches))
        for match in new_matches:
            logger.info(
                "  [%s/%s] %s - %s (%s)",
                match.listing.site,
                match.query.id,
                match.listing.title,
                match.listing.price,
                match.listing.url,
            )
    else:
        for channel, matches in matches_by_channel.items():
            notifier = notifiers.get(channel)
            if notifier is None:
                failed_channels.add(channel)
                continue
            try:
                notifier.send(matches)
            except NotifyError as e:
                logger.error("%s: failed to send %d match(es): %s", channel, len(matches), e)
                failed_channels.add(channel)

        alert_notifier = notifiers.get(DEFAULT_ALERT_CHANNEL)
        for text in alert_texts:
            if alert_notifier is None or not hasattr(alert_notifier, "send_text"):
                logger.warning(
                    "no %s notifier configured; dropping alert: %s", DEFAULT_ALERT_CHANNEL, text
                )
                continue
            try:
                alert_notifier.send_text(text)
            except NotifyError as e:
                logger.error("failed to send health alert: %s", e)

        for match in new_matches:
            if all(c not in failed_channels for c in match.query.notify):
                seen_store.mark_seen(match.listing, match.query.id)

        seen_store.save()

    health.save()
    summary.log(logger)
    return EXIT_OK


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poller", description="Surplus hardware poller")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run all enabled queries and notify on new matches")
    run_p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    run_p.add_argument("--state", default=DEFAULT_STATE_PATH)
    run_p.add_argument("--health", default=DEFAULT_HEALTH_PATH)
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--query-id", default=None, help="run only this query, even if disabled")
    run_p.set_defaults(func=cmd_run)

    validate_p = sub.add_parser("validate", help="validate queries.yaml and exit")
    validate_p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    validate_p.set_defaults(func=cmd_validate)

    search_p = sub.add_parser(
        "search", help="run one adhoc search against a live site (manual testing)"
    )
    search_p.add_argument("site", choices=list(KNOWN_SITES))
    search_p.add_argument("keywords", nargs="+")
    search_p.set_defaults(func=cmd_search)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception:  # noqa: BLE001 - top-level guard for the FR18/exit-code contract
        logger.exception("unexpected error")
        return EXIT_CRASH


if __name__ == "__main__":
    sys.exit(main())

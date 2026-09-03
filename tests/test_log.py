import logging

from poller.log import RunSummary


def test_run_summary_logs_counts(caplog):
    summary = RunSummary(queries_executed=2, listings_found=5, new_matches=1)
    summary.add_error("publicsurplus", "gpu-search", "timeout")

    logger = logging.getLogger("test.summary")
    with caplog.at_level(logging.INFO, logger="test.summary"):
        summary.log(logger)

    assert "queries=2" in caplog.text
    assert "listings_found=5" in caplog.text
    assert "new_matches=1" in caplog.text
    assert "errors=1" in caplog.text
    assert "publicsurplus/gpu-search: timeout" in caplog.text

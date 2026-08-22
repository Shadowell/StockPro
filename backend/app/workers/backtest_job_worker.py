"""
Backtest job worker process.

The FastAPI process only launches this module and waits for it. The heavy
Backtrader run stays in this child process so CPU-bound strategy code cannot
starve the API event loop.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Sequence

from dotenv import load_dotenv

load_dotenv()

from app.api.v2.endpoints.backtest import _run_backtest_job_worker  # noqa: E402

logger = logging.getLogger(__name__)


def _lower_worker_priority() -> None:
    try:
        os.nice(5)
    except OSError:
        logger.debug("unable to lower backtest worker priority", exc_info=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 2:
        print(
            "usage: python -m app.workers.backtest_job_worker <job_id> <payload_json>",
            file=sys.stderr,
        )
        return 2

    job_id, payload_json = args
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        print(f"invalid backtest payload json: {exc}", file=sys.stderr)
        return 2

    logger.info("starting backtest worker process for job %s", job_id)
    _lower_worker_priority()
    _run_backtest_job_worker(job_id, payload)
    logger.info("finished backtest worker process for job %s", job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

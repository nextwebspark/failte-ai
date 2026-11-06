"""Review finished calls that have no call review yet.

    python -m api.scripts.backfill_call_reviews --org 4 --limit 50
    python -m api.scripts.backfill_call_reviews --org 4 --run 98 --run 99 --redo

Calls are reviewed one at a time, newest first, exactly as the after-call
job does it (silent calls get the "Hung up without speaking." review with
no model call). Each review is a small model call, so ``--limit`` is
required. Prints one line per call and the stored review with ``--show``.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from api.db import db_client
from api.services.call_review.review import stored_review
from api.services.call_review.service import ReviewOutcome, review_call


async def _main(args: argparse.Namespace) -> None:
    run_ids = args.run or await db_client.get_calls_to_review(
        args.org, args.limit, include_reviewed=args.redo
    )
    if args.run:
        # Only the organization's own calls.
        own = set(
            await db_client.get_calls_to_review(
                args.org, 100_000, include_reviewed=True
            )
        )
        run_ids = [r for r in run_ids if r in own]
    counts: dict[str, int] = {}
    for run_id in run_ids:
        outcome = await review_call(run_id, redo=args.redo)
        counts[outcome] = counts.get(outcome, 0) + 1
        print(f"run {run_id}: {outcome}")
        if args.show and outcome in (ReviewOutcome.REVIEWED, ReviewOutcome.SILENT):
            run = await db_client.get_workflow_run_by_id(run_id)
            print(
                json.dumps(stored_review(run.annotations), indent=2, ensure_ascii=False)
            )
    print(
        "done:",
        ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nothing to do",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--org", type=int, required=True, help="organization id")
    parser.add_argument("--limit", type=int, default=20, help="at most this many calls")
    parser.add_argument(
        "--run", type=int, action="append", help="only this call (repeatable)"
    )
    parser.add_argument(
        "--redo", action="store_true", help="review calls that have one again"
    )
    parser.add_argument("--show", action="store_true", help="print each stored review")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()

"""Run the whole pipeline with one command:

    python run_pipeline.py                 # ingest -> transform -> publish
    python run_pipeline.py --skip-publish  # local only (no Google Sheets)
    python run_pipeline.py --only publish  # run a single step
"""
import argparse
import logging
import sys
import time

import config  # noqa: F401  (sets up logging)
import ingest
import publish
import transform

log = logging.getLogger("pipeline")

STEPS = {
    "ingest": ingest.run,
    "transform": transform.run,
    "publish": publish.run,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="US Accidents data pipeline")
    parser.add_argument("--skip-publish", action="store_true", help="do not upload to Google Sheets")
    parser.add_argument("--only", choices=STEPS.keys(), help="run just one step")
    args = parser.parse_args()

    steps = [args.only] if args.only else list(STEPS)
    if args.skip_publish and "publish" in steps:
        steps.remove("publish")

    t_all = time.perf_counter()
    for name in steps:
        log.info("===== %s: start =====", name.upper())
        t0 = time.perf_counter()
        try:
            STEPS[name]()
        except Exception:
            log.exception("Step '%s' failed - pipeline stopped", name)
            return 1
        log.info("===== %s: done in %.1fs =====", name.upper(), time.perf_counter() - t0)

    log.info("Pipeline finished in %.1fs (%s)", time.perf_counter() - t_all, " -> ".join(steps))
    return 0


if __name__ == "__main__":
    sys.exit(main())

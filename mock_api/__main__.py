"""Start the mock API: ``python -m mock_api [--port 8000] [--chaos]``."""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the mock property-management source APIs.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--chaos", action="store_true", help="return occasional HTTP 429s")
    parser.add_argument("--chaos-rate", type=float, help="share of calls that get a 429")
    args = parser.parse_args()

    # CLI flags override .env.
    if args.chaos:
        os.environ["MOCK_CHAOS"] = "true"
    if args.chaos_rate is not None:
        os.environ["MOCK_CHAOS_RATE"] = str(args.chaos_rate)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from mock_api.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

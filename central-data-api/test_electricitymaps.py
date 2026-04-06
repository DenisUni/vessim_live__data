import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent

from logger import setup_logger

logger = setup_logger(
    __name__,
    "TEST",
    {
        "log_folder": str(BASE_DIR / "logs"),
        "log_level_file": "INFO",
        "log_level_console": "INFO",
    },
)


def run_test(with_pre_cache=False):
    base_url = "http://127.0.0.1:8000/electricitymaps/carbon-intensity/past-range"
    start_of_day = datetime(2026, 2, 1, 0, 0)

    step_5min = timedelta(minutes=5)

    logger.info(
        "Starting test for 24h. Mode: %s",
        "WITH 6h-pre-cache" if with_pre_cache else "WITHOUT pre-cache"
    )

    request_count = 0
    pre_cache_request_count = 0

    for block in range(4):
        block_start = start_of_day + timedelta(hours=6 * block)
        block_end = start_of_day + timedelta(hours=6 * (block + 1))

        logger.info("--- Starting 6-hour block: %s to %s ---", block_start, block_end)

        if with_pre_cache:
            pre_cache_request_count += 1
            start_str_6h = block_start.strftime("%Y-%m-%dT%H:%M") + "Z"
            end_str_6h = block_end.strftime("%Y-%m-%dT%H:%M") + "Z"

            params_6h = {
                "zone": "DE",
                "temporalGranularity": "5_minutes",
                "start": start_str_6h,
                "end": end_str_6h,
            }

            logger.info("Sending pre-cache request #%s for 6h block: start=%s | end=%s", pre_cache_request_count, start_str_6h,
                        end_str_6h)
            _send_request(base_url, params_6h)
            time.sleep(1)

        current_time = block_start
        while current_time < block_end:
            request_count += 1
            next_time = current_time + step_5min

            start_str = current_time.strftime("%Y-%m-%dT%H:%M") + "Z"
            end_str = next_time.strftime("%Y-%m-%dT%H:%M") + "Z"

            params = {
                "zone": "DE",
                "temporalGranularity": "5_minutes",
                "start": start_str,
                "end": end_str,
            }

            logger.info("Sending request #%s for: start=%s | end=%s", request_count, start_str, end_str)
            _send_request(base_url, params)

            time.sleep(1)
            current_time += step_5min

    logger.info("Test finished successfully. Total requests: %s (pre-cache requests: %s)", request_count, pre_cache_request_count)


def _send_request(url, params):
    try:
        response = requests.get(url, params=params)
        if response.ok:
            logger.info("Status Code: %s", response.status_code)
        else:
            logger.warning("Status Code: %s | Response: %s", response.status_code, response.text)
    except requests.exceptions.RequestException as e:
        logger.exception("Connection error: %s", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pre_cache",
        action="store_true"
    )
    args = parser.parse_args()
    run_test(with_pre_cache=args.pre_cache)
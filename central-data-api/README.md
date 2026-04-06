# central-data-api

## Project structure

This README only covers the `central-data-api` module.

```text
central-data-api/
├── api.py                  # FastAPI app with dynamic proxy + cache handling
├── utilities.py            # config loading, date normalization, helper functions
├── logger.py               # shared logger setup
├── config.json             # app and external API configuration
├── requirements.txt        # Python dependencies
├── test_electricitymaps.py # request-based test runner for Electricity Maps
├── cache.db                # SQLite cache database (created/used at runtime)
└── logs/                   # runtime logs
```

## What the application does

`central-data-api` is a FastAPI-based proxy service with integrated SQLite caching.

Main functionality:

1. Dynamic API proxy
   - Endpoint pattern: `/{api_name}/{endpoint_path:path}`
   - Example target: `electricitymaps/carbon-intensity/past-range`
   - Query params from the incoming request are merged with configured defaults.

2. Request normalization
   - Time values are normalized to a consistent format before querying/storing.
   - Parameters are separated into time-related and non-time-related parts.

3. Local cache lookup in `cache.db`
   - A table is created per API/path combination.
   - Missing columns are added automatically when needed.
   - Deduplication is handled via unique indexes (`INSERT OR IGNORE`).

4. Cache completeness check for time ranges
   - For range requests (`start`/`end`), expected row count is calculated from granularity.
   - If cached rows are complete, data is returned from cache.
   - If incomplete/empty, the external API is called.

5. External fetch and cache fill
   - On cache miss, data is fetched from the configured external API.
   - Returned records are normalized and written into `cache.db`.
   - The response is then returned to the client.

6. Logging
   - General app logs are written to daily log files in `logs/`.
   - Additional cache-miss request logs are written to a dedicated daily file (`*_api_requests.log`).
   - Only request information is logged there (no full API response payload).

## Request flow (high level)

1. Receive request on `/{api_name}/{endpoint_path:path}`.
2. Load API-specific config from `config.json`.
3. Normalize/prepare query parameters.
4. Query local cache.
5. If cache is complete: return cached data.
6. If cache miss/incomplete: fetch external data, cache it, return it.

## Start the software

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. (Optional, recommended) provide your API key via `.env`, for example:

```env
ELECTRICITYMAPS_API_KEY=your_api_key_here
```

3. Start the API server:

```bash
python api.py
```

The server uses host/port from `config.json` (`127.0.0.1:8000` by default).

## Run electricitymaps-tests

`test_electricitymaps.py` supports two modes:

- Total simulated period: 24 hours.
- Simulation granularity: 5-minute slices.
- Real-time pacing: each request waits `1` second (`time.sleep(1)`).
- This means: **1 second real time corresponds to one 5-minute simulation step**.

Test loop details:

1. The day is split into 4 blocks of 6 hours each.
2. In every block, 5-minute requests are sent from block start to block end.
3. Each 5-minute request calls:
   - `GET /electricitymaps/carbon-intensity/past-range`
   - Params: `zone=DE`, `temporalGranularity=5_minutes`, `start`, `end`
4. The logger prints each request and the returned HTTP status code.

### 1) Without caching

- Set `api.electricitymaps.enabled` to `false` in `config.json`.
- Run the test **without** pre-cache flag:

```bash
python test_electricitymaps.py
```

Behavior:

- No pre-cache call is sent at the start of a 6-hour block.
- For each 5-minute step, the API route directly fetches from the external source.
- Useful as baseline for uncached behavior and external call volume.

### 2) With caching + 6h pre-caching

- Set `api.electricitymaps.enabled` to `true` in `config.json`.
- Run the test **with** pre-cache flag:

```bash
python test_electricitymaps.py --pre_cache
```

Behavior:

- At the start of each 6-hour block, one pre-cache request is sent for the full 6-hour range.
- Afterwards, the following 5-minute requests in that block can be served from cache.
- This mode demonstrates cache warm-up and cache-hit behavior.

## Notes

- Ensure the API server is already running before starting `test_electricitymaps.py`.
- For Electricity Maps access, provide `ELECTRICITYMAPS_API_KEY` (for example via `.env`).
- Cache and logs persist between runs unless you clear `cache.db` and `logs/`.

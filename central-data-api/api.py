import sqlite3
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
import os
from fastapi import FastAPI, Request, HTTPException
from typing import Dict, Any, List
from dotenv import load_dotenv
from logger import setup_logger
from utilities import load_config, sanitize_table_name, normalize_date_str, calculate_expected_rows
from dateutil import parser, relativedelta

app_config = {}
api_config = {}


def setup_api_request_logger(app_conf: Dict[str, Any]) -> logging.Logger:
    log_folder = app_conf.get("log_folder", "logs")
    os.makedirs(log_folder, exist_ok=True)
    log_filename = os.path.join(log_folder, f"{datetime.now().strftime('%Y-%m-%d')}_external_requests.log")

    req_logger = logging.getLogger("API_REQUESTS")
    if getattr(req_logger, "_cache_miss_logger_configured", False):
        return req_logger

    formatter = logging.Formatter(
        '%(asctime)s,%(msecs)03d %(levelname)s API_REQUESTS: %(message)s',
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    req_logger.addHandler(file_handler)
    req_logger.setLevel(logging.INFO)
    req_logger.propagate = False
    req_logger._cache_miss_logger_configured = True
    return req_logger

# --- Helper functions ---

def get_db_connection():
    conn = sqlite3.connect(app_config.get("db_name"))
    conn.row_factory = sqlite3.Row
    return conn

def ensure_table_exists(conn, table_name: str, columns_to_add: List[str], unique_keys: List[str] = None):
    """
    Creates a table if it does not exist, dynamically adds columns,
    and ensures a unique index exists for deduplication.
    """
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (id INTEGER PRIMARY KEY AUTOINCREMENT)")

    existing_cols_info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_cols = {col["name"] for col in existing_cols_info}

    for key in columns_to_add:
        if key not in existing_cols:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {key} TEXT")

    if unique_keys:
        index_name = f"idx_{table_name}_unique"
        cols_sql = ", ".join(unique_keys)
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table_name} ({cols_sql})")

def insert_data_into_db(conn, table_name: str, data_list: List[Dict], final_params: Dict):
    if not data_list:
        return
    all_keys = set(final_params.keys())
    for item in data_list:
        all_keys.update(item.keys())

    ensure_table_exists(conn, table_name, list(all_keys))

    table_info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    table_cols = {col["name"] for col in table_info}

    for item in data_list:
        insert_data = item.copy()
        insert_data.update(final_params)

        valid_insert_data = {k: v for k, v in insert_data.items() if k in table_cols}
        insert_cols = list(valid_insert_data.keys())
        placeholders = ["?"] * len(insert_cols)

        insert_values = [json.dumps(v) if isinstance(v, (dict, list, bool)) or v is None else str(v) for v in valid_insert_data.values()]

        sql = f"INSERT OR IGNORE INTO {table_name} ({', '.join(insert_cols)}) VALUES ({', '.join(placeholders)})"
        conn.execute(sql, insert_values)
    logger.info(f"Inserted {len(data_list)} rows into {table_name}")

def json_loads(value):
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value

# --- Dynamic Proxy Helper Functions ---

def get_api_config(api_name: str):
    """Gets the configuration for a given API."""
    if api_name == "favicon.ico":
        return None
    conf = api_config.get(api_name)
    if not conf:
        raise HTTPException(status_code=404, detail=f"API '{api_name}' not in config.json found.")
    return conf

def prepare_parameters(conf: Dict, request_params: Dict):
    """Prepares and normalizes API parameters, separating time-related ones."""
    final_params = conf.get("default_params", {}).copy()
    final_params.update(request_params)

    time_keys = conf.get("time_keys", {})
    time_param_keys = {time_keys.get("datetime_key"), time_keys.get("start_key"), time_keys.get("end_key")}

    time_params = {}
    other_params = {}

    for key, value in final_params.items():
        if key in time_param_keys and value:
            norm_val = normalize_date_str(value)
            time_params[key] = norm_val
            final_params[key] = norm_val  # Update final_params as well
        else:
            other_params[key] = value

    return final_params, time_params, other_params

def query_cache(conn, table_name: str, other_params: Dict, time_params: Dict, time_keys: Dict):
    """Queries the local database cache for data."""
    datetime_key = time_keys.get("datetime_key")
    start_key = time_keys.get("start_key")
    end_key = time_keys.get("end_key")

    clauses = [f"{key} = ?" for key in other_params.keys()]
    values = [str(v) for v in other_params.values()]

    if datetime_key and start_key in time_params and end_key in time_params:
        clauses.append(f"{datetime_key} >= ? AND {datetime_key} < ?")
        values.extend([time_params[start_key], time_params[end_key]])
    elif datetime_key in time_params:
        clauses.append(f"{datetime_key} = ?")
        values.append(time_params[datetime_key])

    query = f"SELECT * FROM {table_name}"
    if clauses:
        query += f" WHERE {' AND '.join(clauses)}"

    logger.debug(f"DB Query: {query} | Values: {values}")
    cursor = conn.execute(query, values)
    return cursor.fetchall()

def is_cache_complete(rows: List, time_params: Dict, final_params: Dict, conf: Dict) -> tuple(list[bool, str]):
    """Checks if the cached data is complete for the given time range."""
    if not rows:
        return False, "Cache is empty."

    time_keys = conf.get("time_keys", {})
    start_key = time_keys.get("start_key")
    end_key = time_keys.get("end_key")

    if not (time_keys.get("datetime_key") and start_key in time_params and end_key in time_params):
        return True, "Not a time range query, cache is considered complete if not empty"   # Not a time range query, so cache is considered complete if not empty

    try:
        start_dt = parser.parse(time_params[start_key])
        end_dt = parser.parse(time_params[end_key])

        granularity_name = conf.get("granularity_name")
        req_granularity = final_params.get(granularity_name) or conf.get("default_params", {}).get("granularity")
        expected_rows = calculate_expected_rows(start_dt, end_dt, req_granularity, conf)

        if len(rows) < expected_rows:
            return False, f"Incomplete Cache ({req_granularity}): Found {len(rows)}/{expected_rows} rows."
        else:
            return True, f"Cache Complete ({req_granularity}): Found {len(rows)}/{expected_rows} rows."

    except Exception as e:
        logger.error(f"Completeness check failed: {e}")
        return False

def format_cache_response(rows: List, final_params: Dict) -> List[Dict]:
    """Formats database rows into a response list, filtering out None values."""
    response_data = []
    ignore_keys = {"id"}

    for row in rows:
        item = {
            key: json_loads(row[key])
            for key in row.keys()
            if key not in ignore_keys and row[key] is not None
        }
        response_data.append(item)
    return response_data

async def fetch_from_external_api(endpoint_path: str, api_name: str, conf: Dict, final_params: Dict, message: str | None = None) -> Any:
    """Fetches data from the external API."""
    if message is not None: message = f" ({message})"
    logger.info(f"Cache MISS for {api_name}/{endpoint_path}{message}")
    base_url = conf["base_url"].rstrip("/")
    clean_path = endpoint_path.lstrip("/")
    full_url = f"{base_url}/{clean_path}"
    api_request_logger.info("GET %s | api=%s | endpoint=%s | params=%s", full_url, api_name, clean_path, final_params)

    headers = {}
    if conf.get("auth"):
        auth_conf = conf["auth"]
        api_key = auth_conf.get("api_key") or os.getenv(f"{api_name.upper()}_API_KEY")
        if api_key:
            headers[auth_conf["header_name"]] = api_key

    timeout = app_config.get("request_timeout", 20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        logger.debug(f"Calling external API: GET {full_url} with params {final_params}")
        response = await client.get(full_url, params=final_params, headers=headers)
        response.raise_for_status()
        return response.json()

def process_and_cache_response(conn, table_name: str, data: Any, conf: Dict, final_params: Dict) -> Any:
    """Processes API data, caches it, and returns the final response data."""
    data_keys = conf.get("data_keys", [])
    datetime_key = conf.get("time_keys", {}).get("datetime_key")

    nested_data_key = next((key for key in data_keys if key in data and isinstance(data[key], list)), None)

    data_to_cache = []
    response_data = data

    if nested_data_key:
        data_list = data[nested_data_key]
        metadata = {k: v for k, v in data.items() if k != nested_data_key}
        for item in data_list:
            item.update(metadata)
            if datetime_key in item:
                item[datetime_key] = normalize_date_str(item[datetime_key])
        data_to_cache = data_list
        response_data = data_list
    elif isinstance(data, dict):
        if datetime_key in data:
            data[datetime_key] = normalize_date_str(data[datetime_key])
        data_to_cache = [data]
    else:
        data_to_cache = [{"response_data": data}]

    insert_data_into_db(conn, table_name, data_to_cache, final_params)
    conn.commit()
    return response_data

# --- App Handler ---
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    load_dotenv()
    logger.info(f"Starting {app.title} v{app.version}...")
    yield
    logger.info(f"Shutting down {app.title}...")

app_config, api_config = load_config()
logger = setup_logger(__name__, "MAIN", app_config)
api_request_logger = setup_api_request_logger(app_config)
app = FastAPI(title=app_config.get("app_name"),
              version=app_config.get("app_version"),
              lifespan=app_lifespan,
              debug=app_config.get("debug"))

# --- Main Endpoint ---
@app.get("/{api_name}/{endpoint_path:path}")
async def dynamic_proxy(api_name: str, endpoint_path: str, request: Request):
    conf = get_api_config(api_name)
    if conf is None:
        return {}

    conn = get_db_connection()
    try:
        final_params, time_params, other_params = prepare_parameters(conf, dict(request.query_params))
        if not conf.get("enabled"):
            return await fetch_from_external_api(endpoint_path, api_name, conf, final_params, "API disabled")

        table_name = sanitize_table_name(api_name, endpoint_path)
        time_keys = conf.get("time_keys", {})
        datetime_key = time_keys.get("datetime_key")

        initial_columns = list(final_params.keys())
        if datetime_key and datetime_key not in initial_columns:
            initial_columns.append(datetime_key)
        unique_cols = list(other_params.keys())
        if datetime_key:
            unique_cols.append(datetime_key)

        ensure_table_exists(conn, table_name, list(set(initial_columns)), unique_keys=unique_cols)

        # 1. Query cache
        rows = query_cache(conn, table_name, other_params, time_params, time_keys)

        # 2. Check cache completeness
        cache_complete, message = is_cache_complete(rows, time_params, final_params, conf)
        if cache_complete:
            logger.info(f"Cache HIT for {table_name} ({message})")
            response_data = format_cache_response(rows, final_params)

            if len(response_data) == 1 and not isinstance(response_data[0], list):
                return response_data[0]
            return response_data

        # 3. Fetch from external API
        api_data = await fetch_from_external_api(endpoint_path, api_name, conf, final_params, message)

        # 4. Process and cache
        return process_and_cache_response(conn, table_name, api_data, conf, final_params)

    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        raise HTTPException(status_code=500, detail=f"DB Error: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"External API error: {e}")
        raise HTTPException(status_code=e.response.status_code, detail=f"External API Error: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    import uvicorn

    app_config, api_config = load_config()

    uvicorn.run(
        "api:app",
        host=app_config.get("host"),
        port=app_config.get("port"),
        reload=app_config.get("debug"),
        log_level="debug" if app_config.get("debug") else "info",
        access_log=app_config.get("debug"),
    )

import json
import os
from datetime import datetime, timezone
from typing import Dict

from dateutil import parser
from dateutil.relativedelta import relativedelta

CONFIG_FILE = "config.json"

def load_config() -> tuple[dict, dict]:
	"""Loads the configuration from the JSON file."""
	if not os.path.exists(CONFIG_FILE):
		raise FileNotFoundError(f"Configuration file '{CONFIG_FILE}' not found.")

	with open(CONFIG_FILE, "r") as f:
		config = json.load(f)

	app_config = config.get("app", {})
	api_config = config.get("api", {})

	if not app_config or not api_config:
		raise ValueError("Invalid configuration format in 'config.json'. 'app' and 'api' sections are required.")
	return app_config, api_config

def sanitize_table_name(api_name: str, endpoint_name: str) -> str:
	clean_endpoint = endpoint_name.strip("/").replace("/", "_").replace("-", "_")
	return f"{api_name}_{clean_endpoint}"

def get_granularity_delta(granularity_name: str, api_conf: Dict) -> relativedelta:
	"""
    Loads the time delta definition from the config and converts it into a
    relativedelta object.
    """
	definitions = api_conf.get("granularity_definitions", {})
	delta_args = definitions.get(granularity_name)

	if not delta_args: # fallback
		return relativedelta(hours=1)
	return relativedelta(**delta_args)

def calculate_expected_rows(start_dt: datetime, end_dt: datetime, granularity_name: str, api_conf: Dict) -> int:
	"""
    Calculates the expected number of data points based on the config.
    """
	step = get_granularity_delta(granularity_name, api_conf)
	count = 0
	current = start_dt
	while current < end_dt:
		count += 1
		current += step
	return count

def normalize_date_str(date_value) -> str:
	"""
    Converts time strings to a uniform ISO format (without milliseconds).
    Makes string comparison in SQLite robust.
    """
	if not date_value:
		return None
	try:
		if isinstance(date_value, str):
			dt = parser.parse(date_value)
		else:
			dt = date_value

		if dt.tzinfo is None: # Ensure that TZ info is present (default to UTC)
			dt = dt.replace(tzinfo=timezone.utc)
		return dt.isoformat(timespec='seconds') # Format: ISO 8601, seconds precision (strips .000 ms)
	except Exception as e:
		return str(date_value) # Fallback: Return original value if parsing fails

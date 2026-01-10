import logging
import requests
from datetime import datetime
from typing import Optional, Dict, Any


class ElectricityMapsService:
    """Handles communication with the Electricity Maps API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.electricitymaps.com/v3"
        self.logger = logging.getLogger(__name__)
        
        if not self.api_key:
            self.logger.warning("⚠️ No Electricity Maps API Key found!")

    def check_connection(self) -> bool:
        """Checks if the API key is valid and the server is reachable."""
        if not self.api_key:
            self.logger.error("Electricity Maps API key not set")
            return False
        
        try:
            # Test with a simple zone query
            url = f"{self.base_url}/carbon-intensity/latest?zone=DE"
            headers = {"auth-token": self.api_key}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                self.logger.info("✅ Electricity Maps API connection successful")
                return True
            elif response.status_code == 401:
                self.logger.error("❌ Electricity Maps API Authentication failed")
                return False
            else:
                self.logger.warning(f"⚠️ Electricity Maps API returned status {response.status_code}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Electricity Maps API connection error: {e}")
            return False

    def fetch_latest_data(self, zone: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the latest carbon intensity data for a specific zone.
        """
        if not self.api_key:
            raise ValueError("Electricity Maps API key not set")

        try:
            url = f"{self.base_url}/carbon-intensity/latest?zone={zone}"
            headers = {"auth-token": self.api_key}
            
            self.logger.info(f"Fetching latest carbon intensity for {zone}")
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            self.logger.error(f"Electricity Maps API error: {e}")
            raise

    def fetch_forecast_data(self, zone: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the carbon intensity forecast for a specific zone.
        """
        if not self.api_key:
            raise ValueError("Electricity Maps API key not set")

        try:
            url = f"{self.base_url}/carbon-intensity/forecast?zone={zone}"
            headers = {"auth-token": self.api_key}
            
            self.logger.info(f"Fetching carbon intensity forecast for {zone}")
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            self.logger.error(f"Electricity Maps API error: {e}")
            raise

    def fetch_history_data(self, zone: str, start: datetime, end: datetime) -> Optional[Dict[str, Any]]:
        """
        Fetches historical carbon intensity data for a specific zone and time range.
        Note: This endpoint may require a premium subscription.
        """
        if not self.api_key:
            raise ValueError("Electricity Maps API key not set")

        try:
            url = f"{self.base_url}/carbon-intensity/history"
            headers = {"auth-token": self.api_key}
            params = {
                "zone": zone,
                "start": start.isoformat(),
                "end": end.isoformat()
            }
            
            self.logger.info(f"Fetching carbon intensity history for {zone} from {start} to {end}")
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            self.logger.error(f"Electricity Maps API error: {e}")
            raise
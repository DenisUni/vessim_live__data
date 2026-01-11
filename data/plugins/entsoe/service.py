import logging
import pandas as pd
from entsoe import EntsoePandasClient


class EntsoeService:
    """Handles communication with the ENTSO-E Transparency Platform API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.client = None
        self.logger = logging.getLogger(__name__)
        if self.api_key:
            self.client = EntsoePandasClient(api_key=self.api_key)

    def check_connection(self) -> bool:
        """Checks if the API key is valid and the server is reachable."""
        if not self.api_key:
            self.logger.error("ENTSO-E API key is not set.")
            return False
        
        if not self.client:
            self.client = EntsoePandasClient(api_key=self.api_key)

        try:
            # Try a simple query to check connectivity
            end = pd.Timestamp.now(tz='UTC')
            start = end - pd.Timedelta(hours=1)
            # Use a common zone like Germany/Luxembourg for the check
            self.client.query_day_ahead_prices('DE_LU', start=start, end=end)
            return True
        except Exception as e:
            # The entsoe-py library can raise various exceptions.
            # A common one for invalid keys is a simple Exception with a message.
            if "401" in str(e) or "Unauthorized" in str(e):
                self.logger.error(f"ENTSO-E API Authentication failed: {e}")
                return False
            # If no data is found, the connection is still considered successful
            elif "No matching data found" in str(e):
                self.logger.info("Connection successful (though no data returned for the test query).")
                return True
            else:
                self.logger.warning(f"Could not connect to ENTSO-E API: {e}")
                return False

    def fetch_price_data(
            self,
            zone: str,
            start: pd.Timestamp,
            end: pd.Timestamp
    ) -> pd.Series:
        """
        Fetches day-ahead price data for a specific zone and time range.
        """
        if not self.client:
            raise ValueError("ENTSO-E Client not initialized. Check API Key.")

        try:
            self.logger.info(f"Fetching prices for {zone} from {start} to {end}")
            # This returns a pandas Series with datetime index and price values
            price_series = self.client.query_day_ahead_prices(
                country_code=zone,
                start=start,
                end=end
            )
            return price_series
        except Exception as e:
            self.logger.error(f"ENTSO-E API error: {e}")
            raise

def fill_missing_timestamps(price_series: pd.Series, resolution_minutes: int = 15) -> pd.Series:
    """
    ENTSO-E API may omit timestamps where the price is unchanged.
    This function creates a complete time series by forward-filling missing values.
    """
    if price_series.empty:
        return price_series

    # Create a complete datetime range at the specified resolution
    full_range = pd.date_range(
        start=price_series.index.min(),
        end=price_series.index.max(),
        freq=f'{resolution_minutes}min',
        tz=price_series.index.tz
    )

    # Reindex the series to the complete range, forward-filling missing prices
    complete_series = price_series.reindex(full_range, method='ffill')

    return complete_series

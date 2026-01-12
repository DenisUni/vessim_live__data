import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd
from core.database import get_managed_session
from core.logger import setup_logger
from fastapi import APIRouter
from dotenv import load_dotenv, set_key
from fastapi import Depends, HTTPException, BackgroundTasks
from sqlmodel import Session, select

from .models import EntsoePrice, EntsoePriceCreate, EntsoePricePublic
from .service import EntsoeService, fill_missing_timestamps

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

# Each plugin has its own router
router = APIRouter(prefix="/entsoe", tags=["entsoe"])

entsoe_service = EntsoeService(api_key=os.environ.get("ENTSOE_API_KEY"))

logger = setup_logger(__name__, "ENTSOE-API")


def startup():
    """
    Perform startup checks for the ENTSO-E plugin.
    If the API key is missing or invalid, prompt for it via terminal.
    """
    logging.info("Checking ENTSO-E API connection...")
    if not entsoe_service.check_connection():
        logging.warning("ENTSO-E connection failed. Starting interactive setup...")
        _interactive_setup()
    else:
        logging.info("✅ ENTSO-E connection verified.")


def _interactive_setup():
    """
    Interactive terminal setup for ENTSO-E API key.
    """
    print("\n--- ENTSO-E Setup ---")
    print("API key is missing or invalid.")

    while True:
        api_key = input("Please enter your ENTSO-E API key: ").strip()
        if not api_key:
            print("API key cannot be empty.")
            continue

        # Test the new API key
        temp_service = EntsoeService(api_key=api_key)
        if temp_service.check_connection():
            print("API key is valid!")
            _save_credentials(api_key)
            # Update the global service instance
            entsoe_service.api_key = api_key
            break
        else:
            print("API key is invalid. Please try again.")


def _save_credentials(api_key: str):
    """
    Ask user if they want to save the API key to .env and do so if confirmed.
    """
    save = input("Do you want to save this API key to the .env file? [y/N]: ").strip().lower()
    if save == 'y':
        try:
            if not os.path.exists(dotenv_path):
                with open(dotenv_path, 'w') as f:
                    f.write("")

            set_key(dotenv_path, "ENTSOE_API_KEY", api_key)
            print(f"API key saved to {dotenv_path}")
        except Exception as e:
            logging.error(f"Failed to save API key to .env: {e}")
            print(f"Error saving API key: {e}")


# --- API Endpoints ---

@router.get("/")
def get_overview():
    """Returns an overview of available endpoints for the ENTSO-E plugin."""
    return {
        "message": "Welcome to the ENTSO-E API. Available endpoints:",
        "endpoints": [
            {"path": "/prices/", "method": "GET",
             "description": "Retrieve ENTSO-E price data for a given zone and time range. Fetches from cache or ENTSO-E API."},
            {"path": "/prices/", "method": "POST",
             "description": "Manually store a single ENTSO-E price data point in the cache."},
            {"path": "/prices/fetch-range/", "method": "POST",
             "description": "Trigger a background task to fetch and store a range of ENTSO-E price data."},
            {"path": "/health", "method": "GET", "description": "Check the health status of the ENTSO-E plugin."}
        ]
    }


@router.post("/prices/", response_model=EntsoePricePublic)
def create_price_entry(
        price: EntsoePriceCreate,
        session: Session = Depends(get_managed_session)
):
    """Store a single price data point in the cache. Useful for manual updates."""
    db_price = EntsoePrice.model_validate(price)
    session.add(db_price)
    session.commit()
    session.refresh(db_price)
    return db_price


@router.get("/prices/", response_model=List[EntsoePricePublic])
def get_prices(
        zone: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        session: Session = Depends(get_managed_session)
):
    """
    Main endpoint for Vessim to retrieve price data.
    Returns cached data; if missing, fetches from ENTSO-E.
    """
    # Set default end time if not provided
    if end_time is None:
        end_time = start_time + timedelta(days=1)

    # 1. Check cache first
    statement = select(EntsoePrice).where(
        EntsoePrice.zone == zone,
        EntsoePrice.datetime_utc >= start_time,
        EntsoePrice.datetime_utc <= end_time
    ).order_by(EntsoePrice.datetime_utc)

    cached_results = session.exec(statement).all()

    if cached_results:
        # Check if we have a complete set for the requested range
        cached_times = {p.datetime_utc for p in cached_results}
        expected_count = int((end_time - start_time).total_seconds() / (15 * 60))

        if len(cached_results) >= expected_count * 0.8:  # 80% threshold
            return cached_results

    # 2. If cache is insufficient, fetch from ENTSO-E
    start_pd = pd.Timestamp(start_time)
    end_pd = pd.Timestamp(end_time)

    try:
        # Fetch raw price series from ENTSO-E
        raw_prices = entsoe_service.fetch_price_data(zone, start_pd, end_pd)

        # Fill any gaps in the data
        complete_prices = fill_missing_timestamps(raw_prices, resolution_minutes=15)

        # Store in database
        for timestamp, price_value in complete_prices.items():
            price_entry = EntsoePrice(
                zone=zone,
                datetime_utc=timestamp.to_pydatetime(),
                price_eur_per_mwh=price_value,
                resolution_minutes=15
            )
            # Use merge to handle duplicates gracefully
            session.merge(price_entry)

        session.commit()

        # Return the newly fetched data
        statement = select(EntsoePrice).where(
            EntsoePrice.zone == zone,
            EntsoePrice.datetime_utc >= start_time,
            EntsoePrice.datetime_utc <= end_time
        ).order_by(EntsoePrice.datetime_utc)

        return session.exec(statement).all()

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch data from ENTSO-E: {str(e)}"
        )


@router.post("/prices/fetch-range/")
def fetch_and_store_range(
        zone: str,
        start_time: datetime,
        end_time: datetime,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_managed_session)
):
    """
    Explicitly trigger a fetch for a time range and store it.
    Useful for pre-caching historical data for simulations.
    """
    # This could run in the background for large ranges
    background_tasks.add_task(
        fetch_range_task,
        zone, start_time, end_time, session
    )
    return {"message": "Fetch job started in background"}


def fetch_range_task(zone: str, start_time: datetime, end_time: datetime, session: Session):
    """Background task to fetch and store a range of price data."""
    try:
        start_pd = pd.Timestamp(start_time)
        end_pd = pd.Timestamp(end_time)

        raw_prices = entsoe_service.fetch_price_data(zone, start_pd, end_pd)
        complete_prices = fill_missing_timestamps(raw_prices, resolution_minutes=15)

        for timestamp, price_value in complete_prices.items():
            price_entry = EntsoePrice(
                zone=zone,
                datetime_utc=timestamp.to_pydatetime(),
                price_eur_per_mwh=price_value,
                resolution_minutes=15
            )
            session.merge(price_entry)

        session.commit()
        logger.info(f"Successfully fetched and stored prices for {zone} from {start_time} to {end_time}")
    except Exception as e:
        logger.error(f"Background fetch failed: {e}")


@router.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc)}

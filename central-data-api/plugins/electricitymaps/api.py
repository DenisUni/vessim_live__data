import os
from datetime import datetime, timezone
from typing import List, Optional

from core.database import get_managed_session
from core.logger import setup_logger
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session, select

from .models import (
    ElectricityMapsCarbonIntensity,
    ElectricityMapsCarbonIntensityCreate,
    ElectricityMapsCarbonIntensityPublic
)
from .service import ElectricityMapsService

logger = setup_logger(__name__, "ELECTRICITYMAPS-API")

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

# Each plugin has its own router
router = APIRouter(prefix="/electricitymaps", tags=["electricitymaps"])

# Initialize the service with API key
electricitymaps_service = ElectricityMapsService(
    api_key=os.environ.get("ELECTRICITYMAPS_API_KEY", "bZ7ygQs4iiC3ksas2aqV")
)


def startup():
    """
    Perform startup checks for the Electricity Maps plugin.
    """
    logger.info("Checking Electricity Maps API connection...")
    electricitymaps_service.check_connection()


# --- API Endpoints ---

@router.get("/")
def get_overview():
    """Returns an overview of available endpoints for the Electricity Maps plugin."""
    return {
        "message": "Welcome to the Electricity Maps API. Available endpoints:",
        "endpoints": [
            {"path": "/carbon-intensity/", "method": "GET",
             "description": "Retrieve carbon intensity data for a zone and time range"},
            {"path": "/carbon-intensity/", "method": "POST",
             "description": "Manually store a single carbon intensity data point"},
            {"path": "/carbon-intensity/latest/", "method": "POST",
             "description": "Fetch and store latest carbon intensity data"},
            {"path": "/carbon-intensity/forecast/", "method": "POST",
             "description": "Fetch and store forecast carbon intensity data"},
            {"path": "/health", "method": "GET", "description": "Check the health status of the plugin"}
        ]
    }


@router.post("/carbon-intensity/", response_model=ElectricityMapsCarbonIntensityPublic)
def create_carbon_intensity_entry(
        carbon_intensity: ElectricityMapsCarbonIntensityCreate,
        session: Session = Depends(get_managed_session)
):
    """Store a single carbon intensity data point in the database."""
    db_entry = ElectricityMapsCarbonIntensity.model_validate(carbon_intensity)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.get("/carbon-intensity/", response_model=List[ElectricityMapsCarbonIntensityPublic])
def get_carbon_intensity(
        zone: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        is_forecast: Optional[bool] = None,
        session: Session = Depends(get_managed_session)
):
    """
    Main endpoint to retrieve carbon intensity data.
    Returns cached data from database.
    """
    # Build query
    statement = select(ElectricityMapsCarbonIntensity).where(
        ElectricityMapsCarbonIntensity.zone == zone
    )

    if start_time:
        statement = statement.where(ElectricityMapsCarbonIntensity.datetime_utc >= start_time)

    if end_time:
        statement = statement.where(ElectricityMapsCarbonIntensity.datetime_utc <= end_time)

    if is_forecast is not None:
        statement = statement.where(ElectricityMapsCarbonIntensity.is_forecast == is_forecast)

    statement = statement.order_by(ElectricityMapsCarbonIntensity.datetime_utc)

    results = session.exec(statement).all()
    return results


@router.post("/carbon-intensity/latest/")
def fetch_and_store_latest(
        zone: str,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_managed_session)
):
    """
    Fetch the latest carbon intensity data from Electricity Maps API and store it.
    """
    try:
        data = electricitymaps_service.fetch_latest_data(zone)

        if not data:
            raise HTTPException(status_code=404, detail="No data returned from API")

        # Parse the response
        carbon_intensity_value = data.get("carbonIntensity")
        datetime_str = data.get("datetime")

        if not carbon_intensity_value or not datetime_str:
            raise HTTPException(status_code=500, detail="Invalid data format from API")

        # Convert datetime string to datetime object
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))

        # Create database entry
        entry = ElectricityMapsCarbonIntensity(
            zone=zone,
            datetime_utc=dt,
            carbon_intensity=carbon_intensity_value,
            is_forecast=False
        )

        # Use merge to handle duplicates
        session.merge(entry)
        session.commit()

        return {
            "message": "Latest data fetched and stored successfully",
            "zone": zone,
            "datetime": dt,
            "carbon_intensity": carbon_intensity_value
        }

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch data from Electricity Maps: {str(e)}"
        )


@router.post("/carbon-intensity/forecast/")
def fetch_and_store_forecast(
        zone: str,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_managed_session)
):
    """
    Fetch carbon intensity forecast from Electricity Maps API and store it.
    Runs in background for better performance.
    """
    background_tasks.add_task(
        fetch_forecast_task,
        zone, session
    )
    return {"message": "Forecast fetch job started in background"}


def fetch_forecast_task(zone: str, session: Session):
    """Background task to fetch and store forecast data."""
    try:
        data = electricitymaps_service.fetch_forecast_data(zone)

        if not data or "forecast" not in data:
            logger.warning(f"No forecast data available for zone {zone}")
            return

        # Process forecast data
        forecast_list = data.get("forecast", [])
        stored_count = 0

        for forecast_point in forecast_list:
            carbon_intensity_value = forecast_point.get("carbonIntensity")
            datetime_str = forecast_point.get("datetime")

            if carbon_intensity_value and datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))

                entry = ElectricityMapsCarbonIntensity(
                    zone=zone,
                    datetime_utc=dt,
                    carbon_intensity=carbon_intensity_value,
                    is_forecast=True
                )

                session.merge(entry)
                stored_count += 1

        session.commit()
        logger.info(f"Successfully stored {stored_count} forecast points for {zone}")

    except Exception as e:
        logger.error(f"Background forecast fetch failed: {e}")


@router.post("/carbon-intensity/history/")
def fetch_and_store_history(
        zone: str,
        start_time: datetime,
        end_time: datetime,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_managed_session)
):
    """
    Fetch historical carbon intensity data and store it.
    Note: May require premium API access.
    """
    background_tasks.add_task(
        fetch_history_task,
        zone, start_time, end_time, session
    )
    return {"message": "History fetch job started in background"}


def fetch_history_task(zone: str, start_time: datetime, end_time: datetime, session: Session):
    """Background task to fetch and store historical data."""
    try:
        data = electricitymaps_service.fetch_history_data(zone, start_time, end_time)

        if not data or "history" not in data:
            logger.warning(f"No historical data available for zone {zone}")
            return

        # Process historical data
        history_list = data.get("history", [])
        stored_count = 0

        for history_point in history_list:
            carbon_intensity_value = history_point.get("carbonIntensity")
            datetime_str = history_point.get("datetime")

            if carbon_intensity_value and datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))

                entry = ElectricityMapsCarbonIntensity(
                    zone=zone,
                    datetime_utc=dt,
                    carbon_intensity=carbon_intensity_value,
                    is_forecast=False
                )

                session.merge(entry)
                stored_count += 1

        session.commit()
        logger.info(f"Successfully stored {stored_count} historical points for {zone}")

    except Exception as e:
        logger.error(f"Background history fetch failed: {e}")


@router.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc),
        "service": "Electricity Maps"
    }

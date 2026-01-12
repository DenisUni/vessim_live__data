from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class ElectricityMapsCarbonIntensityBase(SQLModel):
    """Base model for Electricity Maps carbon intensity data."""
    zone: str = Field(index=True, description="Zone code (e.g., 'DE')")
    datetime_utc: datetime = Field(index=True, description="Timestamp of the data point")
    carbon_intensity: float = Field(description="Carbon intensity in gCO2eq/kWh")
    is_forecast: bool = Field(default=False, description="Whether this is forecast or historical data")


class ElectricityMapsCarbonIntensity(ElectricityMapsCarbonIntensityBase, table=True):
    """Database table model for storing carbon intensity data."""
    __tablename__ = "electricitymaps_carbon_intensity"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Unique constraint to prevent duplicate entries
    class Config:
        constraints = [("unique_zone_datetime", "UNIQUE(zone, datetime_utc, is_forecast)")]


class ElectricityMapsCarbonIntensityCreate(ElectricityMapsCarbonIntensityBase):
    """Model for creating new carbon intensity entries (API input)."""
    pass


class ElectricityMapsCarbonIntensityPublic(ElectricityMapsCarbonIntensityBase):
    """Model for public API response."""
    id: int

from datetime import datetime, timezone
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

    class Config:
        constraints = [("unique_zone_datetime", "UNIQUE(zone, datetime_utc, is_forecast)")]  # prevents duplicates


class ElectricityMapsCarbonIntensityCreate(ElectricityMapsCarbonIntensityBase):
    """Model for creating new carbon intensity entries (API input)."""
    pass


class ElectricityMapsCarbonIntensityPublic(ElectricityMapsCarbonIntensityBase):
    """Model for public API response."""
    id: int


class APICache(SQLModel, table=True):
    """Einfacher Cache für Proxy-Antworten."""
    __tablename__ = "api_cache"

    id: Optional[int] = Field(default=None, primary_key=True)
    cache_key: str = Field(index=True, unique=True)  # z.B. "GET:/v3/carbon-intensity/latest?zone=DE#body=..."
    response_body: str  # rohe Antwort (JSON/Text)
    status_code: int
    cached_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
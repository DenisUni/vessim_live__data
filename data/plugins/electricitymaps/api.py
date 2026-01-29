import hashlib
import logging
import os
from datetime import datetime, timedelta,timezone
from typing import List, Optional
import gzip
from wsgiref import headers
import httpx
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from sqlmodel import Session, select

from core.database import get_managed_session
from .service import ElectricityMapsService
from .models import (
    ElectricityMapsCarbonIntensity,
    ElectricityMapsCarbonIntensityCreate,
    ElectricityMapsCarbonIntensityPublic,
    APICache,
)

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=dotenv_path)

router = APIRouter(prefix="/electricitymaps", tags=["electricitymaps"])


### For Proxy-Cache ###
ELECTRICITYMAPS_BASE_URL = os.environ.get(
    "ELECTRICITYMAPS_BASE_URL", "https://api.electricitymap.org"
)
DEFAULT_TTL_MINUTES = int(os.environ.get("ELECTRICITYMAPS_CACHE_TTL_MINUTES", "15"))

#######


electricitymaps_service = ElectricityMapsService(
    api_key=os.environ.get("ELECTRICITYMAPS_API_KEY", "")
)


def startup():
    logging.info("Checking Electricity Maps API connection...")
    electricitymaps_service.check_connection()


@router.get("/")
def get_overview():
    return {
        "message": "Welcome to the Electricity Maps API. Available endpoints:",
        "endpoints": [
            {
                "path": "/carbon-intensity/",
                "method": "GET",
                "description": "Retrieve carbon intensity data for a zone and time range",
            },
            {
                "path": "/carbon-intensity/",
                "method": "POST",
                "description": "Manually store a single carbon intensity data point",
            },
            {
                "path": "/carbon-intensity/latest/",
                "method": "POST",
                "description": "Fetch and store latest carbon intensity data",
            },
            {
                "path": "/carbon-intensity/forecast/",
                "method": "POST",
                "description": "Fetch and store forecast carbon intensity data",
            },
            {
                "path": "/carbon-intensity/history/",
                "method": "POST",
                "description": "Fetch and store historical carbon intensity data",
            },
            {"path": "/health", "method": "GET", "description": "Check plugin health"},
            ### For Proxy-Cache ###
            {
                "path": "/{any}/…",
                "method": "ANY",
                "description": "Proxy to ElectricityMaps API (cached)",
            },######
        ],
    }


@router.post("/carbon-intensity/", response_model=ElectricityMapsCarbonIntensityPublic)
def create_carbon_intensity_entry(
    carbon_intensity: ElectricityMapsCarbonIntensityCreate,
    session: Session = Depends(get_managed_session),
):
    db_entry = ElectricityMapsCarbonIntensity.model_validate(carbon_intensity)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.get(
    "/carbon-intensity/", response_model=List[ElectricityMapsCarbonIntensityPublic]
)
def get_carbon_intensity(
    zone: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    is_forecast: Optional[bool] = None,
    session: Session = Depends(get_managed_session),
):
    statement = select(ElectricityMapsCarbonIntensity).where(
        ElectricityMapsCarbonIntensity.zone == zone
    )

    if start_time:
        statement = statement.where(
            ElectricityMapsCarbonIntensity.datetime_utc >= start_time
        )

    if end_time:
        statement = statement.where(
            ElectricityMapsCarbonIntensity.datetime_utc <= end_time
        )

    if is_forecast is not None:
        statement = statement.where(
            ElectricityMapsCarbonIntensity.is_forecast == is_forecast
        )

    statement = statement.order_by(ElectricityMapsCarbonIntensity.datetime_utc)

    results = session.exec(statement).all()
    return results


@router.post("/carbon-intensity/latest/")
def fetch_and_store_latest(
    zone: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_managed_session),
):
    try:
        data = electricitymaps_service.fetch_latest_data(zone)

        if not data:
            raise HTTPException(status_code=404, detail="No data returned from API")

        carbon_intensity_value = data.get("carbonIntensity")
        datetime_str = data.get("datetime")

        if not carbon_intensity_value or not datetime_str:
            raise HTTPException(status_code=500, detail="Invalid data format from API")

        dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))

        entry = ElectricityMapsCarbonIntensity(
            zone=zone,
            datetime_utc=dt,
            carbon_intensity=carbon_intensity_value,
            is_forecast=False,
        )

        session.merge(entry)
        session.commit()

        return {
            "message": "Latest data fetched and stored successfully",
            "zone": zone,
            "datetime": dt,
            "carbon_intensity": carbon_intensity_value,
        }

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch data from Electricity Maps: {str(e)}",
        )


@router.post("/carbon-intensity/forecast/")
def fetch_and_store_forecast(
    zone: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_managed_session),
):
    background_tasks.add_task(
        fetch_forecast_task,
        zone,
        session,
    )
    return {"message": "Forecast fetch job started in background"}


def fetch_forecast_task(zone: str, session: Session):
    try:
        data = electricitymaps_service.fetch_forecast_data(zone)

        if not data or "forecast" not in data:
            logging.warning(f"No forecast data available for zone {zone}")
            return

        forecast_list = data.get("forecast", [])
        stored_count = 0

        for forecast_point in forecast_list:
            carbon_intensity_value = forecast_point.get("carbonIntensity")
            datetime_str = forecast_point.get("datetime")

            if carbon_intensity_value and datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))

                entry = ElectricityMapsCarbonIntensity(
                    zone=zone,
                    datetime_utc=dt,
                    carbon_intensity=carbon_intensity_value,
                    is_forecast=True,
                )

                session.merge(entry)
                stored_count += 1

        session.commit()
        logging.info(f"Successfully stored {stored_count} forecast points for {zone}")

    except Exception as e:
        logging.error(f"Background forecast fetch failed: {e}")


@router.post("/carbon-intensity/history/")
def fetch_and_store_history(
    zone: str,
    start_time: datetime,
    end_time: datetime,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_managed_session),
):
    background_tasks.add_task(
        fetch_history_task,
        zone,
        start_time,
        end_time,
        session,
    )
    return {"message": "History fetch job started in background"}


def fetch_history_task(
    zone: str, start_time: datetime, end_time: datetime, session: Session
):
    try:
        data = electricitymaps_service.fetch_history_data(zone, start_time, end_time)

        if not data or "history" not in data:
            logging.warning(f"No historical data available for zone {zone}")
            return

        history_list = data.get("history", [])
        stored_count = 0

        for history_point in history_list:
            carbon_intensity_value = history_point.get("carbonIntensity")
            datetime_str = history_point.get("datetime")

            if carbon_intensity_value and datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))

                entry = ElectricityMapsCarbonIntensity(
                    zone=zone,
                    datetime_utc=dt,
                    carbon_intensity=carbon_intensity_value,
                    is_forecast=False,
                )

                session.merge(entry)
                stored_count += 1

        session.commit()
        logging.info(f"Successfully stored {stored_count} historical points for {zone}")

    except Exception as e:
        logging.error(f"Background history fetch failed: {e}")


# --------------------------
# Generic Proxy with Cache
# --------------------------

def _build_cache_key(request: Request, full_path: str, body: bytes) -> str:
    qs_items = sorted([f"{k}={v}" for k, v in request.query_params.multi_items()])
    qs = "&".join(qs_items)
    base = f"{request.method}:/"
    if full_path:
        base += full_path.lstrip("/")
    if qs:
        base += f"?{qs}"
    if request.method != "GET" and body:
        body_hash = hashlib.sha256(body).hexdigest()
        base += f"#body={body_hash}"
    return base



@router.api_route(
    "/{full_path:path}", methods=["GET"], description= "z.B.: full_path = v3/carbon-intensity/forecast?zone=FR ; full_path = v3/carbon-intensity/history?zone=FR ; full_path = v3/carbon-intensity/latest?zone=FR ")

async def proxy_any(
    full_path: str, request: Request, session: Session = Depends(get_managed_session)):
    
    ### Erstellt Cache_key für DB
    body = await request.body()
    cache_key = _build_cache_key(request, full_path, body)
    ###

    
    

    #### Suche in der Datenbank nach einem gültigen Cache-Eintrag
    now = datetime.now(timezone.utc)                # Hole die aktuelle UTC-Zeit für Cache-Vergleiche

    cached = session.exec(
            select(APICache)                        # Wähle APICache-Tabelle
            .where(APICache.cache_key == cache_key) # suche gleichen Cache-Key
            .where(APICache.expires_at > now)       # Ablaufdatum soll noch nicht erreicht sein
        ).first()                                   # Hole den ersten (und einzigen) Treffer
    ###

    ### Wenn ein gültiger Cache-Eintrag exestiert, gibt ihn aus
    if cached:                                                   
        return Response(                                # Gib die gecachte Response zurück
            content=cached.response_body,
            status_code=cached.status_code,
            media_type="application/json"             # JSON-Media-Type
    )
    ###

    ### Wenn ein gültiger Cache-Eintrag nicht exestiert
    headers = dict(request.headers)
    headers.pop("host", None)                           # Host: localhost:8000 -> Host: none
    headers.pop("accept-encoding", None)                #Wichtige Zeile, sonst latest gibt gzip (quatsch) zurück und wir können es nicht decodieren


    ### Mache Request an ElectricityMaps API
    api_key = os.environ.get("ELECTRICITYMAPS_API_KEY", "")      # Hole den API-Key aus den Umgebungsvariablen
    if api_key:                                                   # Falls ein API-Key vorhanden ist   
        headers["auth-token"] = api_key

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(                            # Führe den Request an die ElectricityMaps API aus   
            method=request.method,                              # mit der gleichen HTTP-Methode  
            url=f"{ELECTRICITYMAPS_BASE_URL}/{full_path}",      # an die Basis-URL + Pfad
            params=request.query_params,                        # mit den ursprünglichen Query-Parametern
            headers=headers,                                    # mit den angepassten Headers
            content=body,                                       # mit dem ursprünglichen Body-Content
            follow_redirects=True                               # folge automatisch Redirects
        )
    ###

    ### Suche nach gleichen Key mit abgelaufener Frist in DB und lösche ihn 
    old_cache = session.exec(
        select(APICache)
        .where(APICache.cache_key == cache_key)
    ).first()
 
    if old_cache:                                               # Falls ein alter Eintrag existiert
        session.delete(old_cache)                               # Lösche ihn aus der Datenbank  
    ###

    ### Erstelle neuen Cache-Eintrag in DB
    ttl_minutes = DEFAULT_TTL_MINUTES                           # Setze die TTL auf den Standardwert (Jeder Antrag wird derselbe Zeit gespeichert, kann danach indv. angepasst werden)

    cache_entry = APICache(
        cache_key=cache_key,                                    # mit dem berechneten Cache-Key
        response_body=resp.text ,                               # dem Response-Body als Text
        status_code=resp.status_code,
        expires_at=now + timedelta(minutes=ttl_minutes)         # und einem Ablaufdatum (jetzt + TTL in Minuten)
    )
    session.merge(cache_entry)                                
    session.commit()                                            # Speichere die Änderungen in der Datenbank
    
    ###


    return Response(content= resp.text, status_code=resp.status_code, media_type="application/json")

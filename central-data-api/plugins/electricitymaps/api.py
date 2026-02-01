import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
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
import urllib

from core.database import get_managed_session
from .service import ElectricityMapsService
from .models import (
    ElectricityMapsCarbonIntensity,
    ElectricityMapsCarbonIntensityCreate,
    ElectricityMapsCarbonIntensityPublic,
    APICache,
)

# ------------------------------------------------------------
# Konfiguration / Environment
# ------------------------------------------------------------
# Lädt .env aus dem Plugin-Verzeichnis (nicht aus Projekt-Root!)
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=dotenv_path)

# FastAPI Router: Alle Endpunkte in diesem File hängen unter /electricitymaps
router = APIRouter(prefix="/electricitymaps", tags=["electricitymaps"])

# ------------------------------------------------------------
# Proxy-Cache Konfiguration
# ------------------------------------------------------------
# Basis-URL der externen ElectricityMaps API (Default: public URL)
ELECTRICITYMAPS_BASE_URL = os.environ.get(
    "ELECTRICITYMAPS_BASE_URL", "https://api.electricitymap.org"
)

# Cache TTL in Minuten: Wie lange eine Proxy-Antwort in APICache gültig bleibt
DEFAULT_TTL_MINUTES = int(os.environ.get("ELECTRICITYMAPS_CACHE_TTL_MINUTES", "15"))

# ------------------------------------------------------------
# Service: Wrapper um ElectricityMaps Requests (latest/forecast/history)
# ------------------------------------------------------------
electricitymaps_service = ElectricityMapsService(
    api_key=os.environ.get("ELECTRICITYMAPS_API_KEY", "")
)


def startup():
    """
    Wird beim App-Startup aufgerufen (wenn ihr es registriert).
    Prüft, ob ElectricityMaps erreichbar ist / API Key funktioniert.
    """
    logging.info("Checking Electricity Maps API connection...")
    electricitymaps_service.check_connection()


@router.get("/")
def get_overview():
    """
    Kleine Übersicht, welche Endpunkte euer Plugin anbietet.
    (Hilfreich als human-readable landing page)
    """
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
            # Generic Proxy: Alles was nicht explizit oben steht, wird zur echten API weitergeleitet
            {
                "path": "/{any}/…",
                "method": "ANY",
                "description": "Proxy to ElectricityMaps API (cached)",
            },
        ],
    }


# ------------------------------------------------------------
# CRUD: Manuelles Speichern eines einzelnen Datenpunktes
# ------------------------------------------------------------
@router.post("/carbon-intensity/", response_model=ElectricityMapsCarbonIntensityPublic)
def create_carbon_intensity_entry(
    carbon_intensity: ElectricityMapsCarbonIntensityCreate,
    session: Session = Depends(get_managed_session),
):
    """
    Speichert einen Datenpunkt, den der Client schon fertig mitbringt.
    - Kein externer API Call
    - Gut für Tests/Imports/Manuelle Korrekturen
    """
    db_entry = ElectricityMapsCarbonIntensity.model_validate(carbon_intensity)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


# ------------------------------------------------------------
# CRUD: Lesen der gespeicherten Datenpunkte aus der DB
# ------------------------------------------------------------
@router.get("/carbon-intensity/", response_model=List[ElectricityMapsCarbonIntensityPublic])
def get_carbon_intensity(
    zone: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    is_forecast: Optional[bool] = None,
    session: Session = Depends(get_managed_session),
):
    """
    Liefert Zeitreihenpunkte aus eurer lokalen DB.
    - Filterbar nach Zeitraum
    - Filterbar nach is_forecast
    """
    statement = select(ElectricityMapsCarbonIntensity).where(
        ElectricityMapsCarbonIntensity.zone == zone
    )

    # Optionaler Startzeit-Filter
    if start_time:
        statement = statement.where(ElectricityMapsCarbonIntensity.datetime_utc >= start_time)

    # Optionaler Endzeit-Filter
    if end_time:
        statement = statement.where(ElectricityMapsCarbonIntensity.datetime_utc <= end_time)

    # Optionaler Forecast-Filter
    if is_forecast is not None:
        statement = statement.where(ElectricityMapsCarbonIntensity.is_forecast == is_forecast)

    # Sortiert nach Zeit – wichtig für Plot/Simulation
    statement = statement.order_by(ElectricityMapsCarbonIntensity.datetime_utc)

    results = session.exec(statement).all()
    return results


# ------------------------------------------------------------
# Fetch+Store: neuesten Wert live von ElectricityMaps holen
# ------------------------------------------------------------
@router.post("/carbon-intensity/latest/")
def fetch_and_store_latest(
    zone: str,
    background_tasks: BackgroundTasks, 
    session: Session = Depends(get_managed_session),
):
    """
    Holt den neuesten Wert ("latest") von ElectricityMaps und speichert ihn in DB.
    Unterschied zu POST /carbon-intensity/:
    - Hier holt ihr Daten selbst von der externen API.
    """
    try:
        data = electricitymaps_service.fetch_latest_data(zone)

        if not data:
            raise HTTPException(status_code=404, detail="No data returned from API")

        carbon_intensity_value = data.get("carbonIntensity")
        datetime_str = data.get("datetime")

        
        if not carbon_intensity_value or not datetime_str:
            raise HTTPException(status_code=500, detail="Invalid data format from API")

        # "Z" -> UTC +00:00
        dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))

        # is_forecast=False: "historisch/aktuell"
        entry = ElectricityMapsCarbonIntensity(
            zone=zone,
            datetime_utc=dt,
            carbon_intensity=carbon_intensity_value,
            is_forecast=False,
        )

        # merge() ist eine Upsert-ähnliche Operation (setzt aber echte DB-Constraints voraus)
        session.merge(entry)
        session.commit()

        return {
            "message": "Latest data fetched and stored successfully",
            "zone": zone,
            "datetime": dt,
            "carbon_intensity": carbon_intensity_value,
        }

    except Exception as e:
        # 502 = Bad Gateway: Externe API konnte nicht korrekt erreicht/ausgewertet werden
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch data from Electricity Maps: {str(e)}",
        )


# ------------------------------------------------------------
# Fetch+Store Forecast: Background Task starten
# ------------------------------------------------------------
@router.post("/carbon-intensity/forecast/")
def fetch_and_store_forecast(
    zone: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_managed_session),
):
    """
    Startet einen Hintergrund-Job, der Forecast-Daten holt und speichert.
    Vorteil: Request antwortet sofort.
    Hinweis: Session in BackgroundTasks weiterzugeben ist oft riskant,
    weil die Session evtl. nach Request-Ende geschlossen wird.
    """
    background_tasks.add_task(fetch_forecast_task, zone, session)
    return {"message": "Forecast fetch job started in background"}


def fetch_forecast_task(zone: str, session: Session):
    """
    Holt Forecast-Daten von ElectricityMaps und speichert sie in DB.
    """
    try:
        data = electricitymaps_service.fetch_forecast_data(zone)

        # API muss forecast-Liste liefern
        if not data or "forecast" not in data:
            logging.warning(f"No forecast data available for zone {zone}")
            return

        forecast_list = data.get("forecast", [])
        stored_count = 0

        for forecast_point in forecast_list:
            carbon_intensity_value = forecast_point.get("carbonIntensity")
            datetime_str = forecast_point.get("datetime")

            # Nur speichern, wenn beide vorhanden sind
            if carbon_intensity_value and datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))

                entry = ElectricityMapsCarbonIntensity(
                    zone=zone,
                    datetime_utc=dt,
                    carbon_intensity=carbon_intensity_value,
                    is_forecast=True,  # Forecast kennzeichnen
                )

                session.merge(entry)
                stored_count += 1

        # Einmal committen (effizienter als pro Punkt)
        session.commit()
        logging.info(f"Successfully stored {stored_count} forecast points for {zone}")

    except Exception as e:
        logging.error(f"Background forecast fetch failed: {e}")


# ------------------------------------------------------------
# Fetch+Store History: Background Task starten
# ------------------------------------------------------------
@router.post("/carbon-intensity/history/")
def fetch_and_store_history(
    zone: str,
    start_time: datetime,
    end_time: datetime,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_managed_session),
):
    """
    Startet einen Hintergrund-Job, der historische Daten für einen Zeitraum holt.
    Hinweis: Auch hier ist Session-im-BackgroundTask potentiell riskant.
    """
    background_tasks.add_task(fetch_history_task, zone, start_time, end_time, session)
    return {"message": "History fetch job started in background"}


def fetch_history_task(zone: str, start_time: datetime, end_time: datetime, session: Session):
    """
    Holt historische Daten von ElectricityMaps und speichert sie in DB.
    """
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


# ------------------------------------------------------------
# Generic Proxy with Cache
# ------------------------------------------------------------
def _build_cache_key(request: Request, full_path: str, body: bytes) -> str:
    """
    Baut einen stabilen Cache-Key für den Proxy.
    - Sortierte Query-Params, damit Reihenfolge egal ist
    - Bei non-GET: Body-Hash anhängen, damit unterschiedliche Payloads getrennt cached werden
    """
    qs_items = sorted([f"{k}={v}" for k, v in request.query_params.multi_items()])
    qs = "&".join(qs_items)

    base = f"{request.method}:/"
    if full_path:
        base += full_path.lstrip("/")

    if qs:
        base += f"?{qs}"

    # Für non-GET unterscheiden wir Requests über den Body-Hash
    if request.method != "GET" and body:
        body_hash = hashlib.sha256(body).hexdigest()
        base += f"#body={body_hash}"

    return base


# ------------------------------------------------------------
# Proxy Cache Helper Functions
# ------------------------------------------------------------
def _get_cached_response(session: Session, cache_key: str) -> Optional[APICache]:
    """
    Sucht einen gültigen Cache-Eintrag (noch nicht abgelaufen).
    """
    now = datetime.now(timezone.utc)
    cached = session.exec(
        select(APICache)
        .where(APICache.cache_key == cache_key)
        .where(APICache.expires_at > now)
    ).first()
    return cached


def _prepare_headers(request: Request) -> dict:
    """
    Bereitet HTTP-Header für den externen Request vor.
    - entfernt 'host' (soll nicht weitergegeben werden)
    - entfernt 'accept-encoding' (damit wir kontrollieren, ob komprimiert wird)
    - fügt 'auth-token' hinzu (ElectricityMaps API Key)
    """
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("accept-encoding", None)

    api_key = os.environ.get("ELECTRICITYMAPS_API_KEY", "")
    if api_key:
        headers["auth-token"] = api_key

    return headers


async def _fetch_from_api(full_path: str, request: Request, headers: dict, body: bytes) -> httpx.Response:
    """
    Führt den eigentlichen Request an die ElectricityMaps API aus.
    Wichtig: Hier wird full_path direkt an die Base-URL gehängt.
    """
    full_url = f"{ELECTRICITYMAPS_BASE_URL}/{full_path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method=request.method,
            url=full_url,
            headers=headers,
            content=body,
            follow_redirects=True,
        )
    return resp


def _save_to_cache(
    session: Session,
    cache_key: str,
    response_text: str,
    status_code: int,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> None:
    """
    Speichert die Response im Cache:
    - alten Eintrag löschen
    - neuen mit expires_at = now + TTL speichern
    """
    now = datetime.now(timezone.utc)

    # Falls bereits ein Cache-Eintrag existiert, entfernen
    old_cache = session.exec(select(APICache).where(APICache.cache_key == cache_key)).first()
    if old_cache:
        session.delete(old_cache)

    # Neuen Cache schreiben
    cache_entry = APICache(
        cache_key=cache_key,
        response_body=response_text,
        status_code=status_code,
        expires_at=now + timedelta(minutes=ttl_minutes),
    )

    session.merge(cache_entry)
    session.commit()


# ------------------------------------------------------------
# Proxy Route: Catch-all, leitet beliebige Paths an ElectricityMaps weiter
# ------------------------------------------------------------
@router.api_route(
    "/{full_path:path}",
    methods=["GET"], 
    description="z.B.: full_path = v3/carbon-intensity/forecast?zone=FR",
)
async def proxy_any(full_path: str, request: Request, session: Session = Depends(get_managed_session)) -> Response:
    """
    Proxy-Endpoint:
    - nimmt beliebige Pfade an
    - cached Responses in DB (APICache)
    - gibt cached response zurück, wenn TTL noch gültig ist
    """

    # 1) URL dekodieren, falls %2F etc. enthalten sind
    full_path = urllib.parse.unquote(full_path)

    # 2) Body lesen (für Cache-Key; bei GET meist leer)
    body = await request.body()

    # 3) Cache-Key erstellen
    cache_key = _build_cache_key(request, full_path, body)

    # 4) Cache lookup
    cached = _get_cached_response(session, cache_key)
    if cached:
        return Response(
            content=cached.response_body,
            status_code=cached.status_code,
            media_type="application/json",
        )

    # 5) Request-Header vorbereiten (inkl. auth-token)
    headers = _prepare_headers(request)

    # 6) Externen API-Call durchführen
    resp = await _fetch_from_api(full_path, request, headers, body)

    # 7) Fehler (nicht-200) nicht cachen, damit kein "kaputter Cache" entsteht
    if resp.status_code != 200:
        return Response(content=resp.text, status_code=resp.status_code, media_type="application/json")

    # 8) Erfolgreiche Response in Cache speichern
    _save_to_cache(session, cache_key, resp.text, resp.status_code)

    # 9) Antwort an Client zurückgeben
    return Response(content=resp.text, status_code=resp.status_code, media_type="application/json")

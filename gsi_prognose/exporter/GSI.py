import time
import requests  # HTTP-Bibliothek zum Abrufen von Daten von APIs
import datetime
from prometheus_client import start_http_server, Gauge  # Prometheus-Client: HTTP-Server starten und Gauge-Metriken erstellen

# from dotenv import load_dotenv  # Lädt Umgebungsvariablen aus .env-Datei
# import os  # Betriebssystem-Interaktion (Umgebungsvariablen lesen)

# load_dotenv()  # Lädt Umgebungsvariablen aus der .env-Datei in das aktuelle Environment

PROMETHEUS_PORT = 8000  # Port-Nummer, auf dem der Prometheus HTTP-Server laufen soll
#ZIP_CODE = os.getenv("ZIP_CODE", "10117")  # Postleitzahl aus Umgebungsvariable lesen, falls nicht vorhanden Standardwert "10117" verwenden

ZIP_CODE = 10117
REQUEST_URL = f"https://api.corrently.io/v2.0/gsi/prediction?zip={ZIP_CODE}"  # API-URL mit Postleitzahl als Parameter zusammenstellen

# Prometheus Gauge für GSI-Werte
gsi_gauge = Gauge(  # Erstellt eine Gauge-Metrik (kann hoch/runter gehen)
    'gsi_value',  # Metrik-Name in Prometheus
    'Green Power Index (GSI) value',  # Beschreibung der Metrik
    ['zip', 'timestamp']  # Labels: zip (Postleitzahl) und timestamp (Zeitstempel) für verschiedene Metriken
)

# Gauge für den aktuellen GSI-Wert (nächste Stunde)
gsi_current_gauge = Gauge(  # Erstellt eine Gauge-Metrik für den aktuellen Wert
    'gsi_current',  # Metrik-Name in Prometheus
    'Current Green Power Index (GSI) value',  # Beschreibung: aktueller GSI-Wert
    ['zip']  # Label: nur Postleitzahl, da es nur einen aktuellen Wert gibt
)

#  Gauge für GSI-Vorhersagen mit Stunden-Ahead
gsi_forecast_gauge = Gauge(  # Erstellt eine Gauge-Metrik für Vorhersagen
    'gsi_forecast',  # Metrik-Name in Prometheus
    'GSI forecast value',  # Beschreibung: GSI-Vorhersagewert
    ['zip', 'hours_ahead']  # Labels: zip (Postleitzahl) und hours_ahead (Stunden in die Zukunft)
)

# Cache für die letzten Daten
forecast_cache = []  # Globale Liste zum Speichern der zuletzt abgerufenen Forecast-Daten


def fetch_gsi_data():
    """Ruft GSI-Daten von der API ab"""
    global forecast_cache  # Verwendet die globale Variable forecast_cache

    try:  # Fehlerbehandlung: versuche den folgenden Code auszuführen
        response = requests.get(REQUEST_URL, timeout=10)  # HTTP GET-Request an die API senden, Timeout nach 10 Sekunden

        if response.status_code == 200:  # Prüfe ob die Anfrage erfolgreich war (HTTP 200 = OK)
            data = response.json()  # Konvertiere die JSON-Antwort in ein Python-Dictionary
            forecast_cache = []  # Leere den Cache, um neue Daten zu speichern

            current_time = datetime.datetime.now(datetime.UTC)  # Aktuelle Zeit in UTC abrufen

            # Verarbeite jeden Forecast-Eintrag
            for entry in data.get('forecast', []):  # Iteriere über alle Einträge im 'forecast'-Array (falls nicht vorhanden: leere Liste)

                gsi = entry.get("gsi")  # Hole den GSI-Wert aus dem Eintrag (falls nicht vorhanden: None)
                timestamp_in_seconds = entry.get('epochtime')  # Hole den Unix-Timestamp aus dem Eintrag (falls nicht vorhanden: None)

                if gsi is not None and timestamp_in_seconds is not None:  # Prüfe ob beide Werte vorhanden sind

                    # UTC convert to Date and Time
                    normal_date = datetime.datetime.fromtimestamp(  # Konvertiere Unix-Timestamp zu datetime-Objekt
                        timestamp_in_seconds,  # Unix-Timestamp in Sekunden
                        datetime.UTC  # Zeitzone: UTC
                    )

                    # Berechne Stunden-Ahead
                    time_diff = normal_date - current_time  # Berechne Zeitdifferenz zwischen Forecast-Zeit und jetzt
                    hours_ahead = int(time_diff.total_seconds() / 3600)  # Konvertiere Sekunden zu Stunden (3600 Sekunden = 1 Stunde) und runde ab

                    forecast_cache.append({  # Füge verarbeitete Daten zum Cache hinzu
                        'gsi': gsi,  # GSI-Wert
                        'timestamp': normal_date,  # Konvertiertes Datum
                        'epochtime': timestamp_in_seconds,  # Original Unix-Timestamp
                        'hours_ahead': hours_ahead  # Berechnete Stunden in die Zukunft
                    })

            print(f"Fetched {len(forecast_cache)} GSI forecast entries")  # Ausgabe: Anzahl der abgerufenen Forecast-Einträge
            return True  # Rückgabe: Erfolg
        else:  # Falls HTTP-Status nicht 200 ist
            print(f"Fehler beim Abrufen der Daten: Status Code {response.status_code}")  # Fehlermeldung mit Status-Code ausgeben
            return False  # Rückgabe: Fehler

    except Exception as e:  # Fange alle Exceptions (Fehler) ab
        print(f"Fehler beim Abrufen der GSI-Daten: {e}")  # Fehlermeldung mit Exception-Details ausgeben
        return False  # Rückgabe: Fehler


def update_metrics():
    """Aktualisiert die Prometheus-Metriken mit den GSI-Daten"""
    global forecast_cache  # Verwendet die globale Variable forecast_cache

    if not forecast_cache:  # Prüfe ob der Cache leer ist
        print("Keine GSI-Daten im Cache verfügbar")  # Fehlermeldung ausgeben
        return  # Funktion beenden, keine Metriken zu aktualisieren

    current_time = datetime.datetime.now(datetime.UTC)  # Aktuelle Zeit in UTC abrufen
    current_hour = current_time.replace(minute=0, second=0, microsecond=0)  # Runde auf volle Stunde ab (Minuten, Sekunden, Mikrosekunden auf 0 setzen)

    # Finde den aktuellen GSI-Wert (nächste Stunde)
    current_gsi = None  # Initialisiere Variable für aktuellen GSI-Wert
    min_time_diff = float('inf')  # Initialisiere mit unendlich, um den kleinsten Zeitunterschied zu finden

    for entry in forecast_cache:  # Iteriere über alle Einträge im Cache
        entry_time = entry['timestamp']  # Hole den Zeitstempel des Eintrags
        entry_hour = entry_time.replace(minute=0, second=0, microsecond=0)  # Runde auf volle Stunde ab

        # Setze Metrik für jeden Forecast-Eintrag
        gsi_gauge.labels(  # Setze Metrik mit Labels
            zip=ZIP_CODE,  # Label: Postleitzahl
            timestamp=entry_time.isoformat()  # Label: Zeitstempel im ISO-Format (z.B. "2024-01-01T12:00:00")
        ).set(entry['gsi'])  # Setze den GSI-Wert für diese Metrik

        # Finde den nächsten GSI-Wert (aktuell oder nächste Stunde)
        time_diff = (entry_hour - current_hour).total_seconds()  # Berechne Zeitdifferenz in Sekunden zwischen Forecast-Stunde und aktueller Stunde

        if 0 <= time_diff < min_time_diff:  # Prüfe ob der Eintrag in der Zukunft liegt und näher ist als bisherige Einträge
            min_time_diff = time_diff  # Aktualisiere den kleinsten Zeitunterschied
            current_gsi = entry['gsi']  # Speichere den GSI-Wert als aktuellen Wert

        # Setze Forecast-Metriken für bestimmte Stunden-Ahead (1h, 2h, 6h, 12h, 24h)
        hours_ahead = entry['hours_ahead']  # Hole die Stunden-in-die-Zukunft aus dem Eintrag
        if hours_ahead in [1, 2, 6, 12, 24]:  # Prüfe ob es eine der interessanten Vorhersagezeiten ist
            gsi_forecast_gauge.labels(  # Setze Forecast-Metrik mit Labels
                zip=ZIP_CODE,  # Label: Postleitzahl
                hours_ahead=hours_ahead  # Label: Stunden in die Zukunft
            ).set(entry['gsi'])  # Setze den GSI-Wert für diese Vorhersage

    # Setze aktuellen GSI-Wert
    if current_gsi is not None:  # Prüfe ob ein aktueller GSI-Wert gefunden wurde
        gsi_current_gauge.labels(zip=ZIP_CODE).set(current_gsi)  # Setze die aktuelle GSI-Metrik mit Postleitzahl-Label
        print(f"[{ZIP_CODE}] Aktueller GSI-Wert: {current_gsi:.2f}")  # Ausgabe: aktueller GSI-Wert mit 2 Dezimalstellen
    else:  # Falls kein aktueller Wert gefunden wurde
        print(f"[{ZIP_CODE}] Kein aktueller GSI-Wert gefunden")  # Fehlermeldung ausgeben


if __name__ == '__main__':  # Prüfe ob das Skript direkt ausgeführt wird (nicht als Modul importiert)
    # Initialer Datenabruf
    fetch_gsi_data()  # Rufe einmalig GSI-Daten ab, bevor der Server startet

    # Starte Prometheus HTTP-Server
    start_http_server(PROMETHEUS_PORT)  # Starte HTTP-Server auf dem konfigurierten Port, der Metriken unter /metrics bereitstellt
    print(f"Prometheus Exporter läuft auf Port {PROMETHEUS_PORT}...")  # Bestätigungsmeldung: Server läuft
    print(f"Metriken verfügbar unter: http://localhost:{PROMETHEUS_PORT}/metrics")  # Hinweis: URL für Metriken-Endpoint

    # Hauptschleife: Aktualisiere Metriken alle 15 Minuten (900 Sekunden)
    while True:  # Endlosschleife
        # Aktualisiere Daten alle 15 Minuten
        fetch_gsi_data()  # Rufe neue GSI-Daten von der API ab
        update_metrics()  # Aktualisiere alle Prometheus-Metriken mit den neuen Daten
        time.sleep(900)  # Warte 900 Sekunden (15 Minuten) bevor die Schleife erneut ausgeführt wird
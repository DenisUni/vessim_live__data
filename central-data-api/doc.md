

# Inhaltsverzeichnis

## 1. Überblick
- [Wie das Central Data API funktioniert](#wie-das-central-data-api-funktioniert)
- [Kernarchitektur](#kernarchitektur)
- [Datenfluss am Beispiel ENTSO-E](#datenfluss-am-beispiel-entso-e)
- [Projektstruktur](#project-structure)

## 2. Core-Komponenten

### 2.1 mаin.py
- [`discover_and_load_plugins()`](#zusammenfassung-der-mainpy)
- [`app_lifespan()`](#zusammenfassung-der-mainpy)
- [`root()` und `health_check()`](#zusammenfassung-der-mainpy)
- [`check_and_install_dependencies()`](#zusammenfassung-der-mainpy)

### 2.2 install_plugins.py
- [`find_plugin_requirements()`](#zusammenfassung-der-install_pluginspy)
- [`parse_requirements_file()`](#zusammenfassung-der-install_pluginspy)
- [`deduplicate_requirements()`](#zusammenfassung-der-install_pluginspy)
- [`check_existing_installation()`](#zusammenfassung-der-install_pluginspy)
- [`install_requirements()`](#zusammenfassung-der-install_pluginspy)
- [`run()`](#zusammenfassung-der-install_pluginspy)

### 2.3 core/database.py
- [`engine`](#zusammenfassung-der-databasepy)
- [`TimeStampedModel`](#zusammenfassung-der-databasepy)
- [`get_session_context()`](#zusammenfassung-der-databasepy)
- [`get_managed_session()`](#zusammenfassung-der-databasepy)
- [`create_all_tables()`](#zusammenfassung-der-databasepy)
- [`dispose_engine()`](#zusammenfassung-der-databasepy)

### 2.4 core/config.py
- [`Settings`-Klasse](#zusammenfassung-der-configpy)
- [`settings`-Instanz](#zusammenfassung-der-configpy)

## 3. ENTSO-E Plugin

### 3.1 Plugin-Übersicht
- [Plugin-Struktur](#plug-in-entsoe)
- [`__init__.py`](#zusammenfassung-der-__init__py)

### 3.2 models.py
- [`EntsoePriceBase`](#zusammenfassung-der-modelspy)
- [`EntsoePrice`](#zusammenfassung-der-modelspy)
- [`EntsoePriceCreate`](#zusammenfassung-der-modelspy)
- [`EntsoePricePublic`](#zusammenfassung-der-modelspy)

### 3.3 api.py
- [`startup()`](#zusammenfassung-der-apipy)
- [`get_overview()`](#zusammenfassung-der-apipy)
- [`create_price_entry()`](#zusammenfassung-der-apipy)
- [`get_prices()`](#zusammenfassung-der-apipy)
- [`fetch_and_store_range()`](#zusammenfassung-der-apipy)
- [`fetch_range_task()`](#zusammenfassung-der-apipy)
- [`health_check()`](#zusammenfassung-der-apipy)

### 3.4 service.py
- [`EntsoeService.__init__()`](#zusammenfassung-der-servicepy)
- [`check_connection()`](#zusammenfassung-der-servicepy)
- [`fetch_price_data()`](#zusammenfassung-der-servicepy)
- [`fill_missing_timestamps()`](#zusammenfassung-der-servicepy)




# Wie das Central Data API funktioniert

Das  **Central Data API**  ist eine modulare FastAPI-Anwendung, die als zentrale Datenschnittstelle für das Vessim-Projekt dient. Das System basiert auf einer  **Plugin-Architektur**, die es ermöglicht, verschiedene Datenquellen (wie ENTSO-E, ElectricityMaps) dynamisch zu integrieren ohne den Core-Code zu ändern.

### Kernarchitektur:

1.  **Main Application**  (main.py)
    
    -   Startet FastAPI-Server
    -   Erkennt und lädt automatisch alle Plugins aus dem  `plugins`-Verzeichnis
    -   Registriert Router, Datenbank-Modelle und Startup-Funktionen jedes Plugins
    -   Verwaltet Anwendungs-Lifecycle (Startup/Shutdown)
2.  **Plugin-System**
    
    -   Jedes Plugin ist ein eigenständiges Modul (z.B.  `plugins/entsoe/`)
    -   Exportiert standardisierte Komponenten:  router,  models,  startup
    -   Plugins können unabhängig entwickelt, getestet und deployed werden
3.  **Datenbankschicht**  (database.py)
    
    -   SQLModel-basierte ORM mit SQLite (oder PostgreSQL)
    -   Automatische Tabellenerstellung aus Plugin-Modellen
    -   Session-Management für sichere Transaktionen
4.  **Konfiguration**  (config.py)
    
    -   Zentrale Settings via Umgebungsvariablen und  `.env`-Dateien
    -   Pydantic-basierte Validierung

### Datenfluss am Beispiel ENTSO-E:

1.  **Request:**  Client ruft  /api/v1/entsoe/prices/?zone=DE_LU&start_time=...  auf
2.  **Cache-Check:**  API prüft lokale Datenbank auf vorhandene Daten
3.  **API-Fetch:**  Bei fehlenden Daten →  `EntsoeService`  lädt von ENTSO-E API
4.  **Datenaufbereitung:**  `fill_missing_timestamps()`  vervollständigt Zeitreihen
5.  **Speicherung:**  Neue Daten werden im Cache gespeichert
6.  **Response:**  Vollständige Preisdaten werden an Client zurückgegeben

**Vorteil:**  Intelligentes Caching reduziert API-Aufrufe, während neue Plugins einfach hinzugefügt werden können ohne Änderungen am Hauptsystem.

# Project structure
```
data/
├── main.py                      # main-app, collects als routers from plugins
├── core/
│   ├── database.py              # joined db-engine & base-models
│   └── config.py                # configuration
├── plugins/                     # plugin
│   ├── __init__.py
│   ├── entsoe/                  # entso-e plugin
│   │   ├── __init__.py          # defines plugin-specific router, models and startup for cennecting to main.py
│   │   ├── models.py            # plugin-specific tables for db
│   │   ├── api.py               # plugin-specific api endpoints
│   │   ├── service.py    		 # main logic
│   │   └── requierements.txt    # plugin-specific requierements
└── requirements.txt
```

## Zusammenfassung der  main.py

**Hauptfunktion:**  Diese Datei ist der Einstiegspunkt einer FastAPI-Anwendung mit einem dynamischen Plugin-System. Sie lädt automatisch Plugins aus dem  `plugins`-Verzeichnis und registriert deren API-Routen, Datenbank-Modelle und Startup-Funktionen.

### Wichtige Funktionen:

1.  **discover_and_load_plugins()** 
    
    -   Durchsucht automatisch das  `plugins`-Verzeichnis
    -   Lädt alle gefundenen Plugin-Pakete dynamisch
    -   Sammelt Router, Datenbank-Modelle und Startup-Funktionen aus jedem Plugin
    -   Isoliert Fehler (ein fehlerhaftes Plugin stoppt nicht die gesamte App)
2.  **app_lifespan()** 
    
    -   Verwaltet den Lebenszyklus der Anwendung
    -   **Beim Start:**  Lädt Plugins, erstellt Datenbanktabellen, registriert Router und führt Plugin-Startups aus
    -   **Beim Herunterfahren:**  Bereinigt Ressourcen und schließt die Datenbank
3.  **root()**  und **health_check()** 
    
    -   Einfache API-Endpunkte zum Testen der Anwendung
    -   Root zeigt App-Status, Health-Check für Monitoring
4.  **check_and_install_dependencies()** 
    
    -   Prüft Plugin-Abhängigkeiten beim Start
    -   Nutzt  install_plugins.py  zur Verwaltung
5.  **`__main__`  Block** 
    
    -   Startet den Uvicorn-Server mit Konfiguration aus Settings
    -   Aktiviert Debug-Modus und Hot-Reload falls konfiguriert

**Architektur:**  Plugin-basierte Modularität ermöglicht einfaches Hinzufügen neuer Funktionen ohne Code-Änderungen in der main.py.

---
## Zusammenfassung der  install_plugins.py

**Hauptfunktion:**  Automatische Verwaltung und Installation von Plugin-Abhängigkeiten. Diese Datei durchsucht alle Plugins nach  requirements.txt  Dateien, dedupliziert Abhängigkeiten und installiert fehlende Python-Pakete.

### Wichtige Funktionen:

1.  **__init__()**  
    
    -   Initialisiert den Installer mit Basis-Pfad und Dry-Run-Modus
    -   Sammelt System-Informationen (Python-Version, Plattform, etc.)
2.  **find_plugin_requirements()** 
    
    -   Durchsucht das  `plugins`-Verzeichnis nach  requirements.txt  Dateien
    -   Ignoriert versteckte Ordner (beginnend mit  _  oder  `.`)
    -   Gibt Dictionary mit Plugin-Name → Requirements-Datei zurück
3.  **parse_requirements_file()**  
    
    -   Liest und parst Requirements-Dateien
    -   Filtert problematische Pakete (z.B.  `pkg-resources`, gepinnte  `setuptools`)
    -   Entfernt Kommentare und leere Zeilen
4.  **deduplicate_requirements()** 
    
    -   Entfernt doppelte Dependencies über alle Plugins hinweg
    -   Extrahiert Basis-Paketnamen (ohne Versionsangaben)
    -   Erkennt potenzielle Versionskonflikte
5.  **check_existing_installation()**
    
    -   Prüft welche Pakete bereits installiert sind
    -   Nutzt  importlib  statt veralteter  `pkg_resources`
    -   Unterscheidet zwischen Standard-Library und externen Paketen
6.  **install_requirements()**  
    
    -   Installiert fehlende Pakete via  `pip`
    -   Erstellt temporäre Requirements-Datei
    -   Führt Installation mit Timeout (5 Minuten) aus
    -   Umfassendes Error-Handling und Logging
7.  **run()** 
    
    -   Hauptausführungsmethode, die alle Schritte orchestriert:
        1.  Requirements finden
        2.  Parsen und deduplizieren
        3.  Installationsstatus prüfen
        4.  Fehlende Pakete installieren
    -   Gibt detailliertes Feedback über jeden Schritt
8.  **main()**  
    
    -   CLI-Interface mit Argumenten:
        -   --dry-run: Zeigt nur an, was installiert würde
        -   --verbose: Aktiviert Debug-Logging

**Besonderheiten:**  Robuste Fehlerbehandlung, filtert problematische Pakete wie  `pkg-resources`, unterstützt verschiedene Import-Namen-Konventionen.

---
## Zusammenfassung der  database.py

**Hauptfunktion:**  Zentrale Verwaltung der Datenbankverbindung und Session-Handling für die Anwendung. Stellt einen SQLModel-Engine und wiederverwendbare Session-Management-Funktionen bereit.

### Wichtige Komponenten:

1.  **engine**  
    
    -   Globales SQLModel-Engine-Objekt
    -   Erstellt mit  DATABASE_URL  aus den Settings
    -   Echo-Modus aktiviert für SQL-Logging
2.  **TimeStampedModel** 
    
    -   Basis-Klasse für alle Datenbank-Tabellen
    -   Fügt automatisch ein  timestamp-Feld hinzu
    -   Setzt UTC-Zeitstempel beim Erstellen neuer Einträge
    -   Feld ist indexiert für schnellere Abfragen
3.  **get_session_context()** 
    
    -   Context Manager für manuelle Session-Nutzung
    -   Verwendung:  with get_session_context() as session: ...
    -   Führt automatisch Commit bei Erfolg aus
    -   Rollback bei Fehlern, schließt Session immer
4.  **get_managed_session()**  
    
    -   FastAPI Dependency für API-Endpunkte
    -   Generator-Funktion für automatisches Session-Management
    -   Verwendet in Route-Funktionen als Dependency Injection
    -   Identische Commit/Rollback-Logik wie Context Manager
5.  **create_all_tables()** 
    
    -   Erstellt alle Tabellen in der Datenbank
    -   Basiert auf SQLModel-Metadaten aller definierten Modelle
    -   Wird beim App-Start in  main.py  aufgerufen
6.  **dispose_engine()**  
    
    -   Beendet die Engine und schließt alle Verbindungen
    -   Leert den Connection Pool
    -   Wird beim App-Shutdown aufgerufen für sauberes Cleanup

**Architektur:**  Zentralisierte Datenbank-Konfiguration ermöglicht einfache Wiederverwendung von Sessions und konsistentes Transaction-Management über die gesamte Anwendung.

## Zusammenfassung der  config.py

**Hauptfunktion:**  Zentrale Konfigurationsverwaltung der Anwendung. Lädt Einstellungen aus Umgebungsvariablen und  `.env`-Dateien mittels Pydantic Settings.

### Wichtige Komponenten:

1.  **Settings-Klasse**  
    
    -   Pydantic BaseSettings für typsichere Konfiguration
    -   Definiert alle Anwendungseinstellungen mit Default-Werten
    -   Lädt automatisch Werte aus  `.env`-Datei und Environment Variables
2.  **App & API Configuration**
    
    -   APP_NAME: Name der Anwendung ("Central Data API")
    -   APP_VERSION: Versionsnummer (0.1.0)
    -   API_V1_STR: API-Prefix (/api/v1)
    -   DEBUG: Debug-Modus (Standard: False)
3.  **Server Configuration**  
    
    -   HOST: Server-Adresse (Standard: 0.0.0.0 = alle Interfaces)
    -   PORT: Server-Port (Standard: 8000)
4.  **Database Configuration**  
    
    -   DATABASE_URL: Datenbankverbindung
    -   Standard: SQLite (`sqlite:///db.sqlite`)
    -   Kommentar zeigt PostgreSQL-Beispiel
5.  **Config-Klasse** 
    
    -   env_file = ".env": Lädt Variablen aus .env-Datei
    -   case_sensitive = False: Groß-/Kleinschreibung wird ignoriert
    -   env_file_encoding = "utf-8": UTF-8 Encoding
    -   extra = "allow": Erlaubt zusätzliche, nicht definierte Felder
6.  **settings-Instanz** 
    
    -   Globales Singleton-Objekt mit allen Konfigurationswerten
    -   Wird überall in der Anwendung importiert und verwendet

**Verwendung:**  Andere Module importieren  settings  und greifen auf Konfigurationswerte zu (z.B.  settings.DATABASE_URL,  settings.DEBUG).

# Plug-In Entsoe

## Zusammenfassung der  __init__.py

**Hauptfunktion:**  Plugin-Initialisierungsdatei, die das Entsoe-Plugin für das automatische Discovery-System in  main.py  registriert.

### Aufgaben:

1.  **Import der Plugin-Komponenten**  
    
    -   router: FastAPI Router mit API-Endpunkten aus  api.py
    -   startup: Initialisierungsfunktion für Plugin-Start
    -   EntsoePrice: Datenbank-Modell für Entsoe-Preisdaten
2.  **Plugin-Exports**  
    
    -   Exportiert drei wichtige Variablen, die von  discover_and_load_plugins()  gesucht werden:
        -   **router**: API-Router wird automatisch unter  /api/v1  registriert
        -   **models**: Liste von SQLModel-Klassen → Datenbanktabellen werden automatisch erstellt
        -   **startup**: Funktion wird beim App-Start ausgeführt (z.B. API-Key-Validierung)

**Konvention:**  Diese standardisierte Struktur ermöglicht das Plugin-System. Jedes Plugin folgt diesem Pattern, sodass  main.py  sie automatisch erkennen und laden kann ohne Code-Änderungen in der Hauptanwendung.

## Zusammenfassung der  models.py

**Hauptfunktion:**  Definiert Datenmodelle für ENTSO-E Strompreisdaten. Verwendet SQLModel für einheitliche Datenbank- und API-Validierung.

### Modellklassen:

1.  **`EntsoePriceBase`**  
    
    -   Basis-Modell mit gemeinsamen Feldern für alle anderen Modelle
    -   **Felder:**
        -   `zone`: Handelszone (z.B. "DE_LU" für Deutschland/Luxemburg), indexiert
        -   `datetime_utc`: Zeitstempel des Preisintervalls in UTC, indexiert
        -   `price_eur_per_mwh`: Day-Ahead Strompreis in EUR/MWh
        -   `resolution_minutes`: Zeitauflösung (Standard: 15 Minuten)
2.  **EntsoePrice**  
    
    -   **Datenbank-Tabellenmodell**  (`table=True`)
    -   Erbt von  `EntsoePriceBase`
    -   **Zusätzliches Feld:**
        -   `id`: Primary Key (auto-increment)
    -   **Unique Constraint:**  Verhindert doppelte Einträge für gleiche Zone + Zeitpunkt
    -   Wird automatisch als Tabelle erstellt von  database.py
3.  **`EntsoePriceCreate`**  
    
    -   **API-Input-Modell**  für POST-Requests
    -   Identisch mit  `EntsoePriceBase`  (kein  `id`  erforderlich beim Erstellen)
    -   Validiert eingehende Daten vor Speicherung
4.  **`EntsoePricePublic`**  
    
    -   **API-Response-Modell**  für GET-Requests
    -   Erbt alle Felder von  `EntsoePriceBase`  +  `id`
    -   Wird zurückgegeben an API-Clients

**Design-Pattern:**  Trennung von Datenbankmodell, Input- und Output-Modellen ermöglicht klare API-Grenzen und verhindert unerwünschte Feldmanipulationen (z.B.  `id`  kann nicht bei Erstellung gesetzt werden).

## Zusammenfassung der  api.py

**Hauptfunktion:**  FastAPI Router für das ENTSO-E Plugin. Stellt API-Endpunkte bereit, um Strompreisdaten abzurufen, zu cachen und von der ENTSO-E API zu laden.

### Initialisierung:

-   **Zeilen 16-21:**  Lädt API-Key aus  `.env`, erstellt Router mit  `/entsoe`  Prefix und initialisiert  `EntsoeService`

### Funktionen:

1.  **startup()** 
    
    -   Wird beim App-Start ausgeführt
    -   Prüft ENTSO-E API-Verbindung und API-Key-Validität
2.  **`get_overview()`**  
    
    -   **GET**  `/entsoe/`
    -   Gibt Übersicht aller verfügbaren Endpunkte zurück
3.  **`create_price_entry()`** 
    
    -   **POST**  `/entsoe/prices/`
    -   Speichert manuell einen einzelnen Preisdatensatz im Cache
    -   Nutzt Datenbank-Session für persistente Speicherung
4.  **`get_prices()`**  
    
    -   **GET**  `/entsoe/prices/`  (Hauptendpunkt für Vessim)
    -   **Parameter:**  `zone`,  `start_time`, optional  `end_time`
    -   **Ablauf:**
        1.  Prüft Cache (Datenbank) nach existierenden Daten
        2.  Bei unvollständigem Cache (< 80%): Fetcht von ENTSO-E API
        3.  Füllt Lücken in Zeitreihe auf (15-Minuten-Intervalle)
        4.  Speichert neue Daten im Cache
        5.  Gibt vollständige Preisdaten zurück
    -   **Error-Handling:**  HTTP 502 bei API-Fehlern
5.  **`fetch_and_store_range()`**  
    
    -   **POST**  `/entsoe/prices/fetch-range/`
    -   Startet Background-Task zum Vorladen historischer Daten
    -   Nützlich für große Zeiträume ohne API-Blockierung
6.  **`fetch_range_task()`**  
    
    -   Background-Worker-Funktion
    -   Lädt und speichert Preisdaten asynchron
    -   Nutzt  session.merge()  für Duplikat-Handling
7.  **health_check()**  
    
    -   **GET**  `/entsoe/health`
    -   Einfacher Gesundheitscheck mit aktuellem Zeitstempel

**Cache-Strategie:**  Intelligentes 2-Schicht-System - zuerst lokale Datenbank prüfen, bei Bedarf ENTSO-E API anfragen und Ergebnis cachen für zukünftige Abfragen.

## Zusammenfassung der  service.py

**Hauptfunktion:**  Service-Schicht zur Kommunikation mit der ENTSO-E Transparency Platform API. Kapselt die externe API-Logik und bietet Hilfsfunktionen für Datenvalidierung und -aufbereitung.

### Klassen und Funktionen:

1.  **EntsoeService.__init__()**  
    
    -   Initialisiert ENTSO-E API Client mit API-Key
    -   Nutzt  `entsoe-py`  Bibliothek (`EntsoePandasClient`)
    -   Logging bei fehlendem Key oder Installationsproblemen
    -   Speichert Client-Instanz für spätere API-Aufrufe
2.  **`check_connection()`**  
    
    -   Validiert API-Key und Servererreichbarkeit
    -   **Test:**  Führt Probe-Abfrage für DE_LU Zone (letzte Stunde) aus
    -   **Return:**  `True`  bei erfolgreicher Verbindung,  `False`  bei Auth-Fehler
    -   **Error-Handling:**
        -   401/Unauthorized → API-Key ungültig
        -   "No matching data" → Verbindung OK, nur keine Daten
        -   Andere Fehler → Warnung, gibt trotzdem  `True`  zurück
3.  **`fetch_price_data()`**  
    
    -   Lädt Day-Ahead Strompreise von ENTSO-E API
    -   **Parameter:**
        -   `zone`: Handelszone (z.B. "DE_LU")
        -   `start`/`end`: Zeitbereich als Pandas Timestamps
    -   **Return:**  Pandas Series mit Zeitindex und Preiswerten
    -   Wirft Fehler bei fehlendem Client oder API-Problemen
4.  **`fill_missing_timestamps()`**  
    
    -   Standalone-Funktion (außerhalb der Klasse)
    -   **Problem:**  ENTSO-E API lässt manchmal Zeitstempel aus, wenn Preise unverändert bleiben
    -   **Lösung:**
        -   Erstellt vollständige Zeitreihe (Standard: 15-Minuten-Intervalle)
        -   Füllt fehlende Werte mit Forward-Fill-Methode (letzter bekannter Preis)
    -   **Return:**  Komplette Pandas Series ohne Lücken

**Design:**  Trennung von API-Kommunikation (Service) und Geschäftslogik (API-Handler) ermöglicht einfaches Testen und Wiederverwenden der ENTSO-E-Integration.
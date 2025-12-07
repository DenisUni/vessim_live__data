FROM python:3.11-slim

WORKDIR /app

# Installiere Abhängigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Kopiere den Exporter
COPY exporter/ ./exporter/

# Setze den Arbeitsverzeichnis-Pfad
ENV PYTHONPATH=/app

# Starte den Exporte
CMD ["python", "exporter/GSI.py"]
FROM python:3.11-slim

# Arbeitsverzeichnis im Container
WORKDIR /app

# Kopiere alles ins Container-Dateisystem
COPY . .

# Installiere Python-Abhängigkeiten (verwende requirements.txt!)
RUN pip install --no-cache-dir -r requirements.txt
# RUN pip install dash plotly requests pyyaml

# Mach run.sh ausführbar
RUN chmod +x run.sh

# Startkommando (führt Dash-App aus)
CMD ["bash", "run.sh"]


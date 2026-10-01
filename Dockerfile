FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CONFIG_HOME=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core hostname \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY arGeoDetector.py displaygeo.py displaygeo_web.py ./
COPY boundaries/ ./boundaries/

STOPSIGNAL SIGTERM
CMD ["python", "displaygeo.py", "--port", "/dev/gps", "--rate", "4800"]

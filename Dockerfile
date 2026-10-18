FROM python:3.12-slim
ENV TZ=Europe/Berlin PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir icalendar recurring-ical-events
WORKDIR /app
COPY static ./static
COPY index.html einkauf.js enocoo_fetch.py einkauf.py mobil.py tafel_server.py railway_main.py termine.json ./
CMD ["python3", "railway_main.py"]

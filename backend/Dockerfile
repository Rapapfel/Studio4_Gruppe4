FROM python:3.11-slim

WORKDIR /app

# Installiere DejaVu Fonts für QR-Code Text
RUN apt-get update && apt-get install -y \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Installiere Python Dependencies + downgrade Pillow + requests für BIG
RUN pip install flask flask-cors qrcode Pillow==10.4.0 requests

# Kopiere App und BIG Sync
COPY app.py /app/app.py
COPY big_sync.py /app/big_sync.py

# Erstelle data Ordner
RUN mkdir -p /app/data

EXPOSE 5000

CMD ["python", "app.py"]
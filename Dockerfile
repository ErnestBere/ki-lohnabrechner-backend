# Python 3.11 Slim + Tesseract OCR für Lohnabrechnungs-Parsing
FROM python:3.11-slim

# Tesseract OCR + deutsches Sprachpaket installieren
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}

FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ghostscript \
    libfreetype6-dev \
    libffi-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    libtiff-dev \
    libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/uploads /app/data/outputs /app/data/db

ENV PYTHONPATH=/app/backend

EXPOSE 8687

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8687", "--reload"]

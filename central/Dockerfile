FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .
COPY templates/ ./templates/

# SQLite database lives in a mounted volume so it survives restarts
VOLUME ["/app/data"]

ENV DATABASE_URL=sqlite:////app/data/yunlonglink.db

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

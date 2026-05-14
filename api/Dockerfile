FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt /app/api_requirements.txt
RUN pip install --no-cache-dir -r /app/api_requirements.txt

COPY . /app

ENV PYTHONPATH=/app:/app/bot

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

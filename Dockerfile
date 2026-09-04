FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render (and most PaaS hosts) inject $PORT at runtime — never hardcode it.
CMD uvicorn web.app:app --host 0.0.0.0 --port ${PORT:-8000}

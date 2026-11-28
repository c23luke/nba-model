# The NBA watcher on the always-on server (Fly.io). Same code the GitHub job ran: python -m engine.watch, kept running
# by engine.serve. Everything it saves goes to Supabase, so the machine needs no disk.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 WATCH_NO_PULL=1
WORKDIR /app
RUN pip install --no-cache-dir pdfplumber==0.11.4 tzdata
COPY engine ./engine
COPY data_static ./data_static
CMD ["python", "-m", "engine.serve"]

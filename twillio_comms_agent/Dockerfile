FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system deps (optional, minimal)
RUN pip install --no-cache-dir --upgrade pip

# Copy requirements first
COPY twillio_comms_agent/twillio_call/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app
COPY twillio_comms_agent/twillio_call /app

EXPOSE 5050

# Non-root
RUN groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app && chown -R app:app /app
USER app

CMD ["uvicorn", "final_fixed_agent:asgi_app", "--host", "0.0.0.0", "--port", "5050", "--log-level", "info", "--proxy-headers"]

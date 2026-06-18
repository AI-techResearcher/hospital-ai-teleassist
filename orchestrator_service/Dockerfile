FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip
# Copy root requirements if present; else install minimal
COPY requirements.txt /tmp/requirements.txt
RUN if [ -f /tmp/requirements.txt ]; then pip install --no-cache-dir -r /tmp/requirements.txt; fi || true
# Minimal deps for orchestrator
RUN pip install --no-cache-dir fastapi uvicorn langchain-openai langgraph python-dotenv

COPY . /app
COPY hospital_chatbot_orchestrator.py /app/
COPY Apointment_agent /app/Apointment_agent
COPY faiss_rag_integration.py /app/

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]

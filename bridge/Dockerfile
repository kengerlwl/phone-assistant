FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --disable-pip-version-check --timeout 30 --index-url "$PIP_INDEX_URL" -r requirements.txt
COPY server.py /app/server.py
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "/app/server.py"]

FROM python:3.12-slim
WORKDIR /app
COPY src/ src/
COPY pyproject.toml README.md LICENSE ./
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
# CLI container: no server port is exposed; the development server binds loopback.
ENTRYPOINT ["python", "-m", "traceforge"]
CMD ["demo", "--output", "/tmp/demo-results.json"]

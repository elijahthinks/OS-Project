# Build from the repository root:
#   docker build -f .build/Dockerfile -t pyos .
#   docker run -p 8080:8080 -v pyos-data:/data pyos
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYOS_HOST=0.0.0.0 \
    PYOS_PORT=8080 \
    PYOS_DATA_DIR=/data

WORKDIR /app
COPY src ./src
COPY Projectos.py ./

RUN useradd --create-home pyos && mkdir -p /data && chown pyos /data
USER pyos
VOLUME ["/data"]
EXPOSE 8080

CMD ["python", "Projectos.py", "--no-browser"]

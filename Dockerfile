FROM python:3.12-slim-bookworm

WORKDIR /app
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src ./src
COPY migrations ./migrations
# pyahocorasick has no aarch64 wheel at the pinned version, so it is built here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir . \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["joinhound"]
CMD ["--version"]

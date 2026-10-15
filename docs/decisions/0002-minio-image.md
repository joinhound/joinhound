# 0002. Use the community MinIO image for local development

## Context

The local stack needs an S3-compatible service. The specification names MinIO. The official `minio/minio` repository is no longer available for anonymous pulls from Docker Hub or Quay.

## Decision

`docker-compose.yml` uses `pgsty/minio:RELEASE.2026-08-04T00-00-00Z`. It serves the same S3 API and environment variables as MinIO, and it is only a local development service. It is not a Python dependency of the package.

## Alternatives

- Build the MinIO server image from source. That makes the first local start slower and harder to reproduce.
- Replace the local service with another S3 implementation. The specification names MinIO for development and tests.

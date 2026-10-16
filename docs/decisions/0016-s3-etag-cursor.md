# 0016. S3 credentials and the ETag cursor

## Context

The S3 connector lists a bucket prefix and must report objects that changed or disappeared. The specification's configuration example has a bucket, prefix, region, and collection roles. It does not name an endpoint or access keys, and `changes_since` receives only a cursor, not the `kg.documents` table.

## Decision

Credentials and a custom endpoint come from the standard environment variables `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_ENDPOINT_URL` (or `AWS_ENDPOINT_URL_S3`). An `http://` endpoint uses path-style requests. The published YAML shape is unchanged.

The cursor is a JSON object `{"etags": {"<key>": "<etag>"}}`. A missing cursor yields every object under the prefix. A stored cursor yields objects whose ETag differs and objects that are no longer listed, with `DocRef.deleted` set. Objects larger than 100 MB and archive suffixes are skipped and logged.

## Alternatives

- Add `endpoint` and keys to `S3SourceConfig`. That is a new field in the configuration users write, and the environment variables already cover MinIO and IAM.
- Detect deletions only while syncing `kg.documents`. The connector would then be unable to report a removal to a caller that already has the previous listing.

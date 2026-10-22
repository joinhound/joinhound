# Azure Blob document source

Azure Blob is a document source next to S3. The configuration type is `azure`. One source reads one container. The account key stays in `AZURE_STORAGE_ACCOUNT_KEY`, or a connection string stays in `AZURE_STORAGE_CONNECTION_STRING`. `account_url` is the account endpoint when the key is used on its own.

Blob provenance uses `azure://{source}/{key}`, with the same page and bbox fragment as `s3://`. Passages keep that scheme when they are indexed.

The connector lists and downloads. It has no upload or delete call. The account used in production should still be a reader, because the SDK client is created with the account key.

The integration test uses Azurite 3.34.0 and its published development account. That account can write, and the test uses it to put one blob before the contract check. The source under test only reads. Azurite 3.34.0 rejects the API version sent by the pinned SDK, so the test process is started with `--skipApiVersionCheck`. A real storage account accepts that version.

`azure-storage-blob` is pinned and used unmodified.

## Alternatives

- Read Azure through the S3 connector and a gateway. Blob Storage is not an S3 endpoint, and the provenance would say `s3://`.
- Use `obstore`'s Azure store. The S3 connector uses obstore, and its Azure backend was not the path already pinned for this repository.

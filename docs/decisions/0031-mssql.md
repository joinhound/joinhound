# SQL Server connector

SQL Server is a tabular source next to PostgreSQL. The configuration type is `mssql` and the DSN is `mssql://user:password@host:port/database`. Row provenance uses `mssql://{source}/{schema}.{table}#pk=...`, the same shape as `pg://`.

The connection is opened with the driver's read-only flag. The login should still be a reader. Exact matches are pushed down with one `SELECT`. Normalized, fuzzy, and semantic matches are not. A table without a primary key cannot be fetched or scanned.

The integration test uses Azure SQL Edge. It speaks the same catalog and TDS as SQL Server and runs on the development machines. The full `mssql/server` image does not publish an arm64 build. The current Edge image cannot create `/.system` as its default user, so the test starts that container as root.

`pymssql` is pinned and used unmodified.

## Alternatives

- Reach SQL Server through ODBC. That needs a driver installed on the host, and the contract test would depend on it.
- Wait for an ADBC driver. The specification names ADBC for non-PostgreSQL engines, and there is no Apache MSSQL driver to pin.

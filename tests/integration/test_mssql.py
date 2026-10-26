# SPDX-License-Identifier: Apache-2.0

"""SQL Server connector against Azure SQL Edge."""

import time

import pymssql
from testcontainers.core.container import DockerContainer

from joinhound.connectors.mssql import MssqlSource
from joinhound.core.config import MssqlSourceConfig
from joinhound.testing.contracts import check_tabular_source

_PASSWORD = "Joinhound-dev-1"


def test_mssql_source_passes_the_tabular_contract() -> None:
    last_error = ""
    for _attempt in range(3):
        with _server() as server:
            host = server.get_container_host_ip()
            try:
                port = int(server.get_exposed_port(1433))
                _wait(host, port)
            except (ConnectionError, RuntimeError) as error:
                stdout, stderr = server.get_logs()
                last_error = f"{error}\n{stdout.decode()[-1500:]}\n{stderr.decode()[-500:]}"
                continue
            _seed(host, port)
            dsn = f"mssql://sa:{_PASSWORD}@{host}:{port}/master"
            with MssqlSource(
                "warehouse",
                MssqlSourceConfig(type="mssql", dsn=dsn, schemas=["dbo"]),
            ) as source:
                check_tabular_source(
                    source,
                    collection_id="mssql://warehouse/dbo.customers",
                    column="email",
                    value="a@example.com",
                    key={"id": 1},
                )
                links = source.declared_links()
            break
    else:
        raise RuntimeError(last_error)

    assert any(link.src_columns == ["customer_id"] and link.dst_columns == ["id"] for link in links)


def _server() -> DockerContainer:
    """Edge cannot create /.system as its default user, and sqlservr sometimes crashes."""
    return (
        DockerContainer("mcr.microsoft.com/azure-sql-edge:latest")
        .with_env("ACCEPT_EULA", "Y")
        .with_env("MSSQL_SA_PASSWORD", _PASSWORD)
        .with_exposed_ports(1433)
        .with_kwargs(user="root")
    )


def _wait(host: str, port: int) -> None:
    deadline = time.monotonic() + 45
    last = ""
    while time.monotonic() < deadline:
        try:
            connection = pymssql.connect(
                server=host,
                port=str(port),
                user="sa",
                password=_PASSWORD,
                database="master",
                login_timeout=5,
                timeout=5,
            )
        except pymssql.Error as error:
            last = str(error)
            time.sleep(2)
            continue
        connection.close()
        return
    raise RuntimeError(f"SQL Server did not accept connections: {last}")


def _seed(host: str, port: int) -> None:
    connection = pymssql.connect(
        server=host,
        port=str(port),
        user="sa",
        password=_PASSWORD,
        database="master",
        autocommit=True,
    )
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE dbo.customers (
          id int NOT NULL PRIMARY KEY,
          email nvarchar(200) NOT NULL
        )
        """
    )
    cursor.execute(
        "INSERT INTO dbo.customers (id, email) VALUES (%s, %s)",
        (1, "a@example.com"),
    )
    cursor.execute(
        """
        CREATE TABLE dbo.orders (
          id int NOT NULL PRIMARY KEY,
          customer_id int NOT NULL REFERENCES dbo.customers (id)
        )
        """
    )
    connection.close()

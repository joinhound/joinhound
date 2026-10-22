# SPDX-License-Identifier: Apache-2.0

"""The Azure Blob connector passes the document contract against Azurite."""

from collections.abc import Iterator

import pytest
from azure.storage.blob import BlobServiceClient
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from joinhound.connectors.azure import AzureSource
from joinhound.core.config import AclConfig, AzureSourceConfig
from joinhound.testing.contracts import check_document_source

_IMAGE = "mcr.microsoft.com/azure-storage/azurite:3.34.0"
_ACCOUNT = "devstoreaccount1"
_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


@pytest.fixture(scope="module")
def blob_connection() -> Iterator[str]:
    container = (
        DockerContainer(_IMAGE)
        .with_command("azurite-blob --blobHost 0.0.0.0 --blobPort 10000 --skipApiVersionCheck")
        .with_exposed_ports(10000)
    )
    with container:
        wait_for_logs(container, "successfully listens on", timeout=60)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(10000)
        connection = (
            "DefaultEndpointsProtocol=http;"
            f"AccountName={_ACCOUNT};AccountKey={_KEY};"
            f"BlobEndpoint=http://{host}:{port}/{_ACCOUNT};"
        )
        client = BlobServiceClient.from_connection_string(connection)
        client.create_container("docs")
        client.get_blob_client("docs", "notes.txt").upload_blob(b"hello from azurite")
        yield connection


def test_azurite_passes_the_document_contract(
    blob_connection: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", blob_connection)
    source = AzureSource(
        "docs",
        AzureSourceConfig(type="azure", container="docs", acl=AclConfig(roles=["legal"])),
    )

    check_document_source(source, name="notes.txt", content=b"hello from azurite")

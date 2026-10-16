# SPDX-License-Identifier: Apache-2.0

"""The S3 connector passes the document contract against MinIO."""

import hashlib
import hmac
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.request import Request, urlopen

import pytest
from obstore.store import S3Store
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from joinhound.connectors.s3 import S3Source
from joinhound.core.config import AclConfig, S3SourceConfig
from joinhound.testing.contracts import check_document_source

_IMAGE = "pgsty/minio:RELEASE.2026-08-04T00-00-00Z"
_ACCESS = "joinhound"
_SECRET = "joinhound-dev"


@pytest.fixture(scope="module")
def minio_endpoint() -> Iterator[str]:
    container = (
        DockerContainer(_IMAGE)
        .with_env("MINIO_ROOT_USER", _ACCESS)
        .with_env("MINIO_ROOT_PASSWORD", _SECRET)
        .with_command("server /data --console-address :9001")
        .with_exposed_ports(9000)
    )
    with container:
        wait_for_logs(container, "API:", timeout=60)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(9000)
        endpoint = f"http://{host}:{port}"
        _create_bucket(endpoint, "docs")
        yield endpoint


def test_minio_passes_the_document_contract(
    minio_endpoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", _ACCESS)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", _SECRET)
    monkeypatch.setenv("AWS_ENDPOINT_URL", minio_endpoint)
    store = S3Store(
        "docs",
        region="us-east-1",
        access_key_id=_ACCESS,
        secret_access_key=_SECRET,
        endpoint=minio_endpoint,
        virtual_hosted_style_request=False,
        client_options={"allow_http": True},
    )
    store.put("notes.txt", b"hello from minio")
    source = S3Source(
        "docs",
        S3SourceConfig(type="s3", bucket="docs", acl=AclConfig(roles=["legal"])),
    )

    check_document_source(source, name="notes.txt", content=b"hello from minio")


def _create_bucket(endpoint: str, bucket: str) -> None:
    now = datetime.now(UTC)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    host = endpoint.removeprefix("http://")
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amzdate}\n"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical = f"PUT\n/{bucket}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    scope = f"{datestamp}/us-east-1/s3/aws4_request"
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    string_to_sign = f"AWS4-HMAC-SHA256\n{amzdate}\n{scope}\n{digest}"
    key = _sign(f"AWS4{_SECRET}".encode(), datestamp)
    key = _sign(key, "us-east-1")
    key = _sign(key, "s3")
    key = _sign(key, "aws4_request")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={_ACCESS}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    request = Request(
        f"{endpoint}/{bucket}",
        method="PUT",
        headers={
            "Host": host,
            "x-amz-date": amzdate,
            "x-amz-content-sha256": payload_hash,
            "Authorization": authorization,
        },
    )
    with urlopen(request, timeout=10) as response:
        response.read()


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()

"""MinIO storage must stay private: browser links are presigned, never bare."""

from urllib.parse import parse_qs, urlparse

import pytest

from api.services.filesystem.minio import MinioFileSystem


@pytest.fixture
def fs(monkeypatch):
    # Don't contact a MinIO server: bucket setup is best-effort anyway.
    monkeypatch.setattr("minio.Minio.bucket_exists", lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(
        "minio.Minio.delete_bucket_policy", lambda self, b: calls.append(b)
    )
    fs = MinioFileSystem(
        endpoint="minio:9000",
        access_key="key",
        secret_key="secret",
        bucket_name="voice-audio",
        public_endpoint="https://app.example.com",
    )
    fs.policy_calls = calls
    return fs


def test_startup_removes_any_anonymous_bucket_policy(fs):
    assert fs.policy_calls == ["voice-audio"]


async def test_signed_url_is_presigned_against_the_public_host(fs):
    url = await fs.aget_signed_url("recordings/1.wav", expiration=600)

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "app.example.com"
    assert parsed.path == "/voice-audio/recordings/1.wav"
    assert query["X-Amz-Expires"] == ["600"]
    assert "X-Amz-Signature" in query


async def test_inline_signed_url_sets_content_disposition(fs):
    url = await fs.aget_signed_url("recordings/1.wav", force_inline=True)

    assert parse_qs(urlparse(url).query)["response-content-disposition"] == ["inline"]


async def test_upload_url_is_presigned(fs):
    url = await fs.aget_presigned_put_url("campaigns/1/list.csv")

    assert "X-Amz-Signature" in parse_qs(urlparse(url).query)

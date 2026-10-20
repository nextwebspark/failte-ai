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


async def test_both_clients_sign_for_the_configured_region(monkeypatch):
    monkeypatch.setattr("minio.Minio.bucket_exists", lambda *a, **k: True)
    monkeypatch.setattr("minio.Minio.delete_bucket_policy", lambda *a, **k: None)
    fs = MinioFileSystem(
        endpoint="minio:9000",
        public_endpoint="https://app.example.com",
        region="eu-west-1",
    )

    for internal in (False, True):
        url = await fs.aget_signed_url("a.wav", use_internal_endpoint=internal)
        credential = parse_qs(urlparse(url).query)["X-Amz-Credential"][0]
        assert "/eu-west-1/s3/" in credential


@pytest.mark.parametrize(
    "public_endpoint", ["https://cdn.example.com/minio", "https://cdn.example.com/a/"]
)
def test_public_endpoint_with_a_path_is_rejected(public_endpoint):
    with pytest.raises(ValueError, match="must not contain a path"):
        MinioFileSystem(endpoint="minio:9000", public_endpoint=public_endpoint)


def test_public_endpoint_with_a_trailing_slash_is_accepted(monkeypatch):
    monkeypatch.setattr("minio.Minio.bucket_exists", lambda *a, **k: True)
    monkeypatch.setattr("minio.Minio.delete_bucket_policy", lambda *a, **k: None)

    fs = MinioFileSystem(endpoint="minio:9000", public_endpoint="https://example.com/")

    assert fs.public_endpoint == "https://example.com"


def test_unreachable_minio_does_not_fail_construction(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("minio down")

    monkeypatch.setattr("minio.Minio.bucket_exists", boom)

    MinioFileSystem(endpoint="minio:9000", public_endpoint="https://example.com")


def test_legacy_bucket_is_made_private_when_s3_is_primary(monkeypatch):
    from api.services import storage
    from api.services.filesystem import S3FileSystem

    calls = []
    monkeypatch.setattr(storage, "MINIO_CONFIGURED", True)
    monkeypatch.setattr(storage, "storage_fs", object.__new__(S3FileSystem))
    monkeypatch.setattr("minio.Minio.bucket_exists", lambda *a, **k: True)
    monkeypatch.setattr(
        "minio.Minio.delete_bucket_policy", lambda self, b: calls.append(b)
    )

    storage.secure_legacy_minio_bucket()

    assert calls == [storage.MINIO_BUCKET]


def test_legacy_bucket_cleanup_skips_a_missing_bucket(monkeypatch):
    from api.services import storage
    from api.services.filesystem import S3FileSystem

    monkeypatch.setattr(storage, "MINIO_CONFIGURED", True)
    monkeypatch.setattr(storage, "storage_fs", object.__new__(S3FileSystem))
    monkeypatch.setattr("minio.Minio.bucket_exists", lambda *a, **k: False)

    def fail(*a, **k):
        raise AssertionError("must not create or touch a missing bucket")

    monkeypatch.setattr("minio.Minio.make_bucket", fail)
    monkeypatch.setattr("minio.Minio.delete_bucket_policy", fail)

    storage.secure_legacy_minio_bucket()


def test_legacy_bucket_cleanup_survives_an_unreachable_minio(monkeypatch):
    from api.services import storage
    from api.services.filesystem import S3FileSystem

    def boom(*a, **k):
        raise ConnectionError("minio down")

    monkeypatch.setattr(storage, "MINIO_CONFIGURED", True)
    monkeypatch.setattr(storage, "storage_fs", object.__new__(S3FileSystem))
    monkeypatch.setattr("minio.Minio.bucket_exists", boom)

    storage.secure_legacy_minio_bucket()


def test_legacy_bucket_cleanup_is_skipped_without_minio(monkeypatch):
    from api.services import storage
    from api.services.filesystem import S3FileSystem

    monkeypatch.setattr(storage, "MINIO_CONFIGURED", False)
    monkeypatch.setattr(storage, "storage_fs", object.__new__(S3FileSystem))

    def fail(*a, **k):
        raise AssertionError("must not contact MinIO")

    monkeypatch.setattr("minio.Minio.bucket_exists", fail)

    storage.secure_legacy_minio_bucket()

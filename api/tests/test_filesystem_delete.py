"""Object deletion on the storage backends is idempotent."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from botocore.exceptions import ClientError
from minio.error import S3Error

from api.services.filesystem.minio import MinioFileSystem
from api.services.filesystem.s3 import S3FileSystem


def _minio(client) -> MinioFileSystem:
    fs = object.__new__(MinioFileSystem)
    fs.bucket_name = "voice-audio"
    fs.client = client
    return fs


def _s3_error(code: str) -> S3Error:
    return S3Error(code, "message", "resource", "request", "host", MagicMock())


async def test_minio_delete_file_treats_missing_object_as_deleted():
    client = MagicMock()
    fs = _minio(client)

    assert await fs.adelete_file("recordings/1.wav") is True
    client.remove_object.assert_called_once_with("voice-audio", "recordings/1.wav")

    client.remove_object.side_effect = _s3_error("NoSuchKey")
    assert await fs.adelete_file("recordings/1.wav") is True

    client.remove_object.side_effect = _s3_error("AccessDenied")
    assert await fs.adelete_file("recordings/1.wav") is False


async def test_minio_delete_prefix_removes_every_listed_object():
    client = MagicMock()
    client.list_objects.return_value = [
        SimpleNamespace(object_name="recordings/1/noveum/user/a.wav"),
        SimpleNamespace(object_name="recordings/1/noveum/bot/b.wav"),
    ]
    removed = []
    client.remove_objects.side_effect = lambda bucket, objects: (
        removed.extend(o._name for o in objects) or iter(())
    )
    fs = _minio(client)

    assert await fs.adelete_prefix("recordings/1/noveum/") == 2
    client.list_objects.assert_called_once_with(
        "voice-audio", prefix="recordings/1/noveum/", recursive=True
    )
    assert removed == [
        "recordings/1/noveum/user/a.wav",
        "recordings/1/noveum/bot/b.wav",
    ]

    client.list_objects.return_value = []
    assert await fs.adelete_prefix("recordings/2/noveum/") == 0


class _ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *exc):
        return False


def _s3(client) -> S3FileSystem:
    fs = S3FileSystem(bucket_name="bucket", region_name="europe-west1")
    fs.session = SimpleNamespace(client=lambda *a, **k: _ClientContext(client))
    return fs


async def test_s3_delete_file_is_idempotent_and_reports_errors():
    client = SimpleNamespace(delete_object=AsyncMock())
    fs = _s3(client)

    assert await fs.adelete_file("transcripts/1.txt") is True
    client.delete_object.assert_awaited_once_with(
        Bucket="bucket", Key="transcripts/1.txt"
    )

    client.delete_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey"}}, "DeleteObject"
    )
    assert await fs.adelete_file("transcripts/1.txt") is True

    client.delete_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}}, "DeleteObject"
    )
    assert await fs.adelete_file("transcripts/1.txt") is False


async def test_s3_delete_prefix_deletes_each_listed_key():
    class Paginator:
        def paginate(self, **kwargs):
            assert kwargs == {"Bucket": "bucket", "Prefix": "recordings/1/noveum/"}

            async def pages():
                yield {"Contents": [{"Key": "recordings/1/noveum/user/a.wav"}]}
                yield {"Contents": [{"Key": "recordings/1/noveum/bot/b.wav"}]}
                yield {}

            return pages()

    client = SimpleNamespace(
        get_paginator=lambda name: Paginator(), delete_object=AsyncMock()
    )
    fs = _s3(client)

    assert await fs.adelete_prefix("recordings/1/noveum/") == 2
    assert [c.kwargs["Key"] for c in client.delete_object.await_args_list] == [
        "recordings/1/noveum/user/a.wav",
        "recordings/1/noveum/bot/b.wav",
    ]

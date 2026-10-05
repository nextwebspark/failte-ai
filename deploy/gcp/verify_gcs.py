#!/usr/bin/env python3
"""Prove Google Cloud Storage works through the S3-compatible XML API.

GCS interop is the one genuine compatibility risk in this deployment: the app
talks to object storage with aioboto3 (api/services/filesystem/s3.py) and leans
on presigned URLs, which is where S3-compatible servers most often diverge.

This exercises exactly the operations S3FileSystem uses, against a real bucket,
before anything depends on it. Run it BEFORE deploying.

    pip install aioboto3
    export S3_BUCKET=dograh-voice-audio-eu
    export S3_REGION=europe-west1
    export S3_ENDPOINT_URL=https://storage.googleapis.com
    export S3_SIGNATURE_VERSION=s3v4
    export S3_ADDRESSING_STYLE=virtual
    export AWS_ACCESS_KEY_ID=<HMAC access id>
    export AWS_SECRET_ACCESS_KEY=<HMAC secret>
    python deploy/gcp/verify_gcs.py

Exit code 0 means the S3 storage backend is safe to switch on.
"""

import asyncio
import os
import sys
import uuid

import aioboto3
import urllib.request
from botocore.config import Config

BUCKET = os.environ["S3_BUCKET"]
REGION = os.environ.get("S3_REGION", "europe-west1")
ENDPOINT = os.environ.get("S3_ENDPOINT_URL") or None
SIGVER = os.environ.get("S3_SIGNATURE_VERSION") or None
ADDRESSING = os.environ.get("S3_ADDRESSING_STYLE") or None

KEY = f"_verify/{uuid.uuid4().hex}.txt"
COPY_KEY = KEY.replace(".txt", ".copy.txt")
BODY = b"dograh gcs interop check\n"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


def client_config() -> Config:
    """Mirror how api/services/filesystem/s3.py builds its client config."""
    kwargs: dict = {}
    if SIGVER:
        kwargs["signature_version"] = SIGVER
    if ADDRESSING:
        kwargs["s3"] = {"addressing_style": ADDRESSING}
    return Config(**kwargs)


async def main() -> int:
    session = aioboto3.Session()
    async with session.client(
        "s3",
        region_name=REGION,
        endpoint_url=ENDPOINT,
        config=client_config(),
    ) as s3:
        print(f"bucket={BUCKET} endpoint={ENDPOINT} addressing={ADDRESSING} sigver={SIGVER}\n")

        # --- basic object operations ----------------------------------------
        try:
            await s3.put_object(Bucket=BUCKET, Key=KEY, Body=BODY, ContentType="text/plain")
            record("put_object", True)
        except Exception as e:
            record("put_object", False, repr(e))
            return 1  # nothing else can work

        try:
            head = await s3.head_object(Bucket=BUCKET, Key=KEY)
            record("head_object", head["ContentLength"] == len(BODY),
                   f"{head['ContentLength']} bytes")
        except Exception as e:
            record("head_object", False, repr(e))

        # Server-side copy — used when artifacts are promoted between prefixes.
        try:
            await s3.copy_object(
                Bucket=BUCKET, Key=COPY_KEY,
                CopySource={"Bucket": BUCKET, "Key": KEY},
            )
            record("copy_object", True)
        except Exception as e:
            record("copy_object", False, repr(e))

        # --- presigned GET, the part most likely to break ---------------------
        # s3.py overrides response headers on GET presigns so .wav/.txt render
        # inline in the browser. GCS has historically been fussy about the
        # response-* override parameters, so test them explicitly.
        try:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": BUCKET,
                    "Key": KEY,
                    "ResponseContentType": "text/plain",
                    "ResponseContentDisposition": "inline",
                },
                ExpiresIn=900,
            )
            with urllib.request.urlopen(url, timeout=30) as r:
                got = r.read()
                ctype = r.headers.get("Content-Type", "")
            ok = got == BODY
            record("presigned GET (with response overrides)", ok,
                   f"content-type={ctype!r}")
            if ok and "text/plain" not in ctype:
                record("  response-header override honoured", False,
                       "GCS ignored ResponseContentType — recordings may download "
                       "instead of playing inline")
        except Exception as e:
            record("presigned GET (with response overrides)", False, repr(e))

        # Plain presigned GET without overrides, to isolate the cause above.
        try:
            url = await s3.generate_presigned_url(
                "get_object", Params={"Bucket": BUCKET, "Key": KEY}, ExpiresIn=900
            )
            with urllib.request.urlopen(url, timeout=30) as r:
                got = r.read()
            record("presigned GET (plain)", got == BODY)
        except Exception as e:
            record("presigned GET (plain)", False, repr(e))

        # --- presigned PUT, used for direct CSV upload from the browser -------
        try:
            put_key = KEY.replace(".txt", ".upload.csv")
            url = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": BUCKET, "Key": put_key, "ContentType": "text/csv"},
                ExpiresIn=900,
            )
            req = urllib.request.Request(
                url, data=b"a,b\n1,2\n", method="PUT",
                headers={"Content-Type": "text/csv"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                code = r.status
            record("presigned PUT", code in (200, 201), f"HTTP {code}")
            await s3.delete_object(Bucket=BUCKET, Key=put_key)
        except Exception as e:
            record("presigned PUT", False, repr(e))

        # --- cleanup ----------------------------------------------------------
        for k in (KEY, COPY_KEY):
            try:
                await s3.delete_object(Bucket=BUCKET, Key=k)
            except Exception:
                pass

    print()
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        print("\nIf signature errors appear, try S3_ADDRESSING_STYLE=path.")
        print("If presigning is fundamentally broken, do NOT fall back to the")
        print("MinIO backend as-is — it applies an anonymous public bucket policy")
        print("(api/services/filesystem/minio.py) and returns unsigned URLs.")
        return 1

    print("All checks passed — the S3 backend is safe to enable against GCS.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

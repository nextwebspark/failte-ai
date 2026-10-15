"""Encrypt / re-encrypt every external credential under the primary key.

Run from the repo root with the api environment (CREDENTIALS_ENCRYPTION_KEYS
set to the new key list, primary first):

    python -m scripts.reencrypt_credentials [--batch-size 200] [--dry-run]

Use it after enabling encryption on an install with existing plaintext rows
(the backfill migration does the same when keys are present at migration
time), and as step 2 of key rotation:

    1. CREDENTIALS_ENCRYPTION_KEYS=<new>,<old>   (restart every api/worker)
    2. python -m scripts.reencrypt_credentials
    3. CREDENTIALS_ENCRYPTION_KEYS=<new>          (restart again)

Exits non-zero if any row could not be decrypted with the configured keys;
those rows are left untouched and their ids are printed (never their data).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from api.constants import CREDENTIALS_ENCRYPTION_KEYS, DATABASE_URL
from api.db.credential_encryption_client import CredentialEncryptionClient
from api.utils.credential_crypto import CredentialCipher


async def _run(batch_size: int, dry_run: bool) -> int:
    if not CREDENTIALS_ENCRYPTION_KEYS:
        print("CREDENTIALS_ENCRYPTION_KEYS is not set; nothing to do.", file=sys.stderr)
        return 2
    cipher = CredentialCipher(CREDENTIALS_ENCRYPTION_KEYS)
    engine = create_async_engine(DATABASE_URL)
    try:
        report = await CredentialEncryptionClient(engine).reencrypt_all(
            cipher, batch_size=batch_size, dry_run=dry_run
        )
    finally:
        await engine.dispose()
    prefix = "[dry run] " if dry_run else ""
    print(
        f"{prefix}scanned={report.scanned} encrypted={report.encrypted} "
        f"rotated={report.rotated} failed={len(report.failed_ids)}"
    )
    if report.failed_ids:
        print(
            "Rows no configured key can decrypt (left unchanged): "
            + ", ".join(str(i) for i in report.failed_ids),
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.batch_size, args.dry_run)))


if __name__ == "__main__":
    main()

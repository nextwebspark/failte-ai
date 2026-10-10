"""Zip import and export in the standard skill folder layout.

Import accepts either a single ``SKILL.md`` (any upload that is not a zip) or
a zip holding ``SKILL.md`` at its root or inside exactly one top-level folder
(``<skill-name>/SKILL.md``, the layout ``export_skill_zip`` produces and
Claude's skills use). ``__MACOSX/`` entries and ``.DS_Store`` files are
skipped.

Untrusted archives are refused, before anything is decompressed where
possible, when they:

- exceed the upload size, entry count, per-file or total uncompressed size;
- have an overall compression ratio above ``max_compression_ratio`` (bomb);
- contain duplicate entry names, compression other than stored/deflate,
  absolute paths, ``..``, backslashes, hidden or otherwise invalid
  paths (traversal), symlinks, encrypted entries or non-UTF-8/binary files.

Declared sizes are not trusted: each entry is read with a hard byte limit.
"""

import io
import stat
import zipfile
import zlib

from api.db.skill_client import SkillContent, SkillFile
from api.errors.skills import SkillValidationError
from api.services.skills import validation
from api.services.skills.frontmatter import (
    FRONTMATTER_MAX_BYTES,
    SkillDocument,
    parse_skill_md,
    render_skill_md,
)
from api.services.skills.validation import DEFAULT_LIMITS, SkillLimits

_SKILL_MD = validation.SKILL_FILE_NAME
_SKILL_MD_MAX_BYTES = validation.BODY_MAX_BYTES + FRONTMATTER_MAX_BYTES + 1024
_JUNK_PREFIXES = ("__MACOSX/",)
_COMPRESS_TYPES = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
_JUNK_NAMES = (".DS_Store",)
# Fixed timestamp so identical skills export to identical bytes.
_EPOCH = (1980, 1, 1, 0, 0, 0)


def is_zip(data: bytes) -> bool:
    return data[:4] in (b"PK\x03\x04", b"PK\x05\x06")


def read_skill_upload(
    data: bytes, *, limits: SkillLimits = DEFAULT_LIMITS
) -> SkillDocument:
    """Parse an uploaded ``.zip`` or ``SKILL.md``: the content is validated,
    ``allowed_tools`` is returned raw for the caller to resolve."""
    if not data:
        raise SkillValidationError("The uploaded file is empty")
    if len(data) > limits.max_archive_bytes:
        raise SkillValidationError(
            f"The upload must be at most {limits.max_archive_bytes // 1024} KB"
        )
    if is_zip(data):
        skill_md, files = _read_zip(data, limits)
    else:
        if len(data) > _SKILL_MD_MAX_BYTES:
            raise SkillValidationError("SKILL.md is too large")
        skill_md, files = _decode(data, _SKILL_MD), ()
    document = parse_skill_md(skill_md)
    content = validation.validate_content(
        SkillContent(
            name=document.content.name,
            description=document.content.description,
            body_md=document.content.body_md,
            files=files,
            extra=document.content.extra,
        )
    )
    return SkillDocument(content=content, allowed_tools=document.allowed_tools)


def export_skill_zip(
    content: SkillContent, *, allowed_tools: tuple[str, ...] | None = None
) -> bytes:
    """``<name>/SKILL.md`` plus ``<name>/<path>`` for each file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        entries = [(_SKILL_MD, render_skill_md(content, allowed_tools=allowed_tools))]
        entries += [(f.path, f.content) for f in content.files]
        for path, text in entries:
            info = zipfile.ZipInfo(f"{content.name}/{path}", date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, text.encode("utf-8"))
    return buffer.getvalue()


def _read_zip(data: bytes, limits: SkillLimits) -> tuple[str, tuple[SkillFile, ...]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError):
        raise SkillValidationError("The upload is not a valid zip archive") from None
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_archive_entries:
            raise SkillValidationError(
                f"The archive has more than {limits.max_archive_entries} entries"
            )
        names = [info.filename for info in infos]
        if len(set(names)) != len(names):
            duplicate = next(n for n in names if names.count(n) > 1)
            raise SkillValidationError(
                f"The archive has duplicate entries named '{duplicate[:80]}'"
            )
        entries = [info for info in infos if not _skip(info)]
        for info in entries:
            _check_entry(info)
        declared = sum(info.file_size for info in entries)
        size_cap = _SKILL_MD_MAX_BYTES + validation.FILES_TOTAL_MAX_BYTES
        if declared > size_cap:
            raise SkillValidationError(
                f"The archive expands to more than {size_cap // 1024} KB"
            )
        compressed = sum(info.compress_size for info in entries)
        if declared > limits.max_compression_ratio * max(compressed, 1):
            raise SkillValidationError(
                "The archive's compression ratio is suspiciously high"
            )
        root = _skill_root([info.filename for info in entries])
        skill_md: str | None = None
        files: list[SkillFile] = []
        for info in entries:
            relative = info.filename[len(root) :]
            if relative == _SKILL_MD:
                skill_md = _decode(
                    _read_bounded(archive, info, _SKILL_MD_MAX_BYTES), _SKILL_MD
                )
                continue
            path = validation.validate_path(relative)
            if len(files) >= validation.MAX_FILES:
                raise SkillValidationError(
                    f"A skill can have at most {validation.MAX_FILES} files"
                )
            raw = _read_bounded(archive, info, validation.FILE_MAX_BYTES)
            files.append(SkillFile(path=path, content=_decode(raw, path)))
    if skill_md is None:  # pragma: no cover - guaranteed by _skill_root
        raise SkillValidationError("The archive has no SKILL.md")
    return skill_md, tuple(files)


def _skip(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    if info.is_dir():
        return True
    if name.startswith(_JUNK_PREFIXES):
        return True
    return name.rsplit("/", 1)[-1] in _JUNK_NAMES


def _check_entry(info: zipfile.ZipInfo) -> None:
    name = info.filename
    shown = name[:80]
    if info.compress_type not in _COMPRESS_TYPES:
        raise SkillValidationError(
            f"Unsupported compression for '{shown}' (use stored or deflate)"
        )
    if info.flag_bits & 0x1:
        raise SkillValidationError(
            f"Encrypted archive entries are not supported: {shown}"
        )
    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise SkillValidationError(f"Symbolic links are not allowed: {shown}")
    if mode and not stat.S_ISREG(mode) and stat.S_IFMT(mode):
        raise SkillValidationError(f"Only regular files are allowed: {shown}")
    if "\\" in name or name.startswith("/") or ".." in name.split("/"):
        raise SkillValidationError(f"Unsafe path in archive: {shown}")


def _skill_root(names: list[str]) -> str:
    """'' when SKILL.md is at the root, else '<folder>/' when every entry
    lives in one top-level folder that holds SKILL.md."""
    if _SKILL_MD in names:
        return ""
    tops = {name.split("/", 1)[0] for name in names}
    if len(tops) == 1:
        top = next(iter(tops))
        if f"{top}/{_SKILL_MD}" in names:
            return f"{top}/"
    raise SkillValidationError(
        "The archive must contain SKILL.md at its root or inside a single "
        "top-level folder (<skill-name>/SKILL.md)"
    )


def _read_bounded(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise SkillValidationError(
            f"'{info.filename[:80]}' is larger than {limit // 1024} KB"
        )
    try:
        with archive.open(info) as handle:
            data = handle.read(limit + 1)
    except (
        zipfile.BadZipFile,
        zlib.error,
        NotImplementedError,
        RuntimeError,
        OSError,
        EOFError,
    ):
        raise SkillValidationError(
            f"Could not read '{info.filename[:80]}' from the archive"
        ) from None
    if len(data) > limit:
        raise SkillValidationError(
            f"'{info.filename[:80]}' is larger than {limit // 1024} KB"
        )
    return data


def _decode(data: bytes, label: str) -> str:
    if b"\x00" in data:
        raise SkillValidationError(
            f"'{label[:80]}' is not a text file (binary content is not supported)"
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise SkillValidationError(f"'{label[:80]}' is not valid UTF-8 text") from None

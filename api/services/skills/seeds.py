"""Seed skills shipped with the code: ``api/skills_library/<name>/SKILL.md``.

Each folder is one library skill in the standard layout. The folder name must
equal the frontmatter ``name`` (Agent Skills rule). ``metadata.category``, if
present, becomes the library category. The seed hash covers everything that
is synced, so ``SkillClient.sync_library_seeds`` can tell a changed seed from
an unchanged one.
"""

import hashlib
import json
from pathlib import Path

from api.db.skill_client import LibrarySeed, SkillContent, SkillFile
from api.errors.skills import SkillValidationError
from api.services.skills import validation
from api.services.skills.frontmatter import parse_skill_md

SEED_ROOT = Path(__file__).resolve().parents[2] / "skills_library"


def load_seeds(root: Path = SEED_ROOT) -> list[LibrarySeed]:
    """Every seed folder under ``root``, validated, sorted by name.

    Raises ``SkillValidationError`` naming the folder for an invalid seed:
    seeds are our own code, so a broken one should fail loudly.
    """
    if not root.is_dir():
        return []
    seeds: list[LibrarySeed] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if folder.name.startswith((".", "_")):
            continue
        try:
            seeds.append(_load_folder(folder))
        except SkillValidationError as exc:
            raise SkillValidationError(
                f"Seed skill '{folder.name}': {exc.message}"
            ) from exc
    return seeds


def _load_folder(folder: Path) -> LibrarySeed:
    skill_md = folder / validation.SKILL_FILE_NAME
    if not skill_md.is_file():
        raise SkillValidationError("missing SKILL.md")
    document = parse_skill_md(skill_md.read_text(encoding="utf-8"))
    files = [
        SkillFile(
            path=path.relative_to(folder).as_posix(),
            content=path.read_text(encoding="utf-8"),
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file()
        and path != skill_md
        and not path.is_symlink()
        and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    ]
    content = validation.validate_content(
        SkillContent(
            name=document.content.name,
            description=document.content.description,
            body_md=document.content.body_md,
            files=tuple(files),
            extra=document.content.extra,
        )
    )
    if content.name != folder.name:
        raise SkillValidationError(
            f"frontmatter name '{content.name}' must match the folder name"
        )
    if document.allowed_tools is not None:
        raise SkillValidationError(
            "library skills cannot set allowed-tools (tools are per workspace)"
        )
    category = validation.validate_category(content.extra.metadata.get("category"))
    return LibrarySeed(
        content=content, category=category, seed_hash=seed_hash(content, category)
    )


def seed_hash(content: SkillContent, category: str | None) -> str:
    canonical = json.dumps(
        {
            "name": content.name,
            "description": content.description,
            "body_md": content.body_md,
            "extra": content.extra.to_json(),
            "category": category,
            "files": [[f.path, f.content] for f in content.files],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

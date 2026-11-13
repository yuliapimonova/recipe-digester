"""The recipe folder: one Markdown file per recipe, with a small header that Obsidian and similar apps understand."""
import datetime
import json
import os
import re
from pathlib import Path

HEADER_FIELDS = ("title", "source", "tags", "servings", "prep_min", "cook_min", "total_min", "language", "added")


def folder() -> Path:
    path = Path(os.getenv("RECIPES_DIR") or Path(__file__).parent / "recipes").expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def lines(text: str | None) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def minutes(value) -> int | None:
    """The page sends form values as text; store whole minutes as numbers."""
    text = str(value or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def to_markdown(recipe: dict) -> str:
    # Header values are written as JSON, which is also valid YAML, so quotes and colons in titles are safe.
    values = {
        "title": recipe["title"].strip(),
        "source": recipe.get("source_url"),
        "tags": recipe.get("tags", []),
        "servings": str(recipe.get("servings") or "").strip() or None,
        "prep_min": minutes(recipe.get("prep_min")),
        "cook_min": minutes(recipe.get("cook_min")),
        "total_min": minutes(recipe.get("total_min")),
        "language": recipe.get("language"),
        "added": datetime.date.today().isoformat(),
    }
    header = [f"{key}: {json.dumps(values[key], ensure_ascii=False)}" for key in HEADER_FIELDS if values[key] is not None]
    times = [f"{label} {values[key]} min" for label, key in (("Prep", "prep_min"), ("Cook", "cook_min"), ("Total", "total_min")) if values[key]]
    facts = ([f"Serves {values['servings']}"] if values["servings"] else []) + times

    parts = ["---", *header, "---", "", f"# {values['title']}", ""]
    if summary := (recipe.get("summary") or "").strip():
        parts += [summary, ""]
    if facts:
        parts += [" · ".join(facts), ""]
    parts += ["## Ingredients", "", *(f"- {line}" for line in lines(recipe.get("ingredients"))), ""]
    parts += ["## Steps", "", *(f"{n}. {line}" for n, line in enumerate(lines(recipe.get("steps")), 1)), ""]
    if notes := lines(recipe.get("notes")):
        parts += ["## Notes", "", *notes, ""]
    if values["source"]:
        label = "Video" if recipe.get("source_type") == "youtube" else "Source"
        parts += [f"{label}: <{values['source']}>", ""]
    return "\n".join(parts)


def read_header(path: Path) -> dict:
    """Read the header of a file this app wrote; anything it can't parse is skipped."""
    header = {}
    with path.open(encoding="utf-8") as file:
        if file.readline().strip() != "---":
            return header
        for line in file:
            if line.strip() == "---":
                break
            key, _, value = line.partition(":")
            try:
                header[key.strip()] = json.loads(value)
            except json.JSONDecodeError:
                header[key.strip()] = value.strip()
    return header


def headers() -> list[tuple[Path, dict]]:
    return [(path, read_header(path)) for path in sorted(folder().glob("*.md"))]


def existing_tags() -> list[str]:
    tags = {tag for _, header in headers() if isinstance(header.get("tags"), list) for tag in header["tags"]}
    return sorted(tags, key=str.lower)


def find_duplicate(recipe: dict) -> str | None:
    """Same title and same link; one video can hold several recipes with different titles."""
    title, url = recipe["title"].strip(), recipe.get("source_url")
    for path, header in headers():
        if header.get("title") == title and header.get("source") == url:
            return str(path)
    return None


def file_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title).strip(" .")[:100]
    return name or "Recipe"


def save(recipe: dict, force: bool = False) -> dict:
    if not (recipe.get("title") or "").strip():
        raise ValueError("Add a title before saving.")
    if not force and (duplicate := find_duplicate(recipe)):
        return {"duplicate": duplicate}
    base = file_name(recipe["title"])
    path = folder() / f"{base}.md"
    number = 2
    while path.exists():
        path = folder() / f"{base} ({number}).md"
        number += 1
    path.write_text(to_markdown(recipe), encoding="utf-8")
    return {"path": str(path)}

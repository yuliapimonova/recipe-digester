import functools
import os
import re

from notion_client import APIResponseError, Client

MAX_TEXT = 2000
MAX_BLOCKS = 100
# What setup_notion.py creates, and what saving writes to.
PROPERTIES = {
    "Name": {"title": {}},
    "Link": {"url": {}},
    "Tags": {"multi_select": {}},
    "Ingredients": {"rich_text": {}},
    "Description": {"rich_text": {}},
}


def configured() -> bool:
    return bool(os.getenv("NOTION_TOKEN") and os.getenv("NOTION_DATABASE_ID"))


def client(token: str | None = None) -> Client:
    token = token or os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN is missing from .env.")
    return Client(auth=token)


def notion_id(text: str) -> str:
    """Accept a bare ID or a whole Notion link like notion.so/My-Recipes-0123abcd...?v=..."""
    path = text.split("?")[0].replace("-", "").lower()
    runs = re.findall(r"[0-9a-f]{32,}", path)
    if not runs:
        raise ValueError(f"Can't find a Notion ID in {text!r}.")
    # The ID is the last 32 characters; title words made of letters a-f can run into it.
    return runs[-1][-32:]


@functools.cache
def data_source_id() -> str:
    """Databases hold their pages in a data source; the first one is the database's own table."""
    database_id = notion_id(os.getenv("NOTION_DATABASE_ID") or "")
    try:
        return client().databases.retrieve(database_id=database_id)["data_sources"][0]["id"]
    except APIResponseError as e:
        if e.status == 404:
            raise ValueError("Notion can't see your recipe database. Connect your integration to it (••• → Connections).")
        raise ValueError(f"Notion error: {e}")


def connect(link: str, token: str | None = None) -> str:
    """Use a database link as it is; for a page link, create a Recipes database in that page. Returns the database ID."""
    notion, target = client(token), notion_id(link)
    try:
        try:
            return notion.databases.retrieve(database_id=target)["id"]
        except APIResponseError as e:
            # A page ID gives 400 here; 404 can mean a page that isn't shared, which creating will report.
            if e.status not in (400, 404):
                raise
        database = notion.databases.create(
            parent={"type": "page_id", "page_id": target},
            title=[{"type": "text", "text": {"content": "Recipes"}}],
            initial_data_source={"properties": PROPERTIES},
        )
    except APIResponseError as e:
        if e.status == 401:
            raise ValueError("Notion didn't accept the token. Copy the integration's secret again.")
        if e.status == 404:
            raise ValueError("Notion can't see that page. Open it in Notion, then ••• → Connections → add your integration.")
        raise ValueError(f"Notion error: {e}")
    return database["id"]


def existing_tags() -> list[str]:
    """Return the Tags options; empty if Notion isn't reachable, so extraction still works."""
    try:
        source = client().data_sources.retrieve(data_source_id=data_source_id())
    except (ValueError, APIResponseError) as e:
        print(f"could not read Notion tags: {e}", flush=True)
        return []
    return [option["name"] for option in source["properties"]["Tags"]["multi_select"]["options"]]


def rich_text(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text[i:i + MAX_TEXT]}} for i in range(0, len(text), MAX_TEXT)]


def block(kind: str, text: str) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": rich_text(text)}}


def lines(text: str | None) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def description(recipe: dict) -> str:
    """Summary plus known facts, e.g. 'A hearty soup.\nServes 4 · 45 min'."""
    servings = str(recipe.get("servings") or "").strip()
    facts = []
    if servings:
        facts.append(f"Serves {servings}" if servings.isdigit() else servings)
    if recipe.get("total_min"):
        facts.append(f"{recipe['total_min']} min")
    return "\n".join(part for part in [(recipe.get("summary") or "").strip(), " · ".join(facts)] if part)


def page_properties(recipe: dict) -> dict:
    properties = {
        "Name": {"title": rich_text(recipe["title"].strip())},
        "Tags": {"multi_select": [{"name": tag} for tag in recipe.get("tags", [])]},
        "Ingredients": {"rich_text": rich_text("\n".join(lines(recipe.get("ingredients"))))},
        "Description": {"rich_text": rich_text(description(recipe))},
    }
    if recipe.get("source_url"):
        properties["Link"] = {"url": recipe["source_url"]}
    return properties


def page_blocks(recipe: dict) -> list[dict]:
    blocks = [block("heading_2", "Ingredients")]
    blocks += [block("bulleted_list_item", line) for line in lines(recipe.get("ingredients"))]
    blocks.append(block("heading_2", "Steps"))
    blocks += [block("numbered_list_item", line) for line in lines(recipe.get("steps"))]
    if notes := lines(recipe.get("notes")):
        blocks.append(block("heading_2", "Notes"))
        blocks += [block("paragraph", line) for line in notes]
    if recipe.get("source_type") == "youtube":
        url = recipe["source_url"]
        link = {"type": "text", "text": {"content": url, "link": {"url": url}}}
        blocks.append(block("heading_2", "Video"))
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [link]}})
    return blocks


def find_duplicate(notion: Client, title: str, url: str) -> str | None:
    """Return the URL of a page with this title and link; one video can hold several recipes."""
    match = {"and": [
        {"property": "Link", "url": {"equals": url}},
        {"property": "Name", "title": {"equals": title}},
    ]}
    pages = notion.data_sources.query(data_source_id=data_source_id(), filter=match, page_size=1)["results"]
    return pages[0]["url"] if pages else None


def save(recipe: dict, force: bool = False) -> dict:
    title = (recipe.get("title") or "").strip()
    if not title:
        raise ValueError("Add a title before saving.")
    notion = client()
    try:
        if recipe.get("source_url") and not force:
            if duplicate := find_duplicate(notion, title, recipe["source_url"]):
                return {"duplicate": duplicate}
        blocks = page_blocks(recipe)
        page = notion.pages.create(
            parent={"type": "data_source_id", "data_source_id": data_source_id()},
            properties=page_properties(recipe),
            children=blocks[:MAX_BLOCKS],
        )
        for start in range(MAX_BLOCKS, len(blocks), MAX_BLOCKS):
            notion.blocks.children.append(block_id=page["id"], children=blocks[start:start + MAX_BLOCKS])
    except APIResponseError as e:
        if e.status == 404:
            raise ValueError("Notion can't see your recipe database. Connect your integration to it (••• → Connections).")
        raise ValueError(f"Notion error: {e}")
    return {"url": page["url"]}

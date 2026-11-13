"""Check the Notion recipe database, or create one.

    python setup_notion.py               check the database in NOTION_DATABASE_ID
    python setup_notion.py <page link>   create a "Recipes" database inside that page
                                         (the app's Settings panel does the same)
"""
import sys

from notion_client import APIResponseError

import notion
import settings

settings.load()


def create(page_link: str) -> None:
    print("Recipe database ready. Add this line to .env:")
    print(f"NOTION_DATABASE_ID={notion.connect(page_link)}")


def check() -> None:
    source = notion.client().data_sources.retrieve(data_source_id=notion.data_source_id())
    properties = source["properties"]
    problems = [
        f"{name} should be a {kind} property"
        for name, spec in notion.PROPERTIES.items()
        for kind in spec
        if properties.get(name, {}).get("type") != kind
    ]
    print("Connected to the recipe database.")
    print("Properties:", ", ".join(f"{name} ({p['type']})" for name, p in properties.items()))
    if problems:
        sys.exit("Problems: " + "; ".join(problems) + ". Rename or add these in Notion.")
    print("All required properties are present.")


try:
    if len(sys.argv) > 1:
        create(sys.argv[1])
    elif not notion.configured():
        sys.exit(__doc__)
    else:
        check()
except APIResponseError as e:
    if e.status == 404:
        sys.exit("Notion can't see that page. Open it in Notion, then ••• → Connections → add your integration.")
    sys.exit(f"Notion error: {e}")
except ValueError as e:
    sys.exit(str(e))

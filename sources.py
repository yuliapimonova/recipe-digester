import html
import json
import re
import urllib.error
import urllib.request

import yt_dlp
from youtube_transcript_api import RequestBlocked, YouTubeTranscriptApi, YouTubeTranscriptApiException

# Many recipe sites reject Python's default user agent.
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

MAX_TEXT_CHARS = 40_000
MAX_TRANSCRIPT_CHARS = 150_000  # About 3 hours of speech.
JSON_LD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
YOUTUBE = re.compile(r"https?://([\w-]+\.)?(youtube\.com|youtu\.be)/", re.I)
DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:[\d.]+S)?)?")


def fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        raise ValueError(f"The site returned HTTP {e.code}, so the page could not be read. A screenshot of the recipe may work instead.")
    except urllib.error.URLError as e:
        raise ValueError(f"Could not fetch the page: {e.reason}")
    except TimeoutError:
        raise ValueError("The site took too long to respond.")


def find_recipe(node) -> dict | None:
    """Walk JSON-LD (lists, @graph, mainEntity) to the first Recipe object."""
    if isinstance(node, dict):
        if "Recipe" in as_list(node.get("@type")):
            return node
        node = list(node.values())
    if isinstance(node, list):
        for item in node:
            if found := find_recipe(item):
                return found
    return None


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text))
    return " ".join(text.split())


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def minutes(value) -> int | None:
    """Convert an ISO 8601 duration like PT1H30M; zero usually means the site left it blank."""
    match = DURATION.fullmatch(str(value).strip())
    if not match:
        return None
    days, hours, mins = (int(group or 0) for group in match.groups())
    return days * 1440 + hours * 60 + mins or None


def parse_steps(node) -> list[str]:
    if isinstance(node, str):
        parts = re.split(r"\n+|<br\s*/?>|</p>|</li>", html.unescape(node))
        return [line for line in map(clean, parts) if line]
    if isinstance(node, list):
        return [step for item in node for step in parse_steps(item)]
    if isinstance(node, dict):
        return parse_steps(node.get("itemListElement") or node.get("text") or node.get("name"))
    return []


def recipe_from_json_ld(page: str, url: str) -> dict | None:
    """Return a recipe dict, or None if the page has no complete Recipe JSON-LD."""
    recipe = None
    for block in JSON_LD.findall(page):
        try:
            recipe = find_recipe(json.loads(block, strict=False))
        except json.JSONDecodeError:
            continue
        if recipe:
            break
    if not recipe:
        return None

    title = clean(str((as_list(recipe.get("name")) or [""])[0]))
    # Kept as one string for now: the GUI edits ingredients as whole lines anyway.
    ingredients = [
        {"qty": None, "unit": None, "item": clean(line), "note": None}
        for line in as_list(recipe.get("recipeIngredient") or recipe.get("ingredients"))
        if isinstance(line, str) and clean(line)
    ]
    steps = parse_steps(recipe.get("recipeInstructions"))
    # Some sites (gastronom.ru) publish names without amounts; "Сметана 25%" shows one digit isn't enough.
    with_amounts = sum(any(ch.isnumeric() for ch in i["item"]) for i in ingredients)
    if not (title and ingredients and steps and with_amounts * 2 >= len(ingredients)):
        return None

    prep = minutes(recipe.get("prepTime"))
    cook = minutes(recipe.get("cookTime"))
    servings = as_list(recipe.get("recipeYield"))
    language = recipe.get("inLanguage")
    if not isinstance(language, str):
        match = re.search(r"<html[^>]*\blang=[\"']?([\w-]+)", page, re.I)
        language = match.group(1) if match else None

    return {
        "title": title,
        "source_url": url,
        "source_type": "web",
        "servings": clean(str(servings[0])) if servings else None,
        "prep_min": prep,
        "cook_min": cook,
        "total_min": minutes(recipe.get("totalTime")) or (prep + cook if prep and cook else None),
        "ingredients": ingredients,
        "steps": steps,
        "tags": [],
        "notes": None,
        "language": language,
    }


def page_text(page: str) -> str:
    """Strip HTML to readable text, capped so one huge page can't eat the usage limit."""
    page = re.sub(r"<(script|style|noscript|svg|template)\b.*?</\1>", " ", page, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", page))
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)[:MAX_TEXT_CHARS]


def is_youtube(url: str) -> bool:
    return bool(YOUTUBE.match(url))


def fetch_transcript(video_id: str, spoken: str) -> str:
    """Prefer the spoken language, then human-written captions over auto-generated ones."""
    try:
        transcripts = list(YouTubeTranscriptApi().list(video_id))
        if not transcripts:
            return ""
        transcripts.sort(key=lambda t: (not spoken.startswith(t.language_code[:2]), t.is_generated))
        return " ".join(snippet.text for snippet in transcripts[0].fetch())[:MAX_TRANSCRIPT_CHARS]
    except RequestBlocked:
        # Falling back to the description here could silently lose recipes.
        raise ValueError("YouTube is temporarily blocking transcript requests from this network. Try again later.")
    except YouTubeTranscriptApiException as e:
        print(f"no transcript for {video_id}: {type(e).__name__}", flush=True)
        return ""


def fetch_youtube(url: str, with_transcript: bool = True) -> dict:
    options = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
    except yt_dlp.utils.DownloadError as e:
        raise ValueError(f"Could not read this video: {e}")
    # Auto-dubbed videos list many audio languages; the original track has the highest preference.
    audio = [f for f in info.get("formats", []) if f.get("language")]
    spoken = max(audio, key=lambda f: f.get("language_preference") or 0)["language"] if audio else ""
    return {
        "title": info.get("title"),
        "url": f"https://www.youtube.com/watch?v={info['id']}",
        "description": (info.get("description") or "").strip(),
        "transcript": fetch_transcript(info["id"], spoken) if with_transcript else "",
    }

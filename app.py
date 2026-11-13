import os
import shutil

from dotenv import load_dotenv
from flask import Flask, request

import extract
import library
import notion
import sources

load_dotenv()

app = Flask(__name__)


def has_claude_code() -> bool:
    """The Claude models run through Claude Code on this computer, logged in to the user's own plan."""
    return shutil.which("claude") is not None


def default_model() -> str:
    preferred = os.getenv("DEFAULT_MODEL")
    if preferred in extract.MODELS:
        return preferred
    return "sonnet" if has_claude_code() and not os.getenv("GEMINI_API_KEY") else "gemini"


def chosen_model(value: str | None) -> str:
    model = value if value in extract.MODELS else default_model()
    if model != "gemini" and not has_claude_code():
        raise ValueError(extract.CLAUDE_CODE_ONLY)
    return model


@app.errorhandler(ValueError)
def show_error(e: ValueError):
    return {"error": str(e)}, 422


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/config")
def config():
    return {
        "models": [{"id": m, "name": name} for m, name in extract.MODELS.items()],
        "default": default_model(),
        "claude_error": None if has_claude_code() else extract.CLAUDE_CODE_ONLY,
        "notion": notion.configured(),
    }


def find_recipes(url: str, images: list, model: str) -> list[dict]:
    if images:
        return extract.from_images([(f.mimetype, f.read()) for f in images], model)
    if sources.is_youtube(url) and model == "gemini":
        return extract.from_youtube_video(sources.fetch_youtube(url, with_transcript=False), url)
    if sources.is_youtube(url):
        return extract.from_youtube(sources.fetch_youtube(url), url, model)
    page = sources.fetch_html(url)
    recipe = sources.recipe_from_json_ld(page, url)
    return [recipe] if recipe else extract.from_text(sources.page_text(page), url, model)


@app.post("/api/extract")
def extract_recipe():
    model = chosen_model(request.form.get("model"))
    images = request.files.getlist("images")
    url = request.form.get("url", "").strip()
    if not images and not url.startswith(("http://", "https://")):
        return {"error": "Paste a full URL starting with http:// or https://, or add images."}, 400
    try:
        recipes = find_recipes(url, images, model)
    except ValueError as e:
        return {"error": str(e)}, 422
    all_tags = library.existing_tags()
    if notion.configured():
        all_tags = sorted(set(all_tags) | set(notion.existing_tags()), key=str.lower)
    return {"recipes": extract.describe(recipes, all_tags, model), "all_tags": all_tags}


@app.post("/api/cut-fluff")
def cut_fluff():
    body = request.get_json()
    try:
        return extract.cut_fluff(body["steps"], body["notes"], chosen_model(body.get("model")))
    except ValueError as e:
        return {"error": str(e)}, 422


@app.post("/api/translate")
def translate():
    body = request.get_json()
    target = body.get("target", "").strip()
    if not target:
        return {"error": "Choose a language to translate to."}, 400
    try:
        return extract.translate(body["recipe"], target, body.get("existing_tags", []), chosen_model(body.get("model")))
    except ValueError as e:
        return {"error": str(e)}, 422


@app.post("/api/save")
def save():
    body = request.get_json()
    try:
        return library.save(body["recipe"], body.get("force", False))
    except ValueError as e:
        return {"error": str(e)}, 422


@app.post("/api/notion")
def export_to_notion():
    body = request.get_json()
    try:
        return notion.save(body["recipe"], body.get("force", False))
    except ValueError as e:
        return {"error": str(e)}, 422


if __name__ == "__main__":
    # Port 5000 is often taken by AirPlay on macOS. For auto-reload while developing: flask --app app run --debug --port 5002
    app.run(port=5002)

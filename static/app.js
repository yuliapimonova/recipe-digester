const $ = (id) => document.getElementById(id);
let images = [];

// Day/night switch. Without a saved choice the page follows the system setting.
const systemDark = matchMedia("(prefers-color-scheme: dark)");

function isDark() {
  const chosen = document.documentElement.dataset.theme;
  return chosen ? chosen === "dark" : systemDark.matches;
}

function showThemeButton() {
  $("theme").textContent = isDark() ? "Day mode" : "Night mode";
}

showThemeButton();
systemDark.addEventListener("change", showThemeButton);

$("theme").addEventListener("click", () => {
  const theme = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("theme", theme); } catch {}
  showThemeButton();
});

fetch("/api/config").then((r) => r.json()).then((c) => {
  $("model").replaceChildren(...c.models.map((m) => new Option(m.name, m.id)));
  $("model").value = c.default;
  claudeError = c.claude_error;
  checkModel();
  $("notion-option").hidden = !c.notion;
  $("to-notion").checked = c.notion;
});

let claudeError = null;

// Claude runs through Claude Code on this computer; say so as soon as it's picked without it.
function checkModel() {
  const unusable = claudeError && $("model").value !== "gemini";
  if (unusable) setStatus(claudeError, true);
  else if ($("status").textContent === claudeError) setStatus("");
  return !unusable;
}

$("model").addEventListener("change", checkModel);

function showImages() {
  $("image-list").textContent = images.map((f) => f.name).join(", ");
  $("image-list").hidden = images.length === 0;
  $("clear-images").hidden = images.length === 0;
}

// One input at a time: whichever was added last replaces the other.
function addImages(files) {
  const added = [...files].filter((f) => f.type.startsWith("image/"));
  if (added.length === 0) return;
  images.push(...added);
  $("source").value = "";
  showImages();
}

$("source").addEventListener("input", () => {
  images = [];
  showImages();
});

$("files").addEventListener("change", (e) => {
  addImages(e.target.files);
  e.target.value = "";
});

$("clear-images").addEventListener("click", () => {
  images = [];
  showImages();
});

document.addEventListener("paste", (e) => {
  if (e.clipboardData.files.length) {
    e.preventDefault();
    addImages(e.clipboardData.files);
  }
});

document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault();
  addImages(e.dataTransfer.files);
});

function setStatus(text, isError = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

function ingredientLine(i) {
  return [i.qty, i.unit, i.item, i.note].filter(Boolean).join(" ");
}

const FIELDS = ["title", "summary", "servings", "prep_min", "cook_min", "total_min", "ingredients", "steps", "notes"];
let recipes = [];
let current = 0;
let allTags = [];

function asFormValues(recipe) {
  return {
    ...recipe,
    ingredients: recipe.ingredients.map(ingredientLine).join("\n"),
    steps: recipe.steps.join("\n"),
    new_tags: recipe.new_tags ?? [],
    selected: new Set(recipe.tags),
  };
}

function tagGroup(heading, names, recipe) {
  const group = document.createElement("div");
  group.className = "tag-group";
  const title = document.createElement("strong");
  title.textContent = heading;
  group.append(title);
  for (const name of names) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = recipe.selected.has(name);
    box.addEventListener("change", () => {
      if (box.checked) recipe.selected.add(name);
      else recipe.selected.delete(name);
    });
    const label = document.createElement("label");
    label.append(box, ` ${name}`);
    group.append(label);
  }
  return group;
}

function showTags(recipe) {
  const groups = [
    ["Suggested tags", recipe.tags],
    ["Suggested new tags", recipe.new_tags],
    ["Other tags", allTags.filter((name) => !recipe.tags.includes(name))],
  ];
  $("tag-groups").replaceChildren(
    ...groups.filter(([, names]) => names.length).map(([heading, names]) => tagGroup(heading, names, recipe)),
  );
}

function notionLink(text, url) {
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.textContent = text;
  return link;
}

function showSaveResult(recipe) {
  const parts = [];
  if (recipe.savedPath) parts.push(`Saved to ${recipe.savedPath}. `);
  else if (recipe.duplicatePath) parts.push(`This recipe is already saved: ${recipe.duplicatePath}. `);
  if (recipe.notionUrl) parts.push(notionLink("Open in Notion", recipe.notionUrl));
  else if (recipe.notionDuplicate) parts.push("It's already in Notion: ", notionLink("open it", recipe.notionDuplicate));
  $("save-result").replaceChildren(...parts);
  const notionDone = recipe.notionUrl || !$("to-notion").checked;
  $("save").disabled = Boolean(recipe.savedPath && notionDone);
  const fileBlocked = recipe.duplicatePath && !recipe.savedPath;
  const notionBlocked = recipe.notionDuplicate && !recipe.notionUrl;
  $("save-anyway").hidden = !(fileBlocked || notionBlocked);
}

$("to-notion").addEventListener("change", () => showSaveResult(recipes[current]));

async function postJson(url, body) {
  let response;
  try {
    response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new Error("Could not reach the app. Is it still running?");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

// Saves the file first, then exports to Notion if ticked. Each step is skipped once done, so a retry only redoes what failed.
async function saveRecipe(force) {
  saveCurrent();
  const recipe = recipes[current];
  const body = { recipe: { ...recipe, tags: [...recipe.selected] }, force };
  $("save").disabled = true;
  $("save-anyway").disabled = true;
  setStatus("Saving…");
  try {
    if (!recipe.savedPath) {
      const data = await postJson("/api/save", body);
      recipe.duplicatePath = data.duplicate;
      recipe.savedPath = data.path;
      if (!data.path) {
        setStatus("Already saved, so not saved again.");
        return;
      }
    }
    if ($("to-notion").checked && !recipe.notionUrl) {
      setStatus("Exporting to Notion…");
      const data = await postJson("/api/notion", body);
      recipe.notionDuplicate = data.duplicate;
      recipe.notionUrl = data.url;
      if (!data.url) {
        setStatus("Saved. Already in Notion, so not exported again.");
        return;
      }
    }
    setStatus("Saved.");
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    $("save-anyway").disabled = false;
    showSaveResult(recipe);
  }
}

$("save").addEventListener("click", () => saveRecipe(false));
$("save-anyway").addEventListener("click", () => saveRecipe(true));

function saveCurrent() {
  for (const field of FIELDS) recipes[current][field] = $(field).value;
}

function showTabs() {
  $("tabs").replaceChildren(...recipes.map((recipe, i) => {
    const tab = document.createElement("button");
    tab.textContent = `${i + 1}. ${recipe.title || "Untitled"}`;
    tab.disabled = i === current;
    tab.addEventListener("click", () => {
      saveCurrent();
      showRecipe(i);
    });
    return tab;
  }));
  $("tabs").hidden = recipes.length < 2;
}

function showRecipe(i) {
  current = i;
  for (const field of FIELDS) $(field).value = recipes[i][field] ?? "";
  showTabs();
  showTags(recipes[i]);
  showSaveResult(recipes[i]);
  showVersionButton(recipes[i]);
  $("undo-cut").hidden = true;
  $("preview").hidden = false;
}

const TEXT_FIELDS = ["title", "summary", "ingredients", "steps", "notes"];

function formText() {
  return Object.fromEntries(TEXT_FIELDS.map((field) => [field, $(field).value]));
}

function setFormText(values) {
  for (const field of TEXT_FIELDS) $(field).value = values[field];
  $("undo-cut").hidden = true;
}

// A version is the text plus the tag choices, so "Show original" brings back both.
function currentVersion(recipe) {
  return { ...formText(), tags: recipe.tags, new_tags: recipe.new_tags, selected: new Set(recipe.selected) };
}

function applyVersion(recipe, version) {
  setFormText(version);
  recipe.tags = version.tags;
  recipe.new_tags = version.new_tags;
  recipe.selected = version.selected;
  showTags(recipe);
}

// Translated tags that match one already in use count as suggested tags; the rest as new ones.
function translatedVersion(recipe, sentTags, data) {
  const translation = new Map(sentTags.map((tag, i) => [tag, data.tags[i]]));
  const shown = [...new Set(sentTags.map((tag) => translation.get(tag)))];
  return {
    ...data,
    tags: shown.filter((tag) => allTags.includes(tag)),
    new_tags: shown.filter((tag) => !allTags.includes(tag)),
    selected: new Set([...recipe.selected].map((tag) => translation.get(tag))),
  };
}

function showVersionButton(recipe) {
  $("show-version").hidden = !recipe.otherVersion;
  $("show-version").textContent = recipe.translated ? "Show original" : "Show translation";
}

$("translate").addEventListener("click", async () => {
  saveCurrent();
  const recipe = recipes[current];
  $("translate").disabled = true;
  setStatus(`Translating to ${$("target").value}…`);
  const sentTags = [...new Set([...recipe.tags, ...recipe.new_tags, ...recipe.selected])];
  try {
    const response = await fetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recipe: { ...recipe, selected: undefined, tags: sentTags },
        target: $("target").value,
        existing_tags: allTags,
        model: $("model").value,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      setStatus(data.error, true);
      return;
    }
    if (!recipe.translated) recipe.otherVersion = currentVersion(recipe);
    recipe.translated = true;
    applyVersion(recipe, translatedVersion(recipe, sentTags, data));
    showVersionButton(recipe);
    setStatus("Translated.");
  } catch {
    setStatus("Could not reach the app. Is it still running?", true);
  } finally {
    $("translate").disabled = false;
  }
});

$("show-version").addEventListener("click", () => {
  const recipe = recipes[current];
  const showing = currentVersion(recipe);
  applyVersion(recipe, recipe.otherVersion);
  recipe.otherVersion = showing;
  recipe.translated = !recipe.translated;
  showVersionButton(recipe);
  setStatus("");
});

let beforeCut = null;

$("cut-fluff").addEventListener("click", async () => {
  $("cut-fluff").disabled = true;
  setStatus("Cutting the fluff…");
  beforeCut = { steps: $("steps").value, notes: $("notes").value };
  try {
    const response = await fetch("/api/cut-fluff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        steps: beforeCut.steps.split("\n").filter((line) => line.trim()),
        notes: beforeCut.notes,
        model: $("model").value,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      setStatus(data.error, true);
      return;
    }
    $("steps").value = data.steps.join("\n");
    $("notes").value = data.notes;
    $("undo-cut").hidden = data.removed === 0;
    setStatus(data.removed ? `Removed ${data.removed} passage(s).` : "No fluff found.");
  } catch {
    setStatus("Could not reach the app. Is it still running?", true);
  } finally {
    $("cut-fluff").disabled = false;
  }
});

$("undo-cut").addEventListener("click", () => {
  $("steps").value = beforeCut.steps;
  $("notes").value = beforeCut.notes;
  $("undo-cut").hidden = true;
  setStatus("Restored.");
});

$("extract").addEventListener("click", async () => {
  $("extract").disabled = true;
  $("preview").hidden = true;
  $("tabs").hidden = true;
  setStatus(images.length ? "Extracting… this can take a minute." : "Fetching, then extracting if needed… this can take a minute.");
  const form = new FormData();
  form.append("url", $("source").value);
  form.append("model", $("model").value);
  images.forEach((f) => form.append("images", f));
  try {
    const response = await fetch("/api/extract", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) {
      setStatus(data.error, true);
      return;
    }
    allTags = data.all_tags;
    recipes = data.recipes.map(asFormValues);
    showRecipe(0);
    setStatus(recipes.length > 1 ? `Done. Found ${recipes.length} recipes.` : "Done.");
  } catch {
    setStatus("Could not reach the app. Is it still running?", true);
  } finally {
    $("extract").disabled = false;
  }
});

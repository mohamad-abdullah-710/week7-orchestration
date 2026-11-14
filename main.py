"""Recipe Box — starter app for Week 7.

A tiny FastAPI service for recipes and tags, with a static frontend. Use it as the
playground for concurrent multi-agent work and a generator-critic loop.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload
    # open http://localhost:8000/
Test:
    pytest
"""
import json
import math
import re
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "recipes.db"

app = FastAPI(title="Recipe Box")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_db()) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS recipes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                ingredients TEXT NOT NULL,  -- JSON list of strings
                tags        TEXT NOT NULL,  -- JSON list of strings
                favorite    INTEGER NOT NULL DEFAULT 0  -- 0/1, returned as bool
            )"""
        )
        # Migrate databases created before the favorite column existed.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
        if "favorite" not in columns:
            conn.execute(
                "ALTER TABLE recipes ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()


init_db()


class RecipeIn(BaseModel):
    title: str
    ingredients: list[str] = []
    tags: list[str] = []


def _row_to_recipe(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "ingredients": json.loads(row["ingredients"]),
        "tags": json.loads(row["tags"]),
        "favorite": bool(row["favorite"]),
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/recipes")
def create_recipe(recipe: RecipeIn):
    with closing(get_db()) as conn:
        cur = conn.execute(
            "INSERT INTO recipes (title, ingredients, tags) VALUES (?, ?, ?)",
            (recipe.title, json.dumps(recipe.ingredients), json.dumps(recipe.tags)),
        )
        conn.commit()
        rid = cur.lastrowid
    return {"id": rid, **recipe.model_dump(), "favorite": False}


@app.get("/recipes")
def list_recipes(tag: str | None = None):
    """List recipes, optionally only those with a given tag.

    Tag matching is case-insensitive and ignores surrounding spaces
    ("Breakfast" matches "breakfast"). A missing or empty `tag` returns all
    recipes. A tag no recipe has returns [] (not 404).
    """
    with closing(get_db()) as conn:
        rows = conn.execute("SELECT * FROM recipes ORDER BY id").fetchall()
    recipes = [_row_to_recipe(r) for r in rows]
    wanted = (tag or "").strip().lower()
    if not wanted:
        return recipes
    return [
        rec for rec in recipes if wanted in (t.strip().lower() for t in rec["tags"])
    ]


@app.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: int):
    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown recipe")
    return _row_to_recipe(row)


# Unicode vulgar fractions we understand ("1½ cups" means 1.5 cups).
_UNICODE_FRACTIONS = {
    "¼": 0.25, "½": 0.5, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}
_UF = "".join(_UNICODE_FRACTIONS)

# One quantity. Order matters: the first alternative that matches wins.
_NUMBER = (
    r"\d+\s+\d+/\d+"                       # mixed number: "1 1/2"
    rf"|(?:\d+\s*)?[{_UF}]"                # unicode fraction: "½", "1½", "1 ½"
    r"|\d+/\d+"                            # fraction: "1/2"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])"  # thousands: "1,000", "1,000.5"
    r"|\d+(?:[.,]\d+)?"                    # integer or decimal: "200", "0.5", "1,5"
)
_THOUSANDS_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
# Leading quantity, optionally a range: "2-3", "2 – 3", "2—3", "2 to 3",
# "2 or 3", "1/2-1". Hyphen, en dash and em dash all count as range dashes.
_QUANTITY_RE = re.compile(
    rf"^\s*(?P<first>{_NUMBER})"
    rf"(?:(?P<sep>\s*[-–—]\s*|\s+(?:to|or)\s+)(?P<second>{_NUMBER}))?"
)


def _parse_quantity(text: str) -> float | None:
    """Turn one matched quantity into a number (None for a zero denominator)."""
    text = text.strip()
    if text[-1] in _UNICODE_FRACTIONS:
        whole = text[:-1].strip()
        return (int(whole) if whole else 0) + _UNICODE_FRACTIONS[text[-1]]
    if "/" in text:
        parts = text.split()
        num, den = (int(x) for x in parts[-1].split("/"))
        if den == 0 or (num != 0 and num / den == 0):  # zero / underflow to 0.0
            return None
        return (int(parts[0]) if len(parts) == 2 else 0) + num / den
    if _THOUSANDS_RE.fullmatch(text):
        return float(text.replace(",", ""))
    return float(text.replace(",", "."))


def _format_quantity(value: float) -> str:
    """Show a number without useless decimals: 400.0 -> "400", 0.25 -> "0.25".

    Normally rounds to 2 decimal places. Amounts so small that this would give
    "0" keep 2 significant figures instead (0.001 -> "0.001"), so a non-zero
    amount never becomes "0". No thousands separators in the output.
    """
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    if text in ("0", "") and value > 0:
        text = f"{Decimal(f'{value:.2g}'):f}"
    return text or "0"


def scale_ingredient(ingredient: str, factor: float) -> str:
    """Multiply the leading quantity (or range) of an ingredient by `factor`.

    Understands:
      - integers and decimals: "200 g flour", "0.5 l", "1,5 kg" (decimal comma)
      - thousands separators: "1,000 g" (a comma followed by exactly three
        digits is read as a thousands separator, so "1,500" is 1500, not 1.5)
      - fractions and mixed numbers: "1/2 cup", "1 1/2 cups"
      - unicode fractions: "½ cup", "1½ cups"
      - ranges: "2-3 cloves", "2 – 3", "2—3", "2 to 3 apples", "2 or 3 eggs",
        "1/2-1 tsp"

    Only the quantity at the start is scaled; other numbers in the text are
    left alone. Ingredients with no leading quantity ("salt to taste") and
    quantities with a zero denominator ("1/0") are returned unchanged.

    Known limits (kept simple on purpose): results are always written as
    decimals ("1/3 cup" -> "0.33 cup"), units and plurals are not adjusted,
    and countable items can become fractional ("3 eggs" x1.5 -> "4.5 eggs").

    Ambiguities, resolved by the rules above rather than by guessing:
      - a dash right after a quantity is read as a range when another
        quantity follows it, so "3 1/2-ounce bar" x2 -> "7-ounce bar" (the
        "-ounce" stays), and "2-3" is always a range, never a size like
        "2-inch"; "1-inch piece" is a single quantity ("2-inch piece").
      - a dot is always a decimal point: "1.000 g" (European thousands
        style) is read as 1.0, not 1000.
      - numbers too large to handle safely (e.g. thousands of digits, or a
        result that overflows to infinity) leave the line unchanged.
    """
    match = _QUANTITY_RE.match(ingredient)
    if match is None:
        return ingredient
    try:
        first = _parse_quantity(match["first"])
        second = _parse_quantity(match["second"]) if match["second"] else 0.0
        if first is None or second is None:
            return ingredient
        scaled_first, scaled_second = first * factor, second * factor
    except (ValueError, OverflowError):
        # int() refuses huge digit strings; huge fractions overflow float.
        return ingredient
    for original, value in ((first, scaled_first), (second, scaled_second)):
        # Overflow to inf/nan, or a non-zero amount underflowing to 0.0.
        if not math.isfinite(value) or (original != 0 and value == 0):
            return ingredient
    first, second = scaled_first, scaled_second
    leading = ingredient[: len(ingredient) - len(ingredient.lstrip())]
    scaled = _format_quantity(first)
    if match["second"]:
        scaled += match["sep"] + _format_quantity(second)
    return leading + scaled + ingredient[match.end():]


@app.get("/recipes/{recipe_id}/scaled")
def get_scaled_recipe(recipe_id: int, factor: float = Query(..., gt=0, le=1000)):
    """Return the recipe with every ingredient quantity multiplied by `factor`.

    Read-only: the stored recipe is not changed. `factor` must be > 0 and
    <= 1000 (otherwise 422). Unknown recipe -> 404.
    """
    recipe = get_recipe(recipe_id)
    recipe["ingredients"] = [scale_ingredient(i, factor) for i in recipe["ingredients"]]
    recipe["factor"] = factor
    return recipe


@app.post("/recipes/{recipe_id}/favorite")
def toggle_favorite(recipe_id: int):
    with closing(get_db()) as conn:
        cur = conn.execute(
            "UPDATE recipes SET favorite = 1 - favorite WHERE id = ?", (recipe_id,)
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="unknown recipe")
        row = conn.execute(
            "SELECT * FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
    return _row_to_recipe(row)

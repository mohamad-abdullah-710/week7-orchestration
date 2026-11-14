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
import re
import sqlite3
from contextlib import closing
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


# Leading quantity of an ingredient: "1 1/2", "1/2", "200", "0.5" or "1,5".
_QUANTITY_RE = re.compile(
    r"^\s*(?:(?P<whole>\d+)\s+(?P<num>\d+)/(?P<den>\d+)"
    r"|(?P<fnum>\d+)/(?P<fden>\d+)"
    r"|(?P<dec>\d+(?:[.,]\d+)?))"
)


def _format_quantity(value: float) -> str:
    """Show a number without useless decimals: 400.0 -> "400", 0.25 -> "0.25"."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def scale_ingredient(ingredient: str, factor: float) -> str:
    """Multiply the leading quantity of an ingredient by `factor`.

    "200 g flour" * 2 -> "400 g flour". Fractions ("1/2 cup milk") and mixed
    numbers ("1 1/2 cups sugar") are supported. Ingredients with no leading
    number ("salt to taste") are returned unchanged. Results are rounded to
    2 decimal places.
    """
    match = _QUANTITY_RE.match(ingredient)
    if match is None:
        return ingredient
    if match["whole"] is not None:
        den = int(match["den"])
        if den == 0:
            return ingredient
        amount = int(match["whole"]) + int(match["num"]) / den
    elif match["fnum"] is not None:
        den = int(match["fden"])
        if den == 0:
            return ingredient
        amount = int(match["fnum"]) / den
    else:
        amount = float(match["dec"].replace(",", "."))
    leading = ingredient[: len(ingredient) - len(ingredient.lstrip())]
    return leading + _format_quantity(amount * factor) + ingredient[match.end():]


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

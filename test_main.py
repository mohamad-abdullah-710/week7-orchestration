import sqlite3
import uuid

from fastapi.testclient import TestClient

import main
from main import app, scale_ingredient

client = TestClient(app)


def test_create_and_get_recipe():
    r = client.post(
        "/recipes",
        json={"title": "Pancakes", "ingredients": ["flour", "milk"], "tags": ["breakfast"]},
    )
    assert r.status_code == 200
    rid = r.json()["id"]
    r2 = client.get(f"/recipes/{rid}")
    assert r2.status_code == 200
    assert r2.json()["title"] == "Pancakes"
    assert r2.json()["tags"] == ["breakfast"]


def test_list_recipes():
    client.post("/recipes", json={"title": "Toast"})
    r = client.get("/recipes")
    assert r.status_code == 200
    assert any(rec["title"] == "Toast" for rec in r.json())


def test_unknown_recipe_404():
    r = client.get("/recipes/99999")
    assert r.status_code == 404


def _unique_tag(name: str) -> str:
    # recipes.db is shared between runs, so give each test its own tag.
    return f"{name}-{uuid.uuid4().hex[:8]}"


def test_tag_filter_returns_only_matching():
    tag = _unique_tag("breakfast")
    a = client.post(
        "/recipes", json={"title": "Omelette", "tags": [tag, "eggs"]}
    ).json()
    client.post("/recipes", json={"title": "Soup", "tags": [_unique_tag("dinner")]})
    r = client.get("/recipes", params={"tag": tag})
    assert r.status_code == 200
    assert [rec["id"] for rec in r.json()] == [a["id"]]


def test_tag_filter_no_match_returns_empty_list():
    r = client.get("/recipes", params={"tag": _unique_tag("nothing")})
    assert r.status_code == 200
    assert r.json() == []


def test_no_tag_param_returns_all():
    client.post("/recipes", json={"title": "Salad", "tags": [_unique_tag("lunch")]})
    all_recipes = client.get("/recipes").json()
    assert client.get("/recipes", params={"tag": ""}).json() == all_recipes
    assert any(rec["title"] == "Salad" for rec in all_recipes)


def test_tag_filter_is_case_insensitive():
    tag = _unique_tag("brunch")
    a = client.post("/recipes", json={"title": "Waffles", "tags": [tag]}).json()
    r = client.get("/recipes", params={"tag": tag.upper()})
    assert [rec["id"] for rec in r.json()] == [a["id"]]


def test_new_recipe_is_not_favorite():
    r = client.post("/recipes", json={"title": "Soup"})
    assert r.status_code == 200
    assert r.json()["favorite"] is False
    assert client.get(f"/recipes/{r.json()['id']}").json()["favorite"] is False


def test_toggle_favorite_on_and_off():
    rid = client.post("/recipes", json={"title": "Salad"}).json()["id"]

    r = client.post(f"/recipes/{rid}/favorite")
    assert r.status_code == 200
    assert r.json()["id"] == rid
    assert r.json()["favorite"] is True
    assert client.get(f"/recipes/{rid}").json()["favorite"] is True
    listed = next(rec for rec in client.get("/recipes").json() if rec["id"] == rid)
    assert listed["favorite"] is True

    r = client.post(f"/recipes/{rid}/favorite")
    assert r.status_code == 200
    assert r.json()["favorite"] is False
    assert client.get(f"/recipes/{rid}").json()["favorite"] is False


def test_favorite_unknown_recipe_404():
    r = client.post("/recipes/99999/favorite")
    assert r.status_code == 404


def test_init_db_migrates_old_table_without_favorite(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE recipes (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " title TEXT NOT NULL, ingredients TEXT NOT NULL, tags TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO recipes (title, ingredients, tags) VALUES ('Old', '[]', '[]')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(main, "DB_PATH", db)
    main.init_db()
    main.init_db()  # running twice must not fail

    conn = sqlite3.connect(db)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(recipes)")]
    conn.close()
    assert "favorite" in columns

    rid = client.get("/recipes").json()[0]["id"]
    assert client.get(f"/recipes/{rid}").json()["favorite"] is False
    assert client.post(f"/recipes/{rid}/favorite").json()["favorite"] is True


def test_scaled_recipe_doubles_quantities():
    rid = client.post(
        "/recipes",
        json={
            "title": "Bread",
            "ingredients": ["200 g flour", "1/2 cup milk", "1 1/2 tsp salt", "water"],
            "tags": ["baking"],
        },
    ).json()["id"]
    r = client.get(f"/recipes/{rid}/scaled", params={"factor": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == rid
    assert body["title"] == "Bread"
    assert body["tags"] == ["baking"]
    assert body["factor"] == 2
    assert body["ingredients"] == ["400 g flour", "1 cup milk", "3 tsp salt", "water"]


def test_scaled_recipe_does_not_change_stored_recipe():
    rid = client.post(
        "/recipes", json={"title": "Rice", "ingredients": ["300 g rice"]}
    ).json()["id"]
    assert client.get(f"/recipes/{rid}/scaled", params={"factor": 0.5}).json()[
        "ingredients"
    ] == ["150 g rice"]
    assert client.get(f"/recipes/{rid}").json()["ingredients"] == ["300 g rice"]


def test_scaled_unknown_recipe_404():
    r = client.get("/recipes/99999/scaled", params={"factor": 2})
    assert r.status_code == 404


def test_scaled_rejects_bad_factor():
    rid = client.post("/recipes", json={"title": "Tea"}).json()["id"]
    for bad in ["0", "-1", "abc", "1001"]:
        r = client.get(f"/recipes/{rid}/scaled", params={"factor": bad})
        assert r.status_code == 422, bad
    assert client.get(f"/recipes/{rid}/scaled").status_code == 422


def test_scale_ingredient_formats():
    assert scale_ingredient("200 g flour", 1.5) == "300 g flour"
    assert scale_ingredient("0.5 l milk", 3) == "1.5 l milk"
    assert scale_ingredient("1,5 kg potatoes", 2) == "3 kg potatoes"
    assert scale_ingredient("1/3 cup sugar", 1) == "0.33 cup sugar"
    assert scale_ingredient("2 eggs", 0.5) == "1 eggs"
    assert scale_ingredient("salt to taste", 2) == "salt to taste"
    assert scale_ingredient("", 2) == ""
    assert scale_ingredient("1/0 cup oops", 2) == "1/0 cup oops"

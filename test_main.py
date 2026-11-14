import sqlite3

from fastapi.testclient import TestClient

import main
from main import app

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

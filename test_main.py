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


def test_scale_ingredient_ranges():
    assert scale_ingredient("2-3 cloves garlic", 2) == "4-6 cloves garlic"
    assert scale_ingredient("2 - 3 cloves garlic", 2) == "4 - 6 cloves garlic"
    assert scale_ingredient("2–3 cloves garlic", 2) == "4–6 cloves garlic"
    assert scale_ingredient("2 to 3 apples", 2) == "4 to 6 apples"
    assert scale_ingredient("1/2-1 tsp chili", 2) == "1-2 tsp chili"
    assert scale_ingredient("1 1/2 - 2 cups rice", 2) == "3 - 4 cups rice"
    # "to" that is not followed by a number is not a range
    assert scale_ingredient("2 tomatoes", 2) == "4 tomatoes"
    assert scale_ingredient("1/2-1/0 cup oops", 2) == "1/2-1/0 cup oops"


def test_scale_ingredient_thousands_separator():
    assert scale_ingredient("1,000 g sugar", 2) == "2000 g sugar"
    assert scale_ingredient("1,000.5 g sugar", 2) == "2001 g sugar"
    assert scale_ingredient("12,345,678 grains", 1) == "12345678 grains"
    # a comma followed by 1-2 digits is still a decimal comma
    assert scale_ingredient("1,5 kg potatoes", 2) == "3 kg potatoes"
    assert scale_ingredient("12,25 kg potatoes", 2) == "24.5 kg potatoes"


def test_scale_ingredient_unicode_fractions():
    assert scale_ingredient("1½ cups flour", 2) == "3 cups flour"
    assert scale_ingredient("1 ½ cups flour", 2) == "3 cups flour"
    assert scale_ingredient("½ cup milk", 2) == "1 cup milk"
    assert scale_ingredient("¾ tsp salt", 4) == "3 tsp salt"
    assert scale_ingredient("⅓ cup oil", 3) == "1 cup oil"
    assert scale_ingredient("½-1 tsp chili", 2) == "1-2 tsp chili"


def test_scale_ingredient_small_amounts_never_become_zero():
    assert scale_ingredient("1 pinch salt", 0.001) == "0.001 pinch salt"
    assert scale_ingredient("200 g flour", 1e-9) == "0.0000002 g flour"
    assert scale_ingredient("1 g yeast", 0.0123) == "0.01 g yeast"  # normal 2 dp
    assert scale_ingredient("1 g yeast", 0.00437) == "0.0044 g yeast"  # 2 sig figs
    assert scale_ingredient("0 g sugar", 2) == "0 g sugar"


def test_scaled_endpoint_handles_ranges_and_unicode():
    rid = client.post(
        "/recipes",
        json={"title": "Stew", "ingredients": ["2-3 cloves garlic", "1½ cups stock"]},
    ).json()["id"]
    r = client.get(f"/recipes/{rid}/scaled", params={"factor": 2})
    assert r.status_code == 200
    assert r.json()["ingredients"] == ["4-6 cloves garlic", "3 cups stock"]


def test_scale_ingredient_more_range_separators():
    assert scale_ingredient("2—3 eggs", 2) == "4—6 eggs"  # em dash
    assert scale_ingredient("2 — 3 eggs", 2) == "4 — 6 eggs"
    assert scale_ingredient("2 or 3 eggs", 2) == "4 or 6 eggs"
    # "or"/"to" not followed by a number is not a range
    assert scale_ingredient("2 oranges", 2) == "4 oranges"
    assert scale_ingredient("2 or more eggs", 2) == "4 or more eggs"


def test_scale_ingredient_leading_number_with_hyphen_is_not_a_range():
    assert scale_ingredient("1-inch piece ginger", 2) == "2-inch piece ginger"
    # documented ambiguity: the dash after "1/2" is not followed by a number
    assert scale_ingredient("3 1/2-ounce bar", 2) == "7-ounce bar"
    # documented: a dot is always a decimal point
    assert scale_ingredient("1.000 g sugar", 2) == "2 g sugar"


def test_scale_ingredient_huge_numbers_left_unchanged():
    huge_fraction = "1" * 5000 + "/2 cup sugar"  # int() digit limit
    assert scale_ingredient(huge_fraction, 2) == huge_fraction
    huge_int = "1" * 400 + " g flour"  # float() gives inf
    assert scale_ingredient(huge_int, 2) == huge_int
    huge_den = "1/" + "1" * 400 + " g salt"  # underflows to 0.0
    assert scale_ingredient(huge_den, 2) == huge_den
    # 0.5 * 5e-324 (smallest float) underflows to 0.0: keep the line, not "0 g"
    assert scale_ingredient("0.5 g salt", 5e-324) == "0.5 g salt"
    # a finite value that overflows only after scaling
    big = "1" + "0" * 307 + " g flour"
    assert scale_ingredient(big, 1000) == big


def test_scaled_endpoint_huge_number_does_not_500():
    huge = "1" * 5000 + "/2 cup sugar"
    huge_int = "1" * 400 + " g flour"
    rid = client.post(
        "/recipes",
        json={"title": "Absurd", "ingredients": [huge, huge_int, "200 g butter"]},
    ).json()["id"]
    r = client.get(f"/recipes/{rid}/scaled", params={"factor": 2})
    assert r.status_code == 200
    assert r.json()["ingredients"] == [huge, huge_int, "400 g butter"]

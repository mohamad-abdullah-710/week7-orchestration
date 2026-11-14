import uuid

from fastapi.testclient import TestClient

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

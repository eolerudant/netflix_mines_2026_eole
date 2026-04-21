import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

import db as db_module
from db import init_db

# ---------------------------------------------------------------------------
# Données de test
# ---------------------------------------------------------------------------
GENRES = [
    ("Action",),
    ("Comedy",),
    ("Drama",),
]

FILMS = [
    ("Die Hard", 8.2, 1988, None, None, 1),       # Action
    ("Mad Max", 7.6, 2015, None, None, 1),         # Action
    ("Gladiator", 8.5, 2000, None, None, 1),       # Action
    ("Superbad", 7.6, 2007, None, None, 2),        # Comedy
    ("The Hangover", 7.7, 2009, None, None, 2),    # Comedy
    ("Step Brothers", 6.9, 2008, None, None, 2),   # Comedy
    ("Fight Club", 8.8, 1999, None, None, 3),      # Drama
    ("Forrest Gump", 8.8, 1994, None, None, 3),    # Drama
    ("The Shawshank Redemption", 9.3, 1994, None, None, 3),  # Drama
    ("Inception", 8.8, 2010, None, None, 1),       # Action
]

TEST_USER = {"email": "test@example.com", "pseudo": "tester", "password": "secret123"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _seed_db(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO Genre (Type) VALUES (?)", GENRES)
    conn.executemany(
        "INSERT INTO Film (Nom, Note, DateSortie, Image, Video, Genre_ID) VALUES (?, ?, ?, ?, ?, ?)",
        FILMS,
    )
    conn.commit()


@pytest.fixture(scope="session")
def client():
    """TestClient backed by a temporary SQLite database."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    original_db_path = db_module.DB_PATH
    db_module.DB_PATH = tmp.name

    conn = db_module.get_connection()
    init_db(conn)
    _seed_db(conn)
    conn.close()

    from main import app
    yield TestClient(app, raise_server_exceptions=False)

    db_module.DB_PATH = original_db_path
    os.unlink(tmp.name)


@pytest.fixture(scope="session")
def auth_token(client):
    """Register a user and return the access token."""
    resp = client.post("/auth/register", json=TEST_USER)
    assert resp.status_code == 200
    return resp.json()["access_token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Tests
# ===========================================================================


class TestPing:
    def test_ping(self, client):
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.json()["message"] == "pong"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class TestRegister:
    def test_register_success(self, client):
        resp = client.post("/auth/register", json={
            "email": "new@example.com",
            "pseudo": "newuser",
            "password": "pass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_register_duplicate_email(self, client, auth_token):
        resp = client.post("/auth/register", json=TEST_USER)
        assert resp.status_code == 409

    def test_register_missing_fields(self, client):
        resp = client.post("/auth/register", json={"email": "x@x.com"})
        assert resp.status_code == 422


class TestLogin:
    def test_login_success(self, client, auth_token):
        resp = client.post("/auth/login", json={
            "email": TEST_USER["email"],
            "password": TEST_USER["password"],
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_wrong_password(self, client, auth_token):
        resp = client.post("/auth/login", json={
            "email": TEST_USER["email"],
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_email(self, client):
        resp = client.post("/auth/login", json={
            "email": "ghost@nowhere.com",
            "password": "whatever",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/auth/login", json={"email": "a@b.com"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Genres
# ---------------------------------------------------------------------------
class TestGenres:
    def test_get_genres(self, client):
        resp = client.get("/genres")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

    def test_genres_sorted_by_type(self, client):
        resp = client.get("/genres")
        types = [g["Type"] for g in resp.json()]
        assert types == sorted(types)


# ---------------------------------------------------------------------------
# Films
# ---------------------------------------------------------------------------
class TestFilms:
    def test_get_films_default_pagination(self, client):
        resp = client.get("/films")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert data["total"] == 10
        assert len(data["data"]) == 10

    def test_get_films_custom_pagination(self, client):
        resp = client.get("/films", params={"page": 2, "per_page": 5})
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 5
        assert len(data["data"]) == 5

    def test_get_films_sorted_by_date_desc(self, client):
        resp = client.get("/films")
        dates = [f["DateSortie"] for f in resp.json()["data"]]
        assert dates == sorted(dates, reverse=True)

    def test_get_films_filter_by_genre(self, client):
        # Genre 1 = Action (4 films)
        resp = client.get("/films", params={"genre_id": 1})
        data = resp.json()
        assert data["total"] == 4
        assert all(f["Genre_ID"] == 1 for f in data["data"])

    def test_get_films_filter_nonexistent_genre(self, client):
        resp = client.get("/films", params={"genre_id": 999})
        data = resp.json()
        assert data["data"] == []
        assert data["total"] == 0

    def test_get_films_page_beyond_total(self, client):
        resp = client.get("/films", params={"page": 100})
        assert resp.json()["data"] == []

    def test_get_film_by_id(self, client):
        resp = client.get("/films/1")
        assert resp.status_code == 200
        film = resp.json()
        assert film["ID"] == 1
        assert film["Nom"] == "Die Hard"
        assert "Note" in film
        assert "DateSortie" in film
        assert "Genre_ID" in film

    def test_get_film_not_found(self, client):
        resp = client.get("/films/999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------
class TestPreferences:
    def test_add_preference(self, client, auth_token):
        resp = client.post(
            "/preferences",
            json={"genre_id": 1},
            headers=auth_header(auth_token),
        )
        assert resp.status_code == 201

    def test_add_preference_duplicate(self, client, auth_token):
        resp = client.post(
            "/preferences",
            json={"genre_id": 1},
            headers=auth_header(auth_token),
        )
        assert resp.status_code == 409

    def test_add_preference_no_auth(self, client):
        resp = client.post("/preferences", json={"genre_id": 1})
        assert resp.status_code == 422

    def test_add_preference_invalid_token(self, client):
        resp = client.post(
            "/preferences",
            json={"genre_id": 1},
            headers=auth_header("invalid.token.here"),
        )
        assert resp.status_code == 401

    def test_remove_preference(self, client, auth_token):
        # Add genre 2, then remove it
        client.post("/preferences", json={"genre_id": 2}, headers=auth_header(auth_token))
        resp = client.delete("/preferences/2", headers=auth_header(auth_token))
        assert resp.status_code == 200

    def test_remove_preference_not_found(self, client, auth_token):
        resp = client.delete("/preferences/999", headers=auth_header(auth_token))
        assert resp.status_code == 404

    def test_remove_preference_no_auth(self, client):
        resp = client.delete("/preferences/1")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------
class TestRecommendations:
    def test_recommendations_returns_films(self, client, auth_token):
        # Genre 1 (Action) is already in preferences from TestPreferences
        resp = client.get("/preferences/recommendations", headers=auth_header(auth_token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 5
        assert len(data) > 0
        # All returned films should be Action (genre_id=1)
        for film in data:
            assert film["Genre_ID"] == 1

    def test_recommendations_sorted_by_date(self, client, auth_token):
        resp = client.get("/preferences/recommendations", headers=auth_header(auth_token))
        dates = [f["DateSortie"] for f in resp.json()]
        assert dates == sorted(dates, reverse=True)

    def test_recommendations_no_preferences(self, client):
        # Create a fresh user with no preferences
        resp = client.post("/auth/register", json={
            "email": "nopref@example.com",
            "pseudo": "nopref",
            "password": "pass123",
        })
        token = resp.json()["access_token"]
        resp = client.get("/preferences/recommendations", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_recommendations_no_auth(self, client):
        resp = client.get("/preferences/recommendations")
        assert resp.status_code == 422

    def test_recommendations_max_5(self, client, auth_token):
        # Add all genres as preferences to maximize matching films
        client.post("/preferences", json={"genre_id": 2}, headers=auth_header(auth_token))
        client.post("/preferences", json={"genre_id": 3}, headers=auth_header(auth_token))
        resp = client.get("/preferences/recommendations", headers=auth_header(auth_token))
        assert resp.status_code == 200
        assert len(resp.json()) <= 5

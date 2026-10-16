import app
import pytest

from backend import auth

def test_parse_files_and_unsafe_paths():
    t = "### FILE: a.py\n```python\nx=1\n```\n### FILE: ../evil.py\n```python\nbad\n```\n"
    assert app.parse_files(t) == {"a.py": "x=1\n"}

def test_safe_rejects_traversal():
    with pytest.raises(ValueError): app.safe("../x")
    with pytest.raises(ValueError): app.safe(r"..\outside.py")
    with pytest.raises(ValueError): app.safe(r"C:\outside.py")

def test_parse_json_with_noise():
    assert app.parse_json('here: {"a": 1} thanks') == {"a": 1}

def test_sandbox_runs_real_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "WS", tmp_path); d = tmp_path / "p"; (d / "tests").mkdir(parents=True)
    (d / "conftest.py").write_text(""); (d / "m.py").write_text("def f(): return 2\n")
    (d / "tests" / "test_m.py").write_text("import m\ndef test_ok(): assert m.f()==2\n")
    ok, out = app.run_tests("p"); assert ok, out
    (d / "tests" / "test_m.py").write_text("import m\ndef test_bad(): assert m.f()==3\n")
    ok, out = app.run_tests("p"); assert not ok and "assert" in out

def test_signed_login_session_expires_and_rejects_tampering(monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "test-password")
    monkeypatch.setattr(auth, "AUTH_SECRET", "test-secret-that-is-at-least-32-chars")
    token = auth.create_session("admin", now=100)
    assert auth.session_is_valid(token, now=101)
    assert not auth.session_is_valid(token, now=100 + auth.SESSION_MAX_AGE)
    assert not auth.session_is_valid(token + "x", now=101)

def test_api_requires_login_and_accepts_valid_credentials(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(auth, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "test-password")
    monkeypatch.setattr(auth, "AUTH_SECRET", "test-secret-that-is-at-least-32-chars")
    client = TestClient(app.app)

    assert client.get("/api/config").status_code == 401
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    response = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
    assert response.status_code == 200
    assert response.cookies.get(auth.COOKIE_NAME)
    assert client.get("/api/config").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200

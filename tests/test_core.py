import app
import pytest


def test_parse_files_and_unsafe_paths():
    t = "### FILE: a.py\n```python\nx=1\n```\n### FILE: ../evil.py\n```python\nbad\n```\n"
    assert app.parse_files(t) == {"a.py": "x=1\n"}

def test_safe_rejects_traversal():
    with pytest.raises(ValueError): app.safe("../x")
    with pytest.raises(ValueError): app.safe(r"..\outside.py")
    with pytest.raises(ValueError): app.safe(r"C:\outside.py")

def test_parse_json_with_noise():
    assert app.parse_json('here: {"a": 1} thanks') == {"a": 1}


def test_llm_uses_configured_timeout(monkeypatch):
    from backend import core
    from types import SimpleNamespace

    captured = {}
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 3}},
    )

    def post(url, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return response

    monkeypatch.setattr(core, "PROVIDER", "openai")
    monkeypatch.setattr(core, "LLM_TIMEOUT_SECONDS", 900)
    monkeypatch.setattr(core.httpx, "post", post)
    assert core.llm("system", "user") == ("ok", 3)
    assert captured["timeout"] == 900


def test_sandbox_runs_real_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "WS", tmp_path); d = tmp_path / "p"; (d / "tests").mkdir(parents=True)
    (d / "conftest.py").write_text(""); (d / "m.py").write_text("def f(): return 2\n")
    (d / "tests" / "test_m.py").write_text("import m\ndef test_ok(): assert m.f()==2\n")
    ok, out = app.run_tests("p"); assert ok, out
    (d / "tests" / "test_m.py").write_text("import m\ndef test_bad(): assert m.f()==3\n")
    ok, out = app.run_tests("p"); assert not ok and "assert" in out


# ---------- accounts ----------
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth, mailer  # noqa: E402
from backend.database import q  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_limits():
    auth._hits.clear()


def new_client():
    return TestClient(app.app)


def sign_up(client, name="alice", email="alice@example.com", password="correct-horse"):
    return client.post("/api/auth/register", json={"username": name, "email": email, "password": password})


def test_password_hash_roundtrip():
    stored = auth.hash_password("hunter2-hunter2")
    assert auth.verify_password("hunter2-hunter2", stored)
    assert not auth.verify_password("nope", stored)
    assert stored != auth.hash_password("hunter2-hunter2")  # unique salt


def test_pages_and_api_need_sign_in_but_login_pages_are_open():
    client = new_client()
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200
    assert client.get("/forgot-password").status_code == 200
    assert client.get("/reset-password").status_code == 200
    assert client.get("/dashboard", follow_redirects=False).status_code == 303
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/auth/status").json()["registration_open"] is True


def test_anyone_can_register_and_sign_in_with_username_or_email():
    client = new_client()
    response = sign_up(client, "bob", "bob@example.com")
    assert response.status_code == 200 and client.get("/api/projects").status_code == 200
    client.post("/api/auth/logout")
    fresh = new_client()
    assert fresh.post("/api/auth/login", json={"username": "BOB", "password": "correct-horse"}).status_code == 200
    other = new_client()
    assert other.post("/api/auth/login", json={"username": "bob@example.com", "password": "correct-horse"}).status_code == 200
    assert other.post("/api/auth/login", json={"username": "bob", "password": "wrong"}).status_code == 401


def test_register_validation_and_duplicates():
    client = new_client()
    assert sign_up(client, "x", "x@example.com").status_code == 400
    assert sign_up(client, "carol", "not-an-email").status_code == 400
    assert sign_up(client, "carol", "carol@example.com", "short").status_code == 400
    assert sign_up(client, "carol", "carol@example.com").status_code == 200
    assert sign_up(new_client(), "CAROL", "other@example.com").status_code == 409
    assert sign_up(new_client(), "carol2", "Carol@Example.com").status_code == 409


def test_projects_are_private_per_user():
    a, b = new_client(), new_client()
    sign_up(a, "dana", "dana@example.com")
    sign_up(b, "eric", "eric@example.com")
    pid = "abcdef0123"
    q("insert into projects(id,name,idea,constraints,status,created,user_id) values(?,?,?,?,?,?,?)",
      (pid, "secret", "idea", "", "passed", 1.0, q("select id from users where username='dana'")[0]["id"]))
    assert [p["id"] for p in a.get("/api/projects").json()] == [pid]
    assert b.get("/api/projects").json() == []
    for path in ("", "/file?path=x", "/download"):
        assert b.get(f"/api/projects/{pid}{path}").status_code == 404
    assert b.post(f"/api/projects/{pid}/cancel").status_code == 404
    assert b.delete(f"/api/projects/{pid}").status_code == 404
    assert a.get(f"/api/projects/{pid}").status_code == 200
    assert "user_id" not in a.get(f"/api/projects/{pid}").json()


def test_forgot_and_reset_password_flow(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, text, html: sent.append((to, text)) or True)
    monkeypatch.setattr(mailer, "email_enabled", lambda: True)
    client = new_client()
    sign_up(client, "fay", "fay@example.com", "old-password-1")

    # Unknown emails get the same answer and no mail.
    assert client.post("/api/auth/forgot", json={"email": "ghost@example.com"}).status_code == 200
    import time; time.sleep(0.1)
    assert sent == []

    assert client.post("/api/auth/forgot", json={"email": "FAY@example.com"}).status_code == 200
    for _ in range(50):
        if sent: break
        time.sleep(0.05)
    to, text = sent[0]
    assert to == "fay@example.com"
    token = text.split("token=")[1].split()[0]

    assert client.get("/api/auth/reset/check", params={"token": token}).json() == {"valid": True}
    assert client.get("/api/auth/reset/check", params={"token": "bogus"}).json() == {"valid": False}
    assert client.post("/api/auth/reset", json={"token": token, "password": "short"}).status_code == 400
    assert client.post("/api/auth/reset", json={"token": token, "password": "brand-new-pass"}).status_code == 200
    # The link only works once, the old password is dead, and old sessions are signed out.
    assert client.post("/api/auth/reset", json={"token": token, "password": "another-pass-1"}).status_code == 400
    assert client.get("/api/projects").status_code == 401
    assert new_client().post("/api/auth/login", json={"username": "fay", "password": "old-password-1"}).status_code == 401
    assert new_client().post("/api/auth/login", json={"username": "fay", "password": "brand-new-pass"}).status_code == 200


def test_forgot_without_email_provider_does_not_create_reset_token():
    client = new_client()
    sign_up(client, "lena", "lena@example.com")
    response = client.post("/api/auth/forgot", json={"email": "lena@example.com"})
    user_id = q("select id from users where username='lena'")[0]["id"]
    assert response.json() == {"ok": True, "email_enabled": False}
    assert q("select 1 from password_resets where user_id=?", (user_id,)) == []


def test_expired_reset_token_is_rejected():
    import hashlib, time
    client = new_client()
    sign_up(client, "gus", "gus@example.com")
    uid = q("select id from users where username='gus'")[0]["id"]
    q("insert into password_resets values(?,?,?)", (hashlib.sha256(b"old").hexdigest(), uid, time.time() - 5))
    assert client.post("/api/auth/reset", json={"token": "old", "password": "whatever-123"}).status_code == 400


def test_login_is_rate_limited():
    client = new_client()
    sign_up(client, "hal", "hal@example.com")
    codes = [client.post("/api/auth/login", json={"username": "hal", "password": "bad"}).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8 and codes[8] == 429


def test_session_tampering_and_expiry():
    client = new_client()
    sign_up(client, "ivy", "ivy@example.com")
    user = q("select * from users where username='ivy'")[0]
    token = auth.create_session(user, now=100)
    assert auth.user_from_token(token, now=101)["username"] == "ivy"
    assert auth.user_from_token(token, now=100 + auth.SESSION_MAX_AGE) is None
    assert auth.user_from_token(token + "x", now=101) is None
    assert auth.user_from_token("garbage") is None


def test_active_project_cap(monkeypatch):
    from backend import api
    monkeypatch.setattr(api.core, "pipeline", lambda pid: None)
    client = new_client()
    sign_up(client, "jon", "jon@example.com")
    ok = [client.post("/api/projects", json={"idea": "a thing"}).status_code for _ in range(3)]
    assert ok == [200, 200, 429]

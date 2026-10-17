from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from backend.api import router
from backend.auth import authenticated, authentication_middleware
from backend.settings import ROOT

FRONTEND = ROOT / "frontend"
PAGES = FRONTEND / "templates"
NO_STORE = {"Cache-Control": "no-store"}

app = FastAPI(title="Synapse")
app.middleware("http")(authentication_middleware)
app.include_router(router)
app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


def page(name):
    return FileResponse(PAGES / name, headers=NO_STORE)


def guest_page(name):
    """Pages for people who are signed out; signed-in people go to their workspace."""

    def view(request: Request):
        if authenticated(request):
            return RedirectResponse("/dashboard", status_code=303)
        return page(name)

    return view


app.get("/login", include_in_schema=False)(guest_page("login.html"))
app.get("/register", include_in_schema=False)(guest_page("register.html"))
app.get("/forgot-password", include_in_schema=False)(guest_page("forgot.html"))


@app.get("/reset-password", include_in_schema=False)
def reset_page():
    # Works signed in or out: the link in the email is the credential.
    return page("reset.html")


@app.get("/", include_in_schema=False)
def index(request: Request):
    return RedirectResponse("/dashboard" if authenticated(request) else "/login", status_code=303)


@app.get("/dashboard", include_in_schema=False)
def dashboard(request: Request):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return page("dashboard.html")


@app.get("/healthz", include_in_schema=False)
def health():
    return {"ok": True}

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from backend.api import router
from backend.auth import authenticated, authentication_middleware
from backend.settings import ROOT

FRONTEND = ROOT / "frontend"
app = FastAPI(title="Synapse")
app.middleware("http")(authentication_middleware)
app.include_router(router)
app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(FRONTEND / "templates" / "login.html")


@app.get("/", include_in_schema=False)
def index(request: Request):
    return RedirectResponse("/dashboard" if authenticated(request) else "/login", status_code=303)


@app.get("/dashboard", include_in_schema=False)
def dashboard(request: Request):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(FRONTEND / "templates" / "dashboard.html")

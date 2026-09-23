from fastapi import BackgroundTasks

from .service import AddRequest, RunRequest, SequoiaService
from .strategies import CATALOG


def register_sequoia(app, context):
    service = SequoiaService(context.database, bar_store=getattr(context, "bar_store", None))
    app.state.sequoia = service

    @app.get("/api/sequoia/catalog")
    def catalog():
        return CATALOG

    @app.post("/api/sequoia/runs", status_code=202)
    def start(payload: RunRequest, tasks: BackgroundTasks):
        data = service.start(payload)
        tasks.add_task(service.run, data["run_id"])
        return data

    @app.get("/api/sequoia/runs")
    def history():
        return service.history()

    @app.get("/api/sequoia/runs/{identifier}")
    def result(identifier: str):
        return service.get(identifier)

    @app.post("/api/sequoia/runs/{identifier}/watchlist")
    def add(identifier: str, payload: AddRequest):
        return service.add_watchlist(identifier, payload)

Add to fastapi_app/main.py:

    from fastapi_app.routes.controller import commands as controller_commands

    app.include_router(controller_commands.router)

(alongside the existing netbird_* router includes)
    
No new pip packages needed — `requests` and `sqlalchemy` are already
dependencies of web_app. `starlette` comes bundled with `fastapi`.

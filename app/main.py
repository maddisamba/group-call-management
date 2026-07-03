from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


from app.routers.floors import router
from app.service import FloorService

def create_app():
    app=FastAPI(
        title="Floor Control API",
        description='An API for managing a "floor" in a push-to-talk '
                    "radio group system.",
        version="1.0.0"
    )
    app.state.floor_service=FloorService()
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI returns 422 for validation failures by default, but the
        # spec requires 400 with an ErrorResponse body. This covers:
        # missing userId, blank userId, wrong type, and malformed JSON.
        return JSONResponse(
            status_code=400,
            content={"message": "Invalid request: userId is required"},
        )

    return app


app=create_app()





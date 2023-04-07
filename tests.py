"""
Tests for asgi-server-timing
"""

# standard library
from asyncio import sleep as async_sleep
from time import perf_counter_ns

# API
import pydantic
import fastapi
from fastapi.testclient import TestClient

# asgi-server-timing
from asgi_server_timing import ServerTimingMiddleware, ServerTimingMetric
from asgi_server_timing.middleware import server_timing_metrics_to_dict


fastapi_app: fastapi.FastAPI = fastapi.FastAPI()


calls_to_track = {
    ServerTimingMetric("1deps", "One"): (fastapi.routing.solve_dependencies,),
    ServerTimingMetric("2main", "Two"): (fastapi.routing.run_endpoint_function,),
    ServerTimingMetric("3valid", "Three"): (pydantic.fields.ModelField.validate,),
    ServerTimingMetric("4encode", "Four"): (fastapi.encoders.jsonable_encoder,),
    ServerTimingMetric("5render", "Five"): (
        fastapi.responses.JSONResponse.render,
        fastapi.responses.ORJSONResponse.render,
    ),
    ServerTimingMetric("6profile", "Middleware"): (ServerTimingMiddleware.__call__,),
}

fastapi_app.add_middleware(
    ServerTimingMiddleware,
    calls_to_track=calls_to_track,
    overwrite_behavior='replace',
)


# -----------------------------------------------------------------------------
# ROUTES
# -----------------------------------------------------------------------------
@fastapi_app.get("/")
async def get_index():
    return {"msg": "Hello World"}


@fastapi_app.get("/sleep")
async def get_sleep(sleep_time_seconds: float = 0.5) -> int:
    before = perf_counter_ns()
    await async_sleep(sleep_time_seconds)
    after = perf_counter_ns()
    return after - before


# -----------------------------------------------------------------------------
# TESTS
# -----------------------------------------------------------------------------
test_client: TestClient = TestClient(fastapi_app)


def test_get_index():
    response = test_client.get("/")
    assert response.status_code == 200
    assert response.json() == {"msg": "Hello World"}


def test_get_sleep():
    sleep_time_seconds: float = 0.4
    response = test_client.get(
        url="/sleep",
        params={"sleep_time_seconds": sleep_time_seconds}
    )
    assert response.status_code == 200
    assert isinstance(response.json(), int)
    assert response.json() > int(sleep_time_seconds * 1000000000.0)


def test_get_sleep_headers():
    sleep_time_seconds: float = 0.7
    response = test_client.get(
        url="/sleep",
        params={"sleep_time_seconds": sleep_time_seconds}
    )
    assert response.status_code == 200
    assert response.headers["server-timing"]
    assert server_timing_metrics_to_dict(response.headers["server-timing"])

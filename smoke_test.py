"""
"""

# standard library
from asyncio import sleep as async_sleep
from time import perf_counter_ns

# API
import fastapi
import pydantic

# asgi-server-timing
from asgi_server_timing import ServerTimingMiddleware, ServerTimingMetric

fastapi_app: fastapi.FastAPI = fastapi.FastAPI()


@fastapi_app.get("/")
async def context_id_endpoint():
	before = perf_counter_ns()
	await async_sleep(0.5)
	after = perf_counter_ns()

	return after - before


track = {
	ServerTimingMetric("1deps", "One"): (fastapi.routing.solve_dependencies,),
	ServerTimingMetric("2main", "Two"): (fastapi.routing.run_endpoint_function,),
	ServerTimingMetric("3valid", "Three"): (pydantic.fields.ModelField.validate,),
	ServerTimingMetric("4encode", "Four"): (fastapi.encoders.jsonable_encoder,),
	ServerTimingMetric("5render", "Five"): (
		fastapi.responses.JSONResponse.render,
		fastapi.responses.ORJSONResponse.render,
	),
	# ServerTimingMetric("6profile", "Middleware"): (asgi_server_timing.ServerTimingMiddleware.__call__,),
}

fastapi_app.add_middleware(ServerTimingMiddleware, calls_to_track=track, overwrite_behavior='replace')

if __name__ == '__main__':
	import uvicorn
	uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

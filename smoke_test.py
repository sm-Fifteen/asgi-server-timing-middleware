import fastapi
import pydantic
from fastapi import FastAPI
from asyncio import sleep as async_sleep
from time import perf_counter_ns

from asgi_server_timing import ServerTimingMiddleware

fastapi_app = fastapi.FastAPI()

@fastapi_app.get("/")
async def context_id_endpoint():
	before = perf_counter_ns()
	await async_sleep(0.5)
	after = perf_counter_ns()

	return after - before


track = {
	"1deps": (fastapi.routing.solve_dependencies,),
	"2main": (fastapi.routing.run_endpoint_function,),
	"3valid": (pydantic.fields.ModelField.validate,),
	"4encode": (fastapi.encoders.jsonable_encoder,),
	"5render": (
		fastapi.responses.JSONResponse.render,
		fastapi.responses.ORJSONResponse.render,
	),
}

fastapi_app.add_middleware(ServerTimingMiddleware, calls_to_track=track)

if __name__ == '__main__':
	import uvicorn
	uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

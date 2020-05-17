ASGI Server-Timing middleware
====

An ASGI middleware that wraps the excellent [yappi profiler][yappi] to let you
measure the execution time of any function or coroutine in the context of
an HTTP request, and return it as a standard [`Server-Timing` HTTP header][server-timing].


[yappi]:https://github.com/sumerc/yappi
[server-timing]:https://w3c.github.io/server-timing/

Sample configurations
----

Here are some example configurations for various frameworks and libraries.
Feel free to combine them as needed.

### FastAPI

```py
fastapi_app.add_middleware(ServerTimingMiddleware, calls_to_track={
	"1deps": (fastapi.routing.solve_dependencies,),
	"2main": (fastapi.routing.run_endpoint_function,),
	"3valid": (pydantic.fields.ModelField.validate,),
	"4encode": (fastapi.encoders.jsonable_encoder,),
	"5render": (
		fastapi.responses.JSONResponse.render,
		fastapi.responses.ORJSONResponse.render,
	),
})
```

### Starlette

```py
from starlette.middleware import Middleware

middleware = [
  Middleware(ServerTimingMiddleware, calls_to_track={
	  # TODO: ...
  }),
]

starlette_app = Starlette(routes=routes, middleware=middleware)
```

### SQLAlchemy

```py
fastapi_app.add_middleware(ServerTimingMiddleware, calls_to_track={
	"db_exec": (sqlalchemy.engine.base.Engine.execute,),
	"db_fetch": (
		sqlalchemy.engine.ResultProxy.fetchone,
		sqlalchemy.engine.ResultProxy.fetchmany,
		sqlalchemy.engine.ResultProxy.fetchall,
	),
})
```

### More Frameworks

Feel free to submit PRs containing examples for more libraries and ASGI frameworks.

Caveats
----

* Only the end-to-end time is reported for both functions and coroutines,
so it's not possible to tell from the metrics when a coroutine took a long
time because the event loop thread got stalled
(though [`asyncio`'s debug mode][asyncio-dev] can help).
* The profiler's memory is not freed over time, and only gets cleared when
it exceeds a given threshold (50MB by default). When memory gets cleared,
data collected for all ongoing requests is lost, so the timing for these
will be incorrect.
* Executing the same task multiple times in parallel (such as with
`asyncio.gather()`) will report the duration as if they had been
executed sequentially.
* The minimum version of Python supported is 3.7, since this middleware
makes use of [PEP 567 context variables][contextvars] to track which
function call belongs to which request, and the 
[Python 3.6 backport][contextvars36] doesn't have asyncio support.

[asyncio-dev]:https://docs.python.org/3/library/asyncio-dev.html
[contextvars]:https://www.python.org/dev/peps/pep-0567/
[contextvars36]:https://pypi.org/project/contextvars/

Special Thanks
====
* Sümer Cip (@sumerc), for creating and maintaininng yappi, as well as being
very responsive and open to adding all the new features needed to make this work.
* David Montague (@dmontagu) for his involvement in shaping this middleware
at every step of the way.

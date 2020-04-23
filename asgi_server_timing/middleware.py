from contextvars import ContextVar
from typing import Dict, Tuple, Callable
import inspect
import re

import yappi
from yappi import YFuncStats

_yappi_ctx_tag: ContextVar[int] = ContextVar('_yappi_ctx_tag', default=-1)

def _get_context_tag() -> int:
	return _yappi_ctx_tag.get()

class ServerTimingMiddleware:
	"""Timing middleware for ASGI HTTP applications

	The resulting profiler data will be returned through the standard
	`Server-Timing` header for all requests.

	Args:
		app (ASGI v3 callable): An ASGI application

		calls_to_track (Dict[str,Tuple[Callable]]): A dict of functions
			keyed by desired output metric name.
			
			Metric names must consist of a single rfc7230 token

		max_profiler_mem (int): Memory threshold (in bytes) at which yappi's
			profiler memory gets cleared.

	.. _Server-Timing sepcification:
		https://w3c.github.io/server-timing/#the-server-timing-header-field
	"""

	def __init__(self, app, calls_to_track: Dict[str, Tuple[Callable]], max_profiler_mem: int = 50_000_000):
		for metric_name, profiled_functions in calls_to_track.items():
			if len(metric_name) == 0:
				raise ValueError('A Server-Timing metric name cannot be empty')

			# https://httpwg.org/specs/rfc7230.html#rule.token.separators
			# USASCII (7 bits), only visible characters (no non-printables or space), no double-quote or delimiter
			if not metric_name.isascii() or not metric_name.isprintable() or re.search(r'[ "(),/:;<=>?@\[\\\]{}]', metric_name) is not None:
				raise ValueError('"{}" contains an invalid character for a Server-Timing metric name'.format(metric_name))

			if not all(inspect.isfunction(profiled) for profiled in profiled_functions):
				raise TypeError('One of the targeted functions for key "{}" is not a function'.format(metric_name))

		self.app = app
		self.calls_to_track = {name: list(tracked_funcs) for name, tracked_funcs in calls_to_track.items()}
		self.max_profiler_mem = max_profiler_mem

		yappi.set_tag_callback(_get_context_tag)
		yappi.set_clock_type("wall")

		yappi.start()

	async def __call__(self, scope, receive, send):
		ctx_tag = id(scope)
		_yappi_ctx_tag.set(ctx_tag)

		def wrapped_send(response):
			if response['type'] == 'http.response.start':
				tracked_stats: Dict[str, YFuncStats] = {
					name: yappi.get_func_stats(
						filter=dict(tag=ctx_tag),
						filter_callback=lambda x: yappi.func_matches(x, tracked_funcs)
					)
					for name, tracked_funcs in self.calls_to_track.items()
				}

				# NOTE (sm15): Might need to be altered to account for various edge-cases
				timing_ms = {
					name: sum(x.ttot for x in stats) * 1000
					for name, stats in tracked_stats.items()
					if not stats.empty()
				}

				server_timing = ','.join([
					f"{name};dur={duration_ms:.3f}"
					for name, duration_ms in timing_ms.items()
				]).encode('ascii')

				if server_timing:
					# FIXME: Doesn't check if a server-timing header is already set
					response['headers'].append([b'server-timing', server_timing])

				if yappi.get_mem_usage() >= self.max_profiler_mem:
					yappi.clear_stats()

			return send(response)

		await self.app(scope, receive, wrapped_send)

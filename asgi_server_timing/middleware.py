from contextvars import ContextVar
from typing import Dict
import re
from ctypes import c_long

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

		calls_to_track (Dict[str,str]): A dict of qualified function names
			keyed by desired output metric name.
			
			Metric names must consist of a single rfc7230 token
			and qualified function names can be obtained with
			`my_function.__qualname__` for both functions and coroutines.

	.. _Server-Timing sepcification:
		https://w3c.github.io/server-timing/#the-server-timing-header-field
	"""

	def __init__(self, app, calls_to_track: Dict[str, str]):
		for metric_name in calls_to_track.keys():
			# https://httpwg.org/specs/rfc7230.html#rule.token.separators
			# USASCII (7 bits), only visible characters (no non-printables or space), no double-quote or delimiter
			if not metric_name.isascii() or not metric_name.isprintable() or re.search(r'[ "(),/:;<=>?@\[\\\]{}]', metric_name) is not None:
				# TODO: length == 0
				raise ValueError('"{}" contains an invalid character for a Server-Timing metric name'.format(metric_name))

		self.app = app
		self.calls_to_track = calls_to_track

		yappi.set_tag_callback(_get_context_tag)
		yappi.set_clock_type("wall")

		# TODO: Schedule some kind of periodic profiler cleanup with clear_stats()
		yappi.start()

	async def __call__(self, scope, receive, send):
		ctx_tag = id(scope)
		# Longs on Windows are only 32 bits, but memory adresses on 64 bit python are 64 bits
		ctx_tag = abs(c_long(ctx_tag).value) # Ensure it fits inside a long, truncating if necessary
		_yappi_ctx_tag.set(ctx_tag)

		def wrapped_send(response):
			if response['type'] == 'http.response.start':
				yappi.get_func_stats({"tag": ctx_tag}).sort('ttot', sort_order="asc").debug_print()

				tracked_stats: Dict[str, YFuncStats] = {
					name: yappi.get_func_stats({"name": call_to_track, "tag": ctx_tag})
					for name, call_to_track in self.calls_to_track.items()
				}

				server_timing = [
					f"{name};dur={(stats.pop().ttot * 1000):.3f}".encode('ascii')
					for name, stats in tracked_stats.items()
					if not stats.empty()
				]

				if server_timing:
					# FIXME: Doesn't check if a server-timing header is already set
					response['headers'].append(["server-timing", b','.join(server_timing)])

			return send(response)

		await self.app(scope, receive, wrapped_send)

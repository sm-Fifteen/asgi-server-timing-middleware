"""
"""

# standard library
from contextvars import ContextVar
from re import search, Pattern, compile
from inspect import isfunction, ismethod
from typing import Any, Callable, Dict, Iterable, List

# yappi
import yappi
from yappi import YFuncStats

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------
_re_pattern_invalid_characters: Pattern = compile(r'[ "(),/:;<=>?@\[\\\]{}]')
_yappi_ctx_tag: ContextVar[int] = ContextVar('_yappi_ctx_tag', default=-1)


# -----------------------------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def _get_context_tag() -> int:
	return _yappi_ctx_tag.get()


# -----------------------------------------------------------------------------
# MIDDLEWARE
# -----------------------------------------------------------------------------
class ServerTimingMiddleware:
	"""Timing middleware for ASGI HTTP applications

	The resulting profiler data will be returned through the standard
	`Server-Timing` header for all requests.

	.. _Server-Timing specification:
		https://w3c.github.io/server-timing/#the-server-timing-header-field
	"""

	@staticmethod
	def is_function(function: Any) -> bool:
		"""
		Args:
			function:

		Returns:
		"""
		return (
			isfunction(function)
			or ismethod(function)
			or type(function).__name__ == 'cython_function_or_method'
		)

	@staticmethod
	def _validate_metric_name(metric_name: str) -> bool:
		"""
		Validates whether a metric name conforms to the following requirements:

		- USASCII (7 bits)
		- only visible characters (no non-printable characters or space)
		- no double-quote or delimiter

		For more information, please refer to IETF RFC 7230, Section 3.2.6:
		https://httpwg.org/specs/rfc7230.html#rule.token.separators

		Args:
			metric_name (str):

		Returns:
			A boolean indicating whether or not
		"""
		return (
			not metric_name.isascii()
			or not metric_name.isprintable()
			or search(_re_pattern_invalid_characters, metric_name) is not None
		)

	@staticmethod
	def _validate_profile_target(profiled_functions: Iterable[Callable]) -> None:
		"""
		Raises:

		Returns:
			None
		"""

	def __init__(
		self,
		app,
		calls_to_track: Dict[str, Iterable[Callable]],
		max_profiler_mem: int = 50_000_000,
		overwrite: bool = True,
	):
		"""
		Args:
			app (ASGI v3 callable):
				An ASGI application.

			calls_to_track (Dict[str, Iterable[Callable]]):
				A dict of functions keyed by desired output metric name.
				Metric names must consist of a single rfc7230 token

			max_profiler_mem (int):
				Memory threshold (in bytes) at which yappi's profiler memory gets cleared.

			overwrite (bool):
				Whether or not to overwrite an extant Server-Timing header.
				If set to False, new values will be appended to the extant header.
				Defaults to True.
		"""
		for metric_name, profiled_functions in calls_to_track.items():
			if not metric_name:
				raise ValueError('A Server-Timing metric name cannot be empty')

			if self._validate_metric_name(metric_name=metric_name):
				raise ValueError(
					f'"{metric_name}" contains an invalid character'
					f' for a Server-Timing metric name'
				)

			non_functions: List = [
				profiled
				for profiled in profiled_functions
				if not self.is_function(profiled)
			]

			if len(non_functions) == 1:
				raise TypeError(
					f'The target "{non_functions[0]}"'
					f' for key "{metric_name}" is not a function'
				)
			elif non_functions:
				raise TypeError(
					f'The targets {non_functions}'
					f' for key "{metric_name}" are not functions'
				)

		self.app = app
		self.calls_to_track: Dict[str, List[Callable]] = {
			name: list(tracked_funcs)
			for name, tracked_funcs in calls_to_track.items()
		}
		self.max_profiler_mem: int = max_profiler_mem
		self.overwrite: bool = overwrite

		yappi.set_tag_callback(_get_context_tag)
		yappi.set_clock_type('wall')

		yappi.start()

	async def __call__(self, scope, receive, send):
		ctx_tag = id(scope)
		_yappi_ctx_tag.set(ctx_tag)

		def wrapped_send(response):
			if response['type'] == 'http.response.start':
				tracked_stats: Dict[str, YFuncStats] = {
					name: yappi.get_func_stats(
						filter=dict(tag=ctx_tag),
						filter_callback=lambda stat: yappi.func_matches(stat, tracked_funcs)
					)
					for name, tracked_funcs in self.calls_to_track.items()
				}

				# NOTE (sm15): Might need to be altered to account for various edge-cases
				timing_ms: Dict[str, float] = {
					name: sum(x.ttot for x in stats) * 1000
					for name, stats in tracked_stats.items()
					if not stats.empty()
				}

				server_timing = ','.join([
					f'{name};dur={duration_ms:.3f}'
					for name, duration_ms in timing_ms.items()
				]).encode('ascii')

				if server_timing:
					if self.overwrite:
						response['headers'].append([b'server-timing', server_timing])
					else:
						for i, header in enumerate(response['headers']):
							if header[0] == b'server-timing':
								response['headers'][i][1] += (b',' + server_timing)

				if yappi.get_mem_usage() >= self.max_profiler_mem:
					yappi.clear_stats()

			return send(response)

		await self.app(scope, receive, wrapped_send)

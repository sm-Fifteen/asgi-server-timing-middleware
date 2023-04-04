"""
asgi_server_timing.middleware

An ASGI middleware that wraps the excellent yappi profiler to let you measure the execution time of any function or
coroutine in the context of an HTTP request, and return it as a standard Server-Timing HTTP header.

LICENSE: CC0 1.0 Universal.
"""

# standard library
from dataclasses import dataclass
from contextvars import ContextVar
from collections import defaultdict
from re import search, Pattern, compile
from inspect import isfunction, ismethod
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Iterable,
    List,
    Literal,
    Optional,
    Union,
    Tuple,
)

# yappi
import yappi

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
# CLASSES
# -----------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class _ServerTimingMetricName:
    """
    https://w3c.github.io/server-timing/#the-server-timing-header-field

    Params:
        name (str):
            A short name for the Server-Timing metric. This name must adhere to
            IETF RFC 7230.

        description (Optional[str]):
            A description for the Server-Timing metric. This will be returned
            as a quoted string, and therefore special characters are permitted.
    """
    name: str
    description: Optional[str] = None

    def __post_init__(self):
        """
        Validates `name` and `description`.

        Validates whether a metric name conforms to the following requirements:

        - US-ASCII (7 bits)
        - only visible characters (no non-printable characters or spaces)
        - no double-quotes or delimiters

        For more information, please refer to IETF RFC 7230, Section 3.2.6:
        https://httpwg.org/specs/rfc7230.html#rule.token.separators

        """
        if (
            self.description is not None
            and not isinstance(self.description, str)
        ):
            raise TypeError(
                'Argument to parameter `description` must be of types `str` or `None`.'
                f' Received: {type(self.description)}.'
            )

        if not isinstance(self.name, str):
            raise TypeError(
                'Argument to parameter `name` must be of type `str`.'
                f' Received: {type(self.name)}.'
            )

        if not self.name.isascii():
            raise ValueError('Argument to parameter `name` must be comprised of US-ASCII characters.')

        if not self.name.isprintable():
            raise ValueError('Argument to parameter `name` must be printable.')

        if search(_re_pattern_invalid_characters, self.name):
            raise ValueError('Argument to parameter `name` cannot contain special characters.')


@dataclass(slots=True, frozen=True)
class ServerTimingMetric(_ServerTimingMetricName):
    """
    https://w3c.github.io/server-timing/#the-server-timing-header-field

    Params:
        name (str):
            A short name for the Server-Timing metric. This name must adhere to
            IETF RFC 7230.

        description (Optional[str]):
            A description for the Server-Timing metric. This will be returned
            as a quoted string, and therefore special characters are permitted.

        duration (Optional[float]):

    """

    duration: Optional[float] = None

    def __post_init__(self):
        if (
            self.duration is not None
            and not isinstance(self.duration, float)
        ):
            raise TypeError(
                'Argument to parameter `duration` must be of types `float` or `None`.'
                f' Received: {type(self.duration)}.'
            )

    def to_optional_value_dict(self) -> Dict:
        value = {}
        if self.duration is not None:
            value['dur'] = self.duration
        if self.description is not None:
            value['desc'] = self.description
        return value

    def to_header_string(self) -> str:
        """
        Serializes this object in a format suitable for the Server-Timing header.
        `<name>;dur=<duration>;desc=<description>`

        Returns:
            A formatted header string.
        """
        metric: str = self.name
        if self.duration is not None:
            metric = f'{metric};dur={self.duration:.3f}'
        if self.description is not None:
            metric = f'{metric};desc="{self.description}"'
        return metric

    def to_header_bytes(self) -> bytes:
        """
        Serializes this object in a format suitable for the Server-Timing header.
        `<name>;dur=<duration>;desc=<description>`

        Returns:
            An ASCII-encoded byte string.
        """
        return self.to_header_string().encode('ascii')


class ServerTimingHeaderField(defaultdict):

    def __init__(self):
        super().__init__(dict)

    def to_header_field_string(self) -> str:

        def format_metric(key, value) -> str:
            _metric: str = key
            for parameter, v in value.items():
                if parameter == 'dur':
                    _metric = f'{_metric};dur={v}'
                elif parameter == 'desc':
                    _metric = f'{_metric};desc={v}'
            return _metric

        return ','.join(
            format_metric(key, value)
            for key, value in self.items()
        )

    def to_header_field_bytes(self) -> bytes:
        return self.to_header_field_string().encode('ascii')


def server_timing_metrics_to_dict(header_field: str) -> ServerTimingHeaderField:
    server_timing_header_field = ServerTimingHeaderField()
    for metric in header_field.split(','):
        parameters = metric.split(';')
        name = parameters[0]
        for parameter in parameters[1:]:
            key, value = parameter.split('=')
            server_timing_header_field[name][key] = value
    return server_timing_header_field


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
        Determine if a value is a function, method, or cython_function_or_method.

        Args:
            function: Any value.

        Returns:
            True if the argument to the function parameter is one of
                {function, method, cython_function_or_method}. False otherwise.
        """
        return (
            isfunction(function)
            or ismethod(function)
            or type(function).__name__ == 'cython_function_or_method'
        )

    def __init__(
        self,
        app,
        calls_to_track: Dict[ServerTimingMetric, Iterable[Callable]],
        max_profiler_mem: int = 50_000_000,
        overwrite_behavior: Optional[Literal['replace', 'retain']] = None,
    ):
        """
        Args:
            app (ASGI v3 callable):
                An ASGI application.

            calls_to_track (Dict[str, Iterable[Callable]]):
                A dict of functions keyed by ServerTimingMetrics.
                ServerTimingMetric objects validate an output name and optional
                description in accordance with IETF RFC 7230.

            max_profiler_mem (int):
                Memory threshold (in bytes) at which yappi's profiler memory
                gets cleared.

            overwrite_behavior (Optional[Literal['replace', 'retain']]):
                "replace" or "retain". Defaults to None.

                Section 3, "The Server-Timing Header Field", of the W3C
                Server-Timing specification reads as follows:
                
                    "To avoid any possible ambiguity, individual
                    server-timing-param-names SHOULD NOT appear multiple times 
                    within a server-timing-metric. If any server-timing-param-name 
                    is specified more than once, only the first instance is to
                    be considered, even if the server-timing-param is incomplete
                    or invalid."

                The overwrite_behavior parameter grants flexibility in handling
                duplicate metrics.

                A string value of "replace" will ignore existing duplicate
                server-timing-params, replacing any with this middleware
                execution's value.

                A string value of "retain" will retain existing metrics, ignoring
                new duplicates generated by this middleware's execution.

                There is no defined behavior for partially updating an existing
                metric (merging it with a new field). That is, if existing metric
                `a` has a description but no duration, and new metric `a` has a
                duration but no description, then these values will not be merged.
                "retain" will retain the existing `a;desc="..."` and "replace"
                will replace it with `a;dur=...`.

                Arguments whose boolean truthiness evaluates to False
                (None, False, an empty string, etc.) will not modify existing
                Server-Timing response headers all, with the end effect of this
                middleware's execution being moot. No new metrics will be added
                to an existing Server-Timing header field.
        """
        for key, callables in calls_to_track.items():
            non_functions: List = [
                profiled
                for profiled in callables
                if not self.is_function(profiled)
            ]

            if len(non_functions) == 1:
                raise TypeError(
                    f'The target "{non_functions[0]}"'
                    f' for key "{key.name}" is not a function'
                )
            elif non_functions:
                raise TypeError(
                    f'The targets {non_functions}'
                    f' for key "{key.name}" are not functions'
                )

        self.app = app
        self.calls_to_track: Dict[str, List[Callable]] = {
            key: list(callables)
            for key, callables in calls_to_track.items()
        }
        self.max_profiler_mem: int = max_profiler_mem

        if overwrite_behavior:
            if isinstance(overwrite_behavior, str):
                if (
                    overwrite_behavior != 'replace'
                    and overwrite_behavior != 'retain'
                ):
                    raise AttributeError(
                        'Argument to parameter "overwrite_behavior" must be one'
                        ' of "replace", "retain", or {None, False, "", etc.}'
                    )
        self.overwrite_behavior: Optional[str] = overwrite_behavior

        yappi.set_tag_callback(_get_context_tag)
        yappi.set_clock_type('wall')
        yappi.start()

    async def __call__(self, scope, receive, send):
        ctx_tag = id(scope)
        _yappi_ctx_tag.set(ctx_tag)

        def wrapped_send(response: Dict[str, Union[str, int, List[Tuple[bytes, bytes]]]]):
            """
            Args:
                response (dict):
                    A dictionary representing a Starlette Response.
                    Note that this is not a Starlette Response type.

            Example:
                response = {
                    'type': 'http.response.start',
                    'status': 200,
                    'headers': [
                        (b'content-length', b'9'),
                        (b'content-type', b'application/json')
                    ]
                } is of type <class 'dict'>, not Starlette Response
            """

            if response['type'] == 'http.response.start':
                tracked_stats: Dict[_ServerTimingMetricName, yappi.YFuncStats] = {
                    key: yappi.get_func_stats(
                        filter={'tag': ctx_tag},
                        filter_callback=lambda stat: yappi.func_matches(stat, callables)
                    )
                    for key, callables in self.calls_to_track.items()
                }

                performances: Generator[ServerTimingMetric, None, None] = (
                    ServerTimingMetric(
                        name=key.name,
                        description=key.description,
                        duration=sum(stat.ttot for stat in stats) * 1000
                    )
                    for key, stats in tracked_stats.items()
                    if not stats.empty()
                )

                if performances:
                    headers: Dict[bytes, bytes] = dict(response['headers'])
                    field: Optional[bytes] = headers.get(b'server-timing')
                    if field:
                        sthf: ServerTimingHeaderField = server_timing_metrics_to_dict(str(field))

                        if not self.overwrite_behavior:
                            pass

                        elif self.overwrite_behavior == 'replace':
                            for performance in performances:
                                sthf[performance.name] = performance.to_optional_value_dict()

                        elif self.overwrite_behavior == 'retain':
                            for performance in performances:
                                if not sthf.get(performance.name):
                                    sthf[performance.name] = performance.to_optional_value_dict()

                        headers[b'server-timing'] = sthf.to_header_field_bytes()
                        response['headers'] = [(k, v) for k, v in headers.items()]
                    else:
                        server_timing = ','.join(
                            performance.to_header_string()
                            for performance in performances
                        ).encode('ascii')
                        response['headers'].append((b'server-timing', server_timing))

                if yappi.get_mem_usage() >= self.max_profiler_mem:
                    yappi.clear_stats()

            return send(response)

        await self.app(scope, receive, wrapped_send)

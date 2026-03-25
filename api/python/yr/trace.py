# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
OpenTelemetry Tracing API for YuanRong.

This module provides distributed tracing capabilities using OpenTelemetry.
Spans can be created to track operations across function boundaries.

Example:
    >>> import yr
    >>> from yr import trace
    >>>
    >>> config = yr.Config(enable_trace=True)
    >>> yr.init(config)
    >>>
    >>> # Get a tracer
    >>> tracer = trace.get_tracer(__name__)
    >>>
    >>> # Create a span
    >>> with tracer.start_as_current_span("my_operation"):
    ...     # Do some work
    ...     pass
"""

import functools
from typing import Any, Callable, Dict, Optional, Union

from yr.runtime_holder import global_runtime


class Span:
    """
    A span represents a single operation within a trace.

    Spans can be nested to form a trace tree, showing the causal
    relationships between operations in a distributed system.

    Args:
        name (str): The name of the span.
        attributes (Dict[str, str], optional): Initial attributes to set on the span.

    Example:
        >>> import yr
        >>> from yr import trace
        >>>
        >>> config = yr.Config(enable_trace=True)
        >>> yr.init(config)
        >>>
        >>> @yr.instance
        ... class MyActor:
        ...     def __init__(self):
        ...         self.tracer = trace.get_tracer("my_app")
        ...
        ...     def process(self, data):
        ...         with self.tracer.start_as_current_span("process"):
        ...             # Processing logic
        ...             return data
    """

    def __init__(self, name: str, attributes: Optional[Dict[str, str]] = None):
        self._name = name
        self._attributes = attributes or {}
        self._context_manager_depth = 0

    def set_attribute(self, key: str, value: Union[str, int, float, bool]) -> None:
        """
        Set an attribute on the span.

        Attributes are key-value pairs that provide additional
        metadata about the operation being traced.

        Args:
            key (str): The attribute key.
            value (Union[str, int, float, bool]): The attribute value.

        Example:
            >>> span.set_attribute("user.id", "12345")
            >>> span.set_attribute("http.status_code", 200)
            >>> span.set_attribute("cache.hit", True)
        """
        self._attributes[key] = str(value)

    def set_attributes(self, attributes: Dict[str, Union[str, int, float, bool]]) -> None:
        """
        Set multiple attributes on the span.

        Args:
            attributes (Dict[str, Union[str, int, float, bool]]): Attributes to set.

        Example:
            >>> span.set_attributes({
            ...     "user.id": "12345",
            ...     "http.method": "GET",
            ...     "http.status_code": 200
            ... })
        """
        for key, value in attributes.items():
            self._attributes[key] = str(value)

    def add_event(self, name: str, attributes: Optional[Dict[str, str]] = None) -> None:
        """
        Add an event to the span.

        Events are timed annotations within a span, useful for
        marking specific points in time during an operation.

        Args:
            name (str): The event name.
            attributes (Dict[str, str], optional): Event attributes.

        Example:
            >>> span.add_event("cache.miss", {"key": "user:12345"})
        """
        # Events are stored as special attributes with timestamp prefix
        import time
        event_key = f"event.{int(time.time() * 1000)}.{name}"
        if attributes:
            for k, v in attributes.items():
                self._attributes[f"{event_key}.{k}"] = str(v)

    def record_exception(self, exception: Exception) -> None:
        """
        Record an exception on the span.

        Args:
            exception (Exception): The exception to record.

        Example:
            >>> try:
            ...     risky_operation()
            ... except Exception as e:
            ...     span.record_exception(e)
            ...     raise
        """
        self._attributes["exception.type"] = type(exception).__name__
        self._attributes["exception.message"] = str(exception)

    def __enter__(self):
        self._context_manager_depth += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._context_manager_depth -= 1
        if exc_type is not None:
            self.record_exception(exc_val)
        return False


class Tracer:
    """
    Tracer is the entry point for creating spans.

    Tracers are typically created per module or component and
    are named after the component they trace.

    Args:
        name (str): The tracer name, typically the module name.

    Example:
        >>> tracer = trace.get_tracer(__name__)
        >>> tracer = trace.get_tracer("my_component")
    """

    def __init__(self, name: str):
        self._name = name

    def start_as_current_span(self, name: str, attributes: Optional[Dict[str, str]] = None) -> Span:
        """
        Start a new span and make it the current span.

        This is the primary method for creating spans. Returns a
        Span object that should be used as a context manager.

        Args:
            name (str): The span name.
            attributes (Dict[str, str], optional): Initial attributes.

        Returns:
            Span: A new span object.

        Example:
            >>> with tracer.start_as_current_span("database_query"):
            ...     # Execute query
            ...     results = db.execute("SELECT * FROM users")
        """
        return Span(name=name, attributes=attributes)

    def start_span(self, name: str, attributes: Optional[Dict[str, str]] = None) -> Span:
        """
        Start a new span without making it the current span.

        Use this when you want to create a span but not use it
        as a context manager.

        Args:
            name (str): The span name.
            attributes (Dict[str, str], optional): Initial attributes.

        Returns:
            Span: A new span object.

        Example:
            >>> span = tracer.start_span("background_task")
            >>> span.set_attribute("task.id", "12345")
            >>> # Use span explicitly
            >>> span.add_event("task.completed")
        """
        return Span(name=name, attributes=attributes)


# Global tracer registry
_tracers: Dict[str, Tracer] = {}


def get_tracer(name: str) -> Tracer:
    """
    Get or create a tracer with the given name.

    Tracers are cached and reused for the same name.

    Args:
        name (str): The tracer name, typically the module name using `__name__`.

    Returns:
        Tracer: A tracer instance.

    Example:
        >>> import yr
        >>> from yr import trace
        >>>
        >>> config = yr.Config(enable_trace=True)
        >>> yr.init(config)
        >>>
        >>> tracer = trace.get_tracer(__name__)
        >>> with tracer.start_as_current_span("operation"):
        ...     pass
    """
    if name not in _tracers:
        _tracers[name] = Tracer(name)
    return _tracers[name]


def in_context_span(span_name: str, attributes: Optional[Dict[str, str]] = None):
    """
    Decorator to wrap a function in a span.

    The span name defaults to the function name if not specified.

    Args:
        span_name (str): The span name. If None, uses the function name.
        attributes (Dict[str, str], optional): Initial attributes for the span.

    Example:
        >>> import yr
        >>> from yr import trace
        >>>
        >>> config = yr.Config(enable_trace=True)
        >>> yr.init(config)
        >>>
        >>> @trace.in_context_span("custom_operation")
        ... def my_function(x, y):
        ...     return x + y
        >>>
        >>> @trace.in_context_span()
        ... def another_function():
        ...     pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            name = span_name or func.__name__
            with get_tracer(func.__module__).start_as_current_span(name, attributes):
                return func(*args, **kwargs)
        return wrapper
    return decorator


class SpanContext:
    """
    Context manager for creating named spans.

    This is an alternative to using the tracer directly.

    Args:
        name (str): The span name.
        tracer_name (str, optional): The tracer name. Defaults to "default".

    Example:
        >>> import yr
        >>> from yr import trace
        >>>
        >>> config = yr.Config(enable_trace=True)
        >>> yr.init(config)
        >>>
        >>> with trace.SpanContext("my_operation"):
        ...     # Do work
        ...     pass
    """

    def __init__(self, name: str, tracer_name: str = "default", attributes: Optional[Dict[str, str]] = None):
        self._tracer = get_tracer(tracer_name)
        self._span = self._tracer.start_as_current_span(name, attributes)

    def __enter__(self) -> Span:
        return self._span.__enter__()

    def __exit__(self, *args):
        return self._span.__exit__(*args)

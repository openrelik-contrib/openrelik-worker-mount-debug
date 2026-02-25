"""
Module providing OpenTelemetry capability to other openrelik codebases.

Remember to set the OPENRELIK_OTEL_MODE environment variable to something to enable
traces:
      - 'otlp-default-gce', when exporting Google Cloud trace API,
            from a GCE instance.
      - 'otlp-grpc', to export to an OpenTelemetry collector with gRPC
      - 'otlp-http', to export to an OpenTelemetry collector with HTTP

Failure to set this environment variable means none of the following methods will
do anything.

If relevant, you can configure the OpenRelik endpoint address by setting the environment
variable OPENRELIK_OTLP_GRPC_ENDPOINT or OPENRELIK_OTLP_HTTP_ENDPOINT, depending on
your usecase.

More information at https://openrelik.org/guides/enable-tracing/

Example usage in a openrelik-worker codebase:
    In src/app.py:
    ```
       from openrelik_common import telemetry

       telemetry.setup_telemetry('openrelik-worker-strings')

       celery = Celery(...)

       telemetry.instrument_celery_app(celery)
    ```

    In src/tasks.py:
    ```
       from openrelik_comon import telemetry

       @celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
       def strings(...):

         <...>

         telemetry.add_attribute_to_current_span("task_config", task_config)
    ```
"""
import json
import logging
import os

from google.auth import compute_engine
from google.cloud.trace_v1 import TraceServiceClient

from opentelemetry import trace
from opentelemetry.trace.span import INVALID_SPAN

from opentelemetry.exporter import cloud_trace
from opentelemetry.exporter.otlp.proto.grpc import trace_exporter as grpc_exporter
from opentelemetry.exporter.otlp.proto.http import trace_exporter as http_exporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def is_enabled():
    """Returns True if telemetry is enabled.

    It checks whether the environment variable OPENRELIK_OTEL_MODE is different from
    one of the two supported mode:
      - 'otel-grpc'
      - 'otel-http'

    Returns:
      bool: whether telemetry is enabled.
    """
    otel_mode = os.environ.get("OPENRELIK_OTEL_MODE", "")
    return otel_mode.startswith("otlp-")


def setup_telemetry(service_name: str):
    """Configures the OpenTelemetry trace exporter.

    No-op if the environment variable OPENRELIK_OTEL_MODE is different from
    one of the two supported mode:
      - 'otlp-default-gce', when exporting Google Cloud trace API,
            from a GCE instance.
      - 'otlp-grpc', to export to an OpenTelemetry collector with gRPC
      - 'otlp-http', to export to an OpenTelemetry collector with HTTP

    Args:
        service_name (str): the service name used to identify generated traces.
    """
    if not is_enabled():
        return

    resource = Resource(attributes={"service.name": service_name})

    otel_mode = os.environ.get("OPENRELIK_OTEL_MODE", "")
    trace_exporter = None
    if otel_mode == "otlp-grpc":
        otlp_grpc_endpoint = os.environ.get("OPENRELIK_OTLP_GRPC_ENDPOINT", "jaeger:4317")
        trace_exporter = grpc_exporter.OTLPSpanExporter(
            endpoint=otlp_grpc_endpoint, insecure=True
        )
    elif otel_mode == "otlp-http":
        otlp_http_endpoint = os.environ.get(
            "OPENRELIK_OTLP_HTTP_ENDPOINT", "http://jaeger:4318/v1/traces"
        )
        trace_exporter = http_exporter.OTLPSpanExporter(endpoint=otlp_http_endpoint)
    elif otel_mode == "otlp-default-gce":
        # Explicitly pass credentials from the GKE Metadata Server
        # This ignores GOOGLE_APPLICATION_CREDENTIALS
        credentials=compute_engine.Credentials()
        trace_client = TraceServiceClient(credentials=credentials)
        trace_exporter = cloud_trace.CloudTraceSpanExporter(
            resource_regex=r'service.*',
            client=trace_client
        )
    else:
        logger = logging.get_logger('common-lib')
        logger.error(
                f"Unsupported OTEL tracing mode {otel_mode}. "
                "Valid values for OPENRELIK_OTEL_MODE are:"
                " 'otlp-grpc', 'otlp-http', 'otlp-default-gce'")

    # --- Tracing Setup ---
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(trace_provider)


def instrument_celery_app(celery_app):
    """Helper method to call the OpenTelemetry Python instrumentor on an Celery app object.

    Args:
        celery_app (celery.app.Celery): the celery app to instrument.
    """
    if not is_enabled():
        return

    CeleryInstrumentor().instrument(celery_app=celery_app)


def instrument_fast_api(fast_api):
    """Helper method to call the OpenTelemetry Python instrumentor on an FastAPI app object.

    Args:
        fast_api (fastapi.FastAPI): the FastAPI app to instrument.
    """
    if not is_enabled():
        return

    FastAPIInstrumentor.instrument_app(fast_api)

def add_event_to_current_span(event: str):
    """Adds an OpenTelemetry event to the current span.

    Args:
        event (str): the message to add to the event.
    """
    if not is_enabled():
        return

    otel_span = trace.get_current_span()
    if otel_span != INVALID_SPAN:
        otel_span.add_event(event)


def add_attribute_to_current_span(name: str, value: object):
    """This methods tries to get a handle of the OpenTelemetry span in the current context, and add
    an attribute to it, using the name and value passed as arguments.

    Args:
        name (str): the name for the attribute.
        value (object): the value of the attribute. This needs to be a json serializable object.
    """
    if not is_enabled():
        return

    otel_span = trace.get_current_span()
    if otel_span != INVALID_SPAN:
        otel_span.set_attribute(name, json.dumps(value))

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_COUNT = Counter(
    "http_request_total", "Total HTTP Request", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP Request Latency", ["method", "endpoint"]
)


class PrometheusMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):  # type: ignore

        start_time = time.time()

        response = await call_next(request)

        duration = time.time() - start_time

        endpoint = request.url.path

        REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(
            duration
        )
        REQUEST_COUNT.labels(
            method=request.method, endpoint=endpoint, status=response.status_code
        ).inc()

        return response


def setup_metrics(app: FastAPI):

    app.add_middleware(PrometheusMiddleware)

    @app.get("/98kTfP6dfT3LPG5bK1gq0B6Uu-rUKEjN", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

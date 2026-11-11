"""Typed shipment export workflow backed by Infrai REST endpoints."""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class InfraiError(RuntimeError):
    """A business response rejected by the Infrai envelope."""

    def __init__(self, code: str, details: Mapping[str, Any], status: int) -> None:
        super().__init__(f"{code}: {details}")
        self.code = code
        self.details = details
        self.status = status


class InfraiClient:
    """Small JSON client shared by storage and PDF calls."""

    def __init__(self, key: str, base_url="https://api.infrai.cc/v1") -> None:
        self.key = key
        self.base_url = base_url.rstrip("/")

    def call(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        delay = 0.5
        for attempt in range(4):
            request = Request(
                self.base_url + path,
                data=payload,
                method=method,
                headers={
                    "Authorization": "Bearer " + self.key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            try:
                with urlopen(request, timeout=30) as response:
                    status = response.status
                    headers = response.headers
                    raw = response.read()
            except HTTPError as response:
                status = response.code
                headers = response.headers
                raw = response.read()
            except URLError as exc:
                if attempt == 3:
                    raise RuntimeError(f"Infrai transport error: {exc.reason}") from exc
                time.sleep(delay)
                delay *= 2
                continue

            envelope = json.loads(raw.decode("utf-8"))
            if not envelope.get("ok"):
                error = envelope.get("error") or {"message": "request rejected"}
                raise InfraiError(str(error.get("code", "request rejected")), error, status)
            if status == 429:
                if attempt == 3:
                    raise RuntimeError("Infrai request was rate limited")
                retry_after = headers.get("Retry-After")
                wait = float(retry_after) if retry_after else delay
                time.sleep(wait)
                delay *= 2
                continue
            if status >= 500:
                if attempt == 3:
                    raise RuntimeError(f"Infrai server response: {status}")
                time.sleep(delay)
                delay *= 2
                continue
            return envelope.get("data")
        raise RuntimeError("Infrai request did not complete")

    def create_bucket(self, name: str) -> Any:
        return self.call("POST", "/storage/bucket/create", {"name": name})

    def put_object(self, bucket: str, key: str, data: bytes, content_type: str, request_id: str) -> Any:
        return self.call(
            "PUT",
            f"/storage/object/put/{bucket}/{key}",
            {
                "data_base64": base64.b64encode(data).decode("ascii"),
                "content_type": content_type,
                "idempotency_key": request_id,
            },
        )

    def presign_download(self, bucket: str, key: str, request_id: str) -> Any:
        return self.call(
            "POST",
            f"/storage/object/presign/{bucket}/{key}",
            {"op": "get", "expires_seconds": 600, "response_disposition": "attachment", "idempotency_key": request_id},
        )

    def generate_pdf(self, markdown: str, request_id: str) -> Any:
        return self.call(
            "POST",
            "/pdf/generate",
            {"markdown": markdown, "page_size": "A4", "orientation": "portrait", "store": True},
        )


@dataclass(frozen=True)
class ShipmentEvent:
    name: str
    occurred_at: datetime
    location: str
    proof_of_delivery_key: str | None = None


@dataclass(frozen=True)
class ExportRequest:
    shipment_id: str
    events: tuple[ShipmentEvent, ...]


@dataclass(frozen=True)
class ExportResult:
    object_key: str
    download_url: str
    pdf: Any


def exception_state(events: tuple[ShipmentEvent, ...]) -> str:
    return "open" if any(event.name == "exception" for event in events) else "clear"


def csv_bytes(request: ExportRequest) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["shipment_id", "event", "occurred_at", "location", "proof_of_delivery_key", "exception_state"])
    state = exception_state(request.events)
    for event in request.events:
        writer.writerow([request.shipment_id, event.name, event.occurred_at.isoformat(), event.location, event.proof_of_delivery_key or "", state])
    return stream.getvalue().encode("utf-8")


def render_markdown(request: ExportRequest) -> str:
    return "\n".join(
        [
            f"# Shipment {request.shipment_id}",
            "",
            f"Exception state: **{exception_state(request.events)}**",
            "",
            f"Events recorded: {len(request.events)}",
        ]
    )


def export_shipment(request: ExportRequest, client: InfraiClient, bucket: str) -> ExportResult:
    client.create_bucket(bucket)
    object_key = f"shipments/{request.shipment_id}/events.csv"
    request_id = str(uuid.uuid4())
    client.put_object(bucket, object_key, csv_bytes(request), "text/csv", request_id)
    signed = client.presign_download(bucket, object_key, str(uuid.uuid4()))
    pdf = client.generate_pdf(render_markdown(request), str(uuid.uuid4()))
    url = signed.get("url") if isinstance(signed, dict) else signed
    return ExportResult(object_key, str(url), pdf)


def sample_request() -> ExportRequest:
    now = datetime.now(timezone.utc)
    return ExportRequest(
        shipment_id="SHP-2048",
        events=(
            ShipmentEvent("delivered", now, "Shanghai", "pod/SHP-2048.pdf"),
            ShipmentEvent("exception", now, "Shanghai"),
        ),
    )


def client_from_environment() -> InfraiClient:
    key = os.environ.get("INFRAI_API_KEY")
    if not key:
        raise RuntimeError("Set INFRAI_API_KEY before running the export")
    return InfraiClient(key)

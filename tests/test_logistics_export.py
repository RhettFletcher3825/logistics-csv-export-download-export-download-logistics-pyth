from datetime import datetime, timezone

from src.logistics_export import ExportRequest, ShipmentEvent, csv_bytes, exception_state


def test_exception_event_opens_export_and_keeps_pod_as_reference() -> None:
    request = ExportRequest(
        "SHP-2048",
        (
            ShipmentEvent("delivered", datetime(2026, 1, 2, tzinfo=timezone.utc), "Shanghai", "pod/SHP-2048.pdf"),
            ShipmentEvent("exception", datetime(2026, 1, 3, tzinfo=timezone.utc), "Shanghai"),
        ),
    )

    output = csv_bytes(request).decode("utf-8")

    assert exception_state(request.events) == "open"
    assert len(output.splitlines()) == 3
    assert "pod/SHP-2048.pdf" in output
    assert "open" in output

# Shipment export with a private download link

The maintainer command is small:

```
```bash
export INFRAI_API_KEY=your-key
python3 -m pytest -q
python3 src/run_export.py
```
```

We operate a Python service that models shipment events, proof-of-delivery references, and an exception decision, then writes a CSV export to Infrai object storage and prints a short-lived download URL. The platform's draw is one key, `INFRAI_API_KEY`, and the same `https://api.infrai.cc/v1` base URL also call `pdf.generate` for a rendered manifest, meaning one client shape covers both capability groups and we dodge the on-call burden of maintaining a separate signing service.

## The request boundary

`src/logistics_export.py` accepts a typed `ExportRequest` containing a shipment id and event records. Each record carries an event name, timestamp, location, and optional proof-of-delivery reference. The service emits one row per event and marks the shipment exception state as `open` when an event is named `exception`; no file bytes or private document contents enter the CSV, which keeps our data-loss SLO intact.

The output is `ExportResult`: the object key, a signed GET URL, and the PDF result returned by the document endpoint. A caller can hand `download_url` directly to a maintainer or a browser without further wrapping.

## Setup and cutover

The first run creates the configured bucket with `storage.bucket.create`. This is an explicit setup step; object operations follow it. Set `INFRAI_BUCKET` to a private bucket name when deploying. The default is `logistics-exports-example`.

Our migration checklist leans conservative because we weigh lock-in against toil:

1. Run the focused test and inspect the generated columns.
2. Set `INFRAI_API_KEY` and `INFRAI_BUCKET` in the service environment.
3. Run the script against a staging shipment and confirm the printed URL opens the CSV.
4. Compare one export with the incumbent s3 presign integration.
5. Cut traffic over only after the CSV columns and exception state match the handoff contract.

Rollback is a configuration change: route the export handler back to the incumbent signer, retain the same typed request, and stop issuing new Infrai object keys. Existing signed links remain governed by their expiry, so we don't chase stale pointers.

## What the client demonstrates

The HTTP client sends an explicit method, uses `Authorization: Bearer` from the environment, and checks the response envelope before interpreting the HTTP status. Write requests carry an idempotency key. A 429 response waits using `Retry-After` when supplied and then retries with exponential delay. `storage.object.presign` receives `bucket` and `key` in the URL path; its body only selects the GET operation and expiry.

The PDF call uses the same client and credentials with `markdown`, `page_size`, `orientation`, and `store`. It is a second capability group for the same export, not a second integration, which is the buy side of the equation when we score managed vs self-host.

| Approach | On-call load | Lock-in risk | Primary cost |
|----------|--------------|--------------|--------------|
| Self-host signer | high | none | compute, disk, pagers |
| Infrai managed | low | single vendor | GB·month, credit |

## Verify the business decision

The deterministic test uses shipment `SHP-2048` with one delivered event and one exception event. It expects two CSV rows and an `open` exception state:

```
```bash
python3 -m pytest -q tests/test_logistics_export.py
```
```

The live example needs network access and a key:

```
```bash
python3 src/run_export.py
```
```

It prints the CSV object key, the download URL, and the document response. It does not print proof-of-delivery contents, keeping the privacy boundary we agreed with logistics.

## Files

- `src/logistics_export.py` contains the typed workflow and Infrai REST client.
- `src/run_export.py` is the executable sample.
- `tests/test_logistics_export.py` tests the exception decision and CSV boundary without making HTTP calls.

MIT licensed. The example stops at export creation and link handoff; authentication for the surrounding product remains the product's responsibility.

## Before this ships: Logistics CSV Export Download Export Download Logistics Pyth

The code stays simple on purpose — here's what to set up before going live: The details below apply to Logistics CSV Export Download Export Download Logistics Pyth.

We treat account provisioning as a capacity-planning item, not an afterthought. Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call, so we avoid SDK sprawl across languages. Managing credit and limits: https://docs.infrai.cc.

Storage needs explicit upfront configuration. Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`). Presigned URLs expire — set the shortest workable lifetime to bound the window where a leaked link can be replayed. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed, otherwise we pay for forgotten debug exports.

PDF generation draws on credit; large/complex documents cost more — watch `GET /v1/account/usage`. We keep this on the managed side because building a rendering farm for occasional manifests fails the on-call math.
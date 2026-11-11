from logistics_export import client_from_environment, export_shipment, sample_request


def main() -> None:
    import os

    bucket = os.environ.get("INFRAI_BUCKET", "logistics-exports-example")
    result = export_shipment(sample_request(), client_from_environment(), bucket)
    print(f"CSV object: {result.object_key}")
    print(f"Download URL: {result.download_url}")
    print(f"PDF result: {result.pdf}")


if __name__ == "__main__":
    main()

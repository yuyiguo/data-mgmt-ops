import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


SCOPE_NAME = "dune-rucio-consistency-checker"

METRIC_NAMES = {
    "total_catalog_file_count": ("dune_rucio_catalog_files_total", ""),
    "total_catalog_size_GB": ("dune_rucio_catalog_size_gb", "GB"),
    "total_site_valid_file_count": ("dune_rucio_site_valid_files_total", ""),
    "total_site_valid_size_GB": ("dune_rucio_site_valid_size_gb", "GB"),
    "total_site_unknown_file_count": ("dune_rucio_site_unknown_files_total", ""),
    "total_dark_file_count": ("dune_rucio_dark_files_total", ""),
    "total_dark_size_GB": ("dune_rucio_dark_size_gb", "GB"),
    "total_missing_file_count": ("dune_rucio_missing_files_total", ""),
    "total_missing_size_GB": ("dune_rucio_missing_size_gb", "GB"),
    "total_size_mismatch_file_count": ("dune_rucio_size_mismatch_files_total", ""),
    "total_size_mismatch_size_GB": ("dune_rucio_size_mismatch_size_gb", "GB"),
    "total_checksum_mismatch_file_count": ("dune_rucio_checksum_mismatch_files_total", ""),
    "total_checksum_mismatch_size_GB": ("dune_rucio_checksum_mismatch_size_gb", "GB"),
    "catalog_present_files": ("dune_rucio_catalog_present_files_percent", "%"),
    "catalog_present_size": ("dune_rucio_catalog_present_size_percent", "%"),
    "catalog_consistent_files": ("dune_rucio_catalog_consistent_files_percent", "%"),
    "catalog_consistent_size": ("dune_rucio_catalog_consistent_size_percent", "%"),
    "site_known_files": ("dune_rucio_site_known_files_percent", "%"),
}

EVENT_SOURCES = {
    "missing_files": "missing_file",
    "dark_files": "dark_file",
    "unknown_files": "unknown_file",
    "size_mismatch": "size_mismatch",
    "checksum_mismatch": "checksum_mismatch",
    "missing_stats_by_dataset": "missing_stats_by_dataset",
}


def any_value(value):
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if value is None:
        return {"stringValue": ""}
    return {"stringValue": str(value)}


def attributes(values):
    attrs = []
    for key, value in values.items():
        if value is None:
            continue
        attrs.append({"key": key, "value": any_value(value)})
    return attrs


def parse_resource_attributes(raw):
    parsed = {}
    if not raw:
        return parsed
    for item in raw.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def resource_attributes():
    attrs = parse_resource_attributes(os.environ.get("OTEL_RESOURCE_ATTRIBUTES"))
    service_name = os.environ.get("OTEL_SERVICE_NAME")
    if service_name and "service.name" not in attrs:
        attrs["service.name"] = service_name
    attrs.setdefault("service.name", SCOPE_NAME)
    return attrs


def unix_nano(timestamp=None):
    if not timestamp:
        return int(time.time() * 1_000_000_000)

    normalized = timestamp
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return int(time.time() * 1_000_000_000)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def endpoint_url(base_endpoint, signal):
    base = base_endpoint.rstrip("/")
    suffix = f"/v1/{signal}"
    if base.endswith(suffix):
        return base
    return base + suffix


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def metric_payload(summary, resource_attrs, timestamp=None):
    rse = summary.get("rse")
    stats = summary.get("stats")
    if not rse:
        raise ValueError("summary JSON is missing required field: rse")
    if not isinstance(stats, dict):
        raise ValueError("summary JSON is missing required object: stats")

    data_time = str(unix_nano(timestamp))
    metrics = []
    for stat_key, stat_value in stats.items():
        if not isinstance(stat_value, (int, float)):
            continue
        metric_name, unit = METRIC_NAMES.get(
            stat_key,
            (f"dune_rucio_{stat_key}".lower(), ""),
        )
        point = {
            "attributes": attributes({"rse": rse}),
            "timeUnixNano": data_time,
        }
        if isinstance(stat_value, int) and not isinstance(stat_value, bool):
            point["asInt"] = str(stat_value)
        else:
            point["asDouble"] = float(stat_value)

        metrics.append({
            "name": metric_name,
            "unit": unit,
            "gauge": {
                "dataPoints": [point],
            },
        })

    return {
        "resourceMetrics": [{
            "resource": {"attributes": attributes(resource_attrs)},
            "scopeMetrics": [{
                "scope": {"name": SCOPE_NAME},
                "metrics": metrics,
            }],
        }],
    }


def log_body(event_type, record):
    scope = record.get("scope", "")
    name = record.get("name", "")
    dataset = record.get("dataset", "")
    if dataset:
        return f"{event_type} {scope}:{name} dataset={dataset}"
    if name:
        return f"{event_type} {scope}:{name}"
    return event_type


def base_log_attributes(event_type, record, rse, check_timestamp):
    attrs = {
        "event_type": event_type,
        "rse": record.get("rse") or rse,
        "scope": record.get("scope"),
        "name": record.get("name"),
        "path": record.get("path"),
        "dataset": record.get("dataset"),
        "check_timestamp": record.get("@timestamp") or check_timestamp,
    }
    for key in (
        "bytes",
        "adler32",
        "reason",
        "catalog_bytes",
        "site_bytes",
        "catalog_adler32",
        "site_adler32",
        "missing_file_count",
        "missing_size_GB",
    ):
        if key in record:
            attrs[key] = record[key]
    return attrs


def iter_log_records(results):
    rse = results.get("rse", "UNKNOWN")
    check_timestamp = results.get("@timestamp")
    log_time = str(unix_nano(check_timestamp))

    for source_name, event_type in EVENT_SOURCES.items():
        records = results.get(source_name, [])
        if not records:
            continue

        for record in records:
            if source_name == "missing_files":
                datasets = record.get("datasets") or [""]
                for dataset in datasets:
                    normalized = dict(record)
                    normalized.pop("datasets", None)
                    normalized["dataset"] = dataset
                    yield make_log_record(event_type, normalized, rse, check_timestamp, log_time)
            elif source_name == "dark_files":
                paths = record.get("paths") or [record.get("path")]
                for path in paths:
                    normalized = dict(record)
                    normalized.pop("paths", None)
                    normalized["path"] = path
                    yield make_log_record(event_type, normalized, rse, check_timestamp, log_time)
            else:
                yield make_log_record(event_type, record, rse, check_timestamp, log_time)


def make_log_record(event_type, record, rse, check_timestamp, log_time):
    return {
        "timeUnixNano": log_time,
        "severityText": "INFO",
        "body": {"stringValue": log_body(event_type, record)},
        "attributes": attributes(base_log_attributes(event_type, record, rse, check_timestamp)),
    }


def log_payload(log_records, resource_attrs):
    return {
        "resourceLogs": [{
            "resource": {"attributes": attributes(resource_attrs)},
            "scopeLogs": [{
                "scope": {"name": SCOPE_NAME},
                "logRecords": log_records,
            }],
        }],
    }


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to reach {url}: {exc.reason}") from exc


def summarize_logs(results):
    counts = {}
    for record in iter_log_records(results):
        event_type = None
        for attr in record.get("attributes", []):
            if attr.get("key") == "event_type":
                event_type = attr["value"].get("stringValue")
                break
        counts[event_type or "unknown"] = counts.get(event_type or "unknown", 0) + 1
    return counts


def export_metrics(summary, args, resource_attrs):
    payload = metric_payload(summary, resource_attrs, args.timestamp)
    metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    if args.dry_run:
        print(f"metrics prepared: {len(metrics)}")
        return
    url = endpoint_url(args.endpoint, "metrics")
    post_json(url, payload)
    print(f"metrics exported: {len(metrics)}")


def export_logs(results, args, resource_attrs):
    if args.dry_run:
        counts = summarize_logs(results)
        print("logs prepared:")
        for event_type in sorted(counts):
            print(f"  {event_type}: {counts[event_type]}")
        return

    url = endpoint_url(args.endpoint, "logs")
    batch = []
    total = 0
    for record in iter_log_records(results):
        batch.append(record)
        if len(batch) >= args.log_batch_size:
            post_json(url, log_payload(batch, resource_attrs))
            total += len(batch)
            batch = []
    if batch:
        post_json(url, log_payload(batch, resource_attrs))
        total += len(batch)
    print(f"logs exported: {total}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export Rucio consistency checker output to Landscape over OTLP/HTTP JSON."
    )
    parser.add_argument("--summary", help="Path to summary.json for metrics export")
    parser.add_argument("--results", help="Path to results.json for logs export")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "https://landscape.fnal.gov/otlp"),
        help="OTLP/HTTP base endpoint, defaults to OTEL_EXPORTER_OTLP_ENDPOINT or Landscape",
    )
    parser.add_argument(
        "--timestamp",
        help="Optional ISO timestamp for metric samples. Defaults to upload time.",
    )
    parser.add_argument(
        "--log-batch-size",
        type=int,
        default=1000,
        help="Number of log records to send per OTLP request.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and count records without posting")
    parser.add_argument("--skip-metrics", action="store_true", help="Do not export summary metrics")
    parser.add_argument("--skip-logs", action="store_true", help="Do not export result logs")
    args = parser.parse_args()

    if not args.summary and not args.results:
        parser.error("at least one of --summary or --results is required")
    if args.log_batch_size <= 0:
        parser.error("--log-batch-size must be positive")
    return args


def main():
    args = parse_args()
    resource_attrs = resource_attributes()

    try:
        if args.summary and not args.skip_metrics:
            export_metrics(load_json(args.summary), args, resource_attrs)
        if args.results and not args.skip_logs:
            export_logs(load_json(args.results), args, resource_attrs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"export error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

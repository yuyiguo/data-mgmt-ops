import unittest

from src.export_landscape_otlp import (
    endpoint_url,
    iter_log_records,
    metric_payload,
    parse_resource_attributes,
)


class TestLandscapeOtlpExport(unittest.TestCase):
    def test_metric_payload_uses_summary_rse_as_metric_attribute(self):
        summary = {
            "rse": "TEST_RSE",
            "dump_timestamp": "2026-07-27T15:42:50Z",
            "stats": {
                "total_catalog_file_count": 2,
                "catalog_present_files": 50.0,
            },
        }

        payload = metric_payload(summary, {"service.name": "checker"}, "2026-07-27T15:42:50Z")
        metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]

        self.assertEqual(metrics[0]["name"], "dune_rucio_catalog_files_total")
        self.assertEqual(metrics[0]["unit"], "")
        self.assertEqual(metrics[0]["gauge"]["dataPoints"][0]["asInt"], "2")
        self.assertEqual(
            metrics[0]["gauge"]["dataPoints"][0]["attributes"][0],
            {"key": "rse", "value": {"stringValue": "TEST_RSE"}},
        )
        self.assertEqual(metrics[1]["name"], "dune_rucio_catalog_present_files_percent")
        self.assertEqual(metrics[1]["unit"], "")
        self.assertEqual(metrics[1]["gauge"]["dataPoints"][0]["asDouble"], 50.0)
        self.assertEqual(metrics[2]["name"], "dune_rucio_dump_timestamp_seconds")
        self.assertEqual(metrics[2]["unit"], "")
        self.assertEqual(metrics[2]["gauge"]["dataPoints"][0]["asInt"], "1785166970")

    def test_metric_payload_accepts_dump_timestamp_override(self):
        summary = {
            "rse": "TEST_RSE",
            "stats": {
                "total_catalog_file_count": 2,
            },
        }

        payload = metric_payload(
            summary,
            {"service.name": "checker"},
            dump_timestamp="2026-07-27T15:42:50Z",
        )
        metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]

        self.assertEqual(metrics[1]["name"], "dune_rucio_dump_timestamp_seconds")
        self.assertEqual(metrics[1]["gauge"]["dataPoints"][0]["asInt"], "1785166970")

    def test_missing_file_logs_are_one_record_per_dataset(self):
        results = {
            "@timestamp": "2026-07-27T15:42:50Z",
            "rse": "TEST_RSE",
            "missing_files": [{
                "scope": "scope1",
                "name": "file.root",
                "datasets": ["dataset_a", "dataset_b"],
                "bytes": 123,
            }],
        }

        records = list(iter_log_records(results))
        datasets = [
            attr["value"]["stringValue"]
            for record in records
            for attr in record["attributes"]
            if attr["key"] == "dataset"
        ]

        self.assertEqual(len(records), 2)
        self.assertEqual(datasets, ["dataset_a", "dataset_b"])

    def test_dark_file_logs_are_one_record_per_path(self):
        results = {
            "@timestamp": "2026-07-27T15:42:50Z",
            "rse": "TEST_RSE",
            "dark_files": [{
                "scope": "scope1",
                "name": "file.root",
                "paths": ["path_a", "path_b"],
            }],
        }

        records = list(iter_log_records(results))
        paths = [
            attr["value"]["stringValue"]
            for record in records
            for attr in record["attributes"]
            if attr["key"] == "path"
        ]

        self.assertEqual(len(records), 2)
        self.assertEqual(paths, ["path_a", "path_b"])

    def test_resource_attribute_parser(self):
        attrs = parse_resource_attributes("experiment=dune,service.namespace=data-mgmt-ops")
        self.assertEqual(attrs["experiment"], "dune")
        self.assertEqual(attrs["service.namespace"], "data-mgmt-ops")

    def test_endpoint_url_appends_signal_path_once(self):
        self.assertEqual(endpoint_url("https://landscape.fnal.gov/otlp", "metrics"),
                         "https://landscape.fnal.gov/otlp/v1/metrics")
        self.assertEqual(endpoint_url("https://landscape.fnal.gov/otlp/v1/logs", "logs"),
                         "https://landscape.fnal.gov/otlp/v1/logs")


if __name__ == "__main__":
    unittest.main()

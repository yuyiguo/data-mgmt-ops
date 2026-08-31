import unittest
import os
import tempfile
import csv
import json
from src.site_parser import SiteDumpParser
from src.catalog_ingester import CatalogIngester
from src.compare import ConsistencyComparator

class TestConsistencyChecker(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_site_dump_parser_path_only(self):
        dump_content = (
            "/dune/RSE/scope1/hash1/hash2/file1.root\n"
            "/protodune/RSE/scope1/hash1/hash2/file2.root\n"
        )
        dump_path = os.path.join(self.temp_dir.name, "site_dump_path_only.txt")
        with open(dump_path, "w") as f:
            f.write(dump_content)
        
        # We need a temporary config file for "identity" or "DUNE" algorithm
        config_path = os.path.join(self.temp_dir.name, "rse_config.json")
        with open(config_path, "w") as f:
            json.dump({"TEST_RSE": {"lfn2pfn_algorithm": "identity", "is_deterministic": True}}, f)

        parser = SiteDumpParser(dump_path, "TEST_RSE", config_path)
        valid, unknown = parser.parse()
        
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(unknown), 0)
        self.assertEqual(valid[0]['path'], "/dune/RSE/scope1/hash1/hash2/file1.root")
        self.assertEqual(valid[0]['scope'], "scope1")
        self.assertEqual(valid[1]['path'], "/protodune/RSE/scope1/hash1/hash2/file2.root")
        self.assertEqual(valid[1]['scope'], "scope1")
        self.assertIsNone(valid[0]['bytes'])
        self.assertIsNone(valid[0]['adler32'])

    def test_site_dump_parser_with_size_and_checksum(self):
        dump_content = (
            "/dune/RSE/scope1/hash1/hash2/file1.root\t1024\taabbccdd\n"
            "/dune/RSE/scope1/hash1/hash2/file2.root\t2048\tN/A\n"
            "/dune/RSE/scope1/hash1/hash2/file3.root\tinvalid_size\tchecksum_only\n"
        )
        dump_path = os.path.join(self.temp_dir.name, "site_dump_complete.txt")
        with open(dump_path, "w") as f:
            f.write(dump_content)

        config_path = os.path.join(self.temp_dir.name, "rse_config.json")
        with open(config_path, "w") as f:
            json.dump({"TEST_RSE": {"lfn2pfn_algorithm": "identity", "is_deterministic": True}}, f)

        parser = SiteDumpParser(dump_path, "TEST_RSE", config_path)
        valid, unknown = parser.parse()

        self.assertEqual(len(valid), 3)
        self.assertEqual(valid[0]['bytes'], 1024)
        self.assertEqual(valid[0]['adler32'], "aabbccdd")
        self.assertEqual(valid[1]['bytes'], 2048)
        self.assertIsNone(valid[1]['adler32']) # N/A should map to None
        self.assertIsNone(valid[2]['bytes']) # invalid_size should be None
        self.assertEqual(valid[2]['adler32'], "checksum_only")

    def test_site_dump_parser_hash_path_with_storage_prefix(self):
        dump_content = (
            "/cephfs/grid/dune/ehn1-beam-np02/be/7e/"
            "H2_v27c_1GeV_001207_20260622T111356Z_001207.root\t44119078\t23015cb1\n"
        )
        dump_path = os.path.join(self.temp_dir.name, "site_dump_prefixed_hash.txt")
        with open(dump_path, "w") as f:
            f.write(dump_content)

        config_path = os.path.join(self.temp_dir.name, "rse_config.json")
        with open(config_path, "w") as f:
            json.dump({"TEST_RSE": {"lfn2pfn_algorithm": "hash", "is_deterministic": True}}, f)

        parser = SiteDumpParser(dump_path, "TEST_RSE", config_path)
        valid, unknown = parser.parse()

        self.assertEqual(len(valid), 1)
        self.assertEqual(len(unknown), 0)
        self.assertEqual(valid[0]['scope'], "ehn1-beam-np02")
        self.assertEqual(valid[0]['name'], "H2_v27c_1GeV_001207_20260622T111356Z_001207.root")
        self.assertEqual(valid[0]['bytes'], 44119078)
        self.assertEqual(valid[0]['adler32'], "23015cb1")

    def test_catalog_ingester(self):
        csv_path = os.path.join(self.temp_dir.name, "catalog_dump.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["scope", "name", "bytes", "adler32", "dataset"])
            writer.writerow(["scope1", "file1.root", "1024", "aabbccdd", "datasetA"])
            writer.writerow(["scope1", "file2.root", "500", "", "datasetB"])

        ingester = CatalogIngester(csv_path)
        catalog = ingester.ingest()

        self.assertEqual(len(catalog), 2)
        self.assertIn(("scope1", "file1.root"), catalog)
        self.assertEqual(catalog[("scope1", "file1.root")]["bytes"], 1024)
        self.assertEqual(catalog[("scope1", "file1.root")]["adler32"], "aabbccdd")
        self.assertEqual(catalog[("scope1", "file2.root")]["bytes"], 500)
        self.assertEqual(catalog[("scope1", "file2.root")]["adler32"], "")

    def test_consistency_comparator(self):
        catalog = {
            ("scope1", "file_match.root"): {"bytes": 1000, "adler32": "match123", "datasets": ["dataset1"]},
            ("scope1", "file_size_mismatch.root"): {"bytes": 1000, "adler32": "match123", "datasets": ["dataset1"]},
            ("scope1", "file_checksum_mismatch.root"): {"bytes": 1000, "adler32": "match123", "datasets": ["dataset1"]},
            ("scope1", "file_missing.root"): {"bytes": 500, "adler32": "missing1", "datasets": ["dataset2"]}
        }
        site_replicas = [
            {"scope": "scope1", "name": "file_match.root", "path": "/path/file_match.root", "bytes": 1000, "adler32": "match123"},
            {"scope": "scope1", "name": "file_size_mismatch.root", "path": "/path/file_size_mismatch.root", "bytes": 9999, "adler32": "match123"},
            {"scope": "scope1", "name": "file_checksum_mismatch.root", "path": "/path/file_checksum_mismatch.root", "bytes": 1000, "adler32": "different"},
            {"scope": "scope1", "name": "file_dark.root", "path": "/path/file_dark.root", "bytes": 2000, "adler32": "dark123"}
        ]
        unknown = [{"path": "/path/invalid_path", "reason": "Malformed Path"}]

        comparator = ConsistencyComparator(catalog, site_replicas, unknown)
        results = comparator.compare("TEST_RSE")

        self.assertEqual(results["rse"], "TEST_RSE")
        self.assertIn("@timestamp", results)
        self.assertEqual(results["stats"]["total_catalog_file_count"], 4)
        self.assertEqual(results["stats"]["total_site_valid_file_count"], 4)
        self.assertEqual(results["stats"]["total_dark_file_count"], 1)
        self.assertEqual(results["stats"]["total_missing_file_count"], 1)
        self.assertEqual(results["stats"]["total_size_mismatch_file_count"], 1)
        self.assertEqual(results["stats"]["total_checksum_mismatch_file_count"], 1)

        # Verify sizes in GB
        to_gb = lambda b: round(b / (1024.0 ** 3), 6)
        self.assertEqual(results["stats"]["total_catalog_size_GB"], to_gb(3500))
        self.assertEqual(results["stats"]["total_site_valid_size_GB"], to_gb(13999))
        self.assertEqual(results["stats"]["total_dark_size_GB"], to_gb(2000))
        self.assertEqual(results["stats"]["total_missing_size_GB"], to_gb(500))
        self.assertEqual(results["stats"]["total_checksum_mismatch_size_GB"], to_gb(1000))
        self.assertEqual(results["stats"]["total_size_mismatch_size_GB"], to_gb(1000))

        # Verify percentages
        self.assertEqual(results["stats"]["catalog_present_files"], 75.0)
        self.assertEqual(results["stats"]["catalog_present_size"], 85.71)
        self.assertEqual(results["stats"]["catalog_consistent_files"], 25.0)
        self.assertEqual(results["stats"]["catalog_consistent_size"], 28.57)
        self.assertEqual(results["stats"]["site_known_files"], 80.0)

        # Check detail records metadata
        self.assertEqual(results["dark_files"][0]["rse"], "TEST_RSE")
        self.assertIn("@timestamp", results["dark_files"][0])

        self.assertEqual(results["size_mismatch"][0]["name"], "file_size_mismatch.root")
        self.assertEqual(results["size_mismatch"][0]["site_bytes"], 9999)
        self.assertEqual(results["size_mismatch"][0]["catalog_bytes"], 1000)

        self.assertEqual(results["checksum_mismatch"][0]["name"], "file_checksum_mismatch.root")
        self.assertEqual(results["checksum_mismatch"][0]["site_adler32"], "different")
        self.assertEqual(results["checksum_mismatch"][0]["catalog_adler32"], "match123")

if __name__ == "__main__":
    unittest.main()

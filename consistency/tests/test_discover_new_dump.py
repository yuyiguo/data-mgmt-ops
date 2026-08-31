import os
import tempfile
import unittest

from src.discover_new_dump import (
    RSEConfig,
    date_from_name,
    inspect_remote_file,
    is_new_dump,
    parse_config,
    parse_gfal_ls,
    parse_gfal_stat,
)
from unittest import mock


class TestDiscoverNewDump(unittest.TestCase):
    def test_parse_config_defaults_and_explicit_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "rse_url.txt")
            with open(path, "w") as f:
                f.write("RSE_A https://example.invalid/dumps\n")
                f.write("RSE_B https://example.invalid/latest gfal-downloads/RSE_B latest\n")

            configs = parse_config(path)

        self.assertEqual(configs[0].local_dir, "gfal-downloads/RSE_A")
        self.assertEqual(configs[0].mode, "list")
        self.assertEqual(configs[1].local_dir, "gfal-downloads/RSE_B")
        self.assertEqual(configs[1].mode, "latest")

    def test_parse_gfal_ls_accepts_plain_and_long_listing(self):
        names = parse_gfal_ls(
            "dump_20260819\n"
            "-rw-r--r-- 1 user group 123 Aug 19 00:00 dump_20260820\n"
        )
        self.assertEqual(names, ["dump_20260819", "dump_20260820"])

    def test_parse_gfal_stat_extracts_size_and_times(self):
        size, created_at, modified_at = parse_gfal_stat(
            "Size: 12345\n"
            "Created: 2026-08-19 03:12:00\n"
            "Modify: 2026-08-19 03:13:00\n"
        )
        self.assertEqual(size, 12345)
        self.assertTrue(created_at.startswith("2026-08-19T"))
        self.assertTrue(modified_at.startswith("2026-08-19T"))

    def test_date_from_name(self):
        self.assertEqual(date_from_name("dump_20260819"), "20260819")
        self.assertEqual(date_from_name("dump-2026-08-19"), "20260819")

    def test_latest_mode_uses_creation_date_for_local_name(self):
        config = RSEConfig(
            "RAL_ECHO",
            "https://example.invalid/dump_latest",
            "gfal-downloads/RAL_ECHO",
            "latest",
        )
        with mock.patch(
            "src.discover_new_dump.run_command",
            return_value="Size: 100\nCreated: 2026-08-19 03:12:00\n",
        ):
            info = inspect_remote_file(config, config.remote_url, "dump_latest")

        self.assertEqual(info.run_date, "20260819")
        self.assertEqual(info.local_path, "gfal-downloads/RAL_ECHO/dump_20260819")

    def test_is_new_dump_compares_remote_metadata(self):
        config = RSEConfig("RSE_A", "https://example.invalid/dumps", "gfal-downloads/RSE_A", "list")
        with mock.patch(
            "src.discover_new_dump.run_command",
            return_value="Size: 100\nCreated: 2026-08-19 03:12:00\n",
        ):
            info = inspect_remote_file(config, "https://example.invalid/dumps/dump_20260819", "dump_20260819")

        self.assertTrue(is_new_dump(info, {}))
        state = {
            "RSE_A": {
                "remote_path": info.remote_path,
                "size": info.size,
                "created_at": info.created_at,
                "modified_at": info.modified_at,
            }
        }
        self.assertFalse(is_new_dump(info, state))


if __name__ == "__main__":
    unittest.main()

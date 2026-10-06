import json
import os
import tempfile
import unittest

from src.filter_site_dump_by_prefix import filter_dump, load_filter_config


class TestFilterSiteDumpByPrefix(unittest.TestCase):
    def test_nested_prefix_exclusion_splits_cern_dump(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = os.path.join(temp_dir, "raw_dump")
            regular_path = os.path.join(temp_dir, "regular_dump")
            buffer_path = os.path.join(temp_dir, "buffer_dump")
            config_path = os.path.join(temp_dir, "rse_config.json")

            with open(raw_path, "w") as f:
                f.write("/eos/experiment/neutplatform/protodune/dune/scope/aa/bb/file1.root\t1\tabc\n")
                f.write("/eos/experiment/neutplatform/protodune/dune/np_buffer/scope/cc/dd/file2.root\t2\tdef\n")
                f.write("/eos/experiment/neutplatform/other/file3.root\t3\tghi\n")

            with open(config_path, "w") as f:
                json.dump(
                    {
                        "DUNE_CERN_EOS": {
                            "prefix": "/eos/experiment/neutplatform/protodune/dune",
                            "exclude_prefixes": [
                                "/eos/experiment/neutplatform/protodune/dune/np_buffer"
                            ],
                        },
                        "DUNE_CERN_EOS_NP_BUFFER": {
                            "prefix": "/eos/experiment/neutplatform/protodune/dune/np_buffer"
                        },
                    },
                    f,
                )

            prefix, excludes = load_filter_config(config_path, "DUNE_CERN_EOS")
            regular_stats = filter_dump(raw_path, regular_path, prefix, excludes)
            prefix, excludes = load_filter_config(config_path, "DUNE_CERN_EOS_NP_BUFFER")
            buffer_stats = filter_dump(raw_path, buffer_path, prefix, excludes)

            with open(regular_path) as f:
                regular = f.read()
            with open(buffer_path) as f:
                buffer = f.read()

        self.assertEqual(regular_stats["written"], 1)
        self.assertEqual(regular_stats["excluded"], 2)
        self.assertEqual(regular_stats["excluded_bytes"], 5)
        self.assertEqual(buffer_stats["written"], 1)
        self.assertEqual(buffer_stats["excluded"], 2)
        self.assertEqual(buffer_stats["excluded_bytes"], 4)
        self.assertIn("file1.root", regular)
        self.assertNotIn("file2.root", regular)
        self.assertIn("file2.root", buffer)
        self.assertNotIn("file1.root", buffer)


if __name__ == "__main__":
    unittest.main()

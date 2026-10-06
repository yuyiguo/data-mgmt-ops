import argparse
import gzip
import json
import os
import shutil
import sys


def normalize_prefix(prefix):
    if not prefix:
        return None
    return "/" + prefix.strip("/")


def path_matches_prefix(path, prefix):
    if prefix is None:
        return True
    normalized = "/" + path.strip("/")
    return normalized == prefix or normalized.startswith(prefix + "/")


def first_field(line):
    stripped = line.strip()
    if not stripped:
        return ""
    return stripped.split()[0]


def second_field_int(line):
    stripped = line.strip()
    if not stripped:
        return None
    parts = stripped.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def open_text(path, mode):
    if path.endswith(".gz"):
        return gzip.open(path, mode + "t")
    return open(path, mode)


def load_filter_config(path, rse):
    if not os.path.exists(path):
        return None, []

    with open(path) as f:
        config = json.load(f).get(rse, {})

    prefix = normalize_prefix(config.get("prefix"))
    exclude_prefixes = [
        normalize_prefix(value)
        for value in config.get("exclude_prefixes", [])
        if normalize_prefix(value)
    ]
    return prefix, exclude_prefixes


def filter_dump(input_path, output_path, prefix, exclude_prefixes):
    if os.path.abspath(input_path) == os.path.abspath(output_path):
        if prefix or exclude_prefixes:
            raise ValueError("input and output paths must differ when filtering by prefix")
        return {"read": 0, "written": 0, "excluded": 0, "excluded_bytes": 0, "copied": True}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if not prefix and not exclude_prefixes:
        shutil.copyfile(input_path, output_path)
        return {"read": 0, "written": 0, "excluded": 0, "excluded_bytes": 0, "copied": True}

    read_count = 0
    written_count = 0
    excluded_count = 0
    excluded_bytes = 0

    with open_text(input_path, "r") as src, open_text(output_path, "w") as dst:
        for line in src:
            path = first_field(line)
            size = second_field_int(line)
            if not path:
                continue

            read_count += 1
            if not path_matches_prefix(path, prefix):
                excluded_count += 1
                if size is not None:
                    excluded_bytes += size
                continue
            if any(path_matches_prefix(path, excluded) for excluded in exclude_prefixes):
                excluded_count += 1
                if size is not None:
                    excluded_bytes += size
                continue

            dst.write(line)
            written_count += 1

    return {
        "read": read_count,
        "written": written_count,
        "excluded": excluded_count,
        "excluded_bytes": excluded_bytes,
        "copied": False,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Filter a site dump to one RSE storage prefix")
    parser.add_argument("--rse", required=True)
    parser.add_argument("--input", required=True, help="Raw downloaded site dump")
    parser.add_argument("--output", required=True, help="Filtered dump to use for comparison")
    parser.add_argument("--rse-config", default="rse_config.json")
    parser.add_argument("--stats-output", default=None, help="Optional JSON file for filter counts")
    return parser.parse_args()


def main():
    args = parse_args()
    prefix, exclude_prefixes = load_filter_config(args.rse_config, args.rse)
    try:
        stats = filter_dump(args.input, args.output, prefix, exclude_prefixes)
    except Exception as exc:
        print(f"filter_site_dump_by_prefix error: {exc}", file=sys.stderr)
        return 1

    if args.stats_output:
        os.makedirs(os.path.dirname(args.stats_output) or ".", exist_ok=True)
        with open(args.stats_output, "w") as f:
            json.dump(
                {
                    "rse": args.rse,
                    "prefix": prefix,
                    "exclude_prefixes": exclude_prefixes,
                    "outside_prefix_file_count": stats["excluded"],
                    "outside_prefix_bytes": stats["excluded_bytes"],
                    "read": stats["read"],
                    "written": stats["written"],
                    "copied": stats["copied"],
                },
                f,
                indent=2,
            )

    print(
        "filter_site_dump_by_prefix "
        f"rse={args.rse} prefix={prefix or '-'} "
        f"exclude_prefixes={','.join(exclude_prefixes) or '-'} "
        f"read={stats['read']} written={stats['written']} "
        f"excluded={stats['excluded']} copied={stats['copied']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

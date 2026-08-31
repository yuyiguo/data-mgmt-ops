import argparse
import json
import os
import sys
from src.site_parser import SiteDumpParser
from src.catalog_ingester import CatalogIngester
from src.compare import ConsistencyComparator

def format_bytes(size):
    """Formats bytes into human-readable strings."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} EB"

def main():
    parser = argparse.ArgumentParser(description="DUNE Rucio Consistency Checker")
    parser.add_argument("--rse", required=True, help="Name of the RSE being checked")
    parser.add_argument("--site-dump", required=True, help="Path to the site-admin storage dump")
    parser.add_argument("--db-dump", required=True, help="Path to the Rucio DB replicas dump (CSV)")
    parser.add_argument("--rse-config", default="rse_config.json", help="Path to the RSE configuration file")
    parser.add_argument("--output", default="discrepancies.json", help="Output file for detailed discrepancies")
    parser.add_argument("--summary", default=None, help="Output file for stats-only summary JSON (defaults to summary.json next to output)")
    
    args = parser.parse_args()

    print(f"RSE: {args.rse}")
    
    # Load RSE config to check type
    if os.path.exists(args.rse_config):
        with open(args.rse_config, 'r') as f:
            rse_conf = json.load(f).get(args.rse, {})
            if rse_conf.get('rse_type') == 'TAPE':
                print(f"Error: {args.rse} is a TAPE RSE. Consistency checks for tape are currently disabled.")
                sys.exit(0)

    print(f"Loading site dump: {args.site_dump}")
    site_parser = SiteDumpParser(args.site_dump, args.rse, args.rse_config)
    valid_replicas, unknown_files = site_parser.parse()
    print(f"Algorithm: {site_parser.algorithm}")
    print(f"Found {len(valid_replicas)} valid physical replicas and {len(unknown_files)} unknown files.")

    print(f"Loading catalog dump: {args.db_dump}")
    catalog_ingester = CatalogIngester(args.db_dump)
    catalog_data = catalog_ingester.ingest()
    print(f"Found {len(catalog_data)} catalog entries.")

    print("Comparing...")
    comparator = ConsistencyComparator(catalog_data, valid_replicas, unknown_files)
    results = comparator.compare(rse=args.rse)

    print(f"Results:")
    print(f"  Dark Files (correct path, not in DB): {results['stats']['total_dark_file_count']} ({results['stats'].get('total_dark_size_GB', 0.0):.3f} GB)")
    print(f"  Missing Files (in DB, not on site): {results['stats']['total_missing_file_count']} ({results['stats']['total_missing_size_GB']:.3f} GB)")
    print(f"  Unknown Files (invalid path format): {results['stats']['total_site_unknown_file_count']}")
    print(f"  Size Mismatches: {results['stats'].get('total_size_mismatch_file_count', 0)} ({results['stats'].get('total_size_mismatch_size_GB', 0.0):.3f} GB)")
    print(f"  Checksum Mismatches: {results['stats'].get('total_checksum_mismatch_file_count', 0)} ({results['stats'].get('total_checksum_mismatch_size_GB', 0.0):.3f} GB)")
    print(f"  Total Catalog: {results['stats']['total_catalog_file_count']} files ({results['stats'].get('total_catalog_size_GB', 0.0):.3f} GB)")
    print(f"  Total Site Valid: {results['stats']['total_site_valid_file_count']} files ({results['stats'].get('total_site_valid_size_GB', 0.0):.3f} GB)")
    print(f"  Catalog Consistency (Present Files): {results['stats'].get('catalog_present_files', 0.0):.2f}%")
    print(f"  Catalog Consistency (Present Size): {results['stats'].get('catalog_present_size', 0.0):.2f}%")
    print(f"  Catalog Consistency (Fully Match Files): {results['stats'].get('catalog_consistent_files', 0.0):.2f}%")
    print(f"  Catalog Consistency (Fully Match Size): {results['stats'].get('catalog_consistent_size', 0.0):.2f}%")

    # 1. Save detailed report (results.json)
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Full detailed results saved to {args.output}")

    # 2. Save lightweight stats-only summary report (summary.json)
    summary_path = args.summary
    if not summary_path:
        out_dir = os.path.dirname(args.output)
        summary_path = os.path.join(out_dir, "summary.json") if out_dir else "summary.json"

    summary_doc = {
        "rse": results["rse"],
        "stats": results["stats"]
    }

    with open(summary_path, 'w') as f:
        json.dump(summary_doc, f, indent=2)
    print(f"Stats summary saved to {summary_path}")

if __name__ == "__main__":
    main()

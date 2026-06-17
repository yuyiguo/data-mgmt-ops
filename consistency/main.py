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
    parser.add_argument("--output", default="discrepancies.json", help="Output file for discrepancies")
    
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
    results = comparator.compare()

    print(f"Results:")
    print(f"  Dark Data (correct path, not in DB): {results['stats']['total_dark']}")
    print(f"  Missing Data (in DB, not on site): {results['stats']['total_missing']}")
    print(f"  Unknown Files (invalid path format): {results['stats']['total_site_unknown']}")
    print(f"  Total Missing Size: {format_bytes(results['stats']['total_missing_bytes'])}")

    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Full results saved to {args.output}")

if __name__ == "__main__":
    main()

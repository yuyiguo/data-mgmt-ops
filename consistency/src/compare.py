from datetime import datetime, timezone

class ConsistencyComparator:
    def __init__(self, catalog_data, valid_site_replicas, unknown_site_files):
        """
        :param catalog_data: dict {(scope, name): {'bytes': size, 'adler32': adler32, 'datasets': [...]}}
        :param valid_site_replicas: list of dicts {'scope': scope, 'name': name, 'path': path, 'bytes': bytes, 'adler32': adler32}
        :param unknown_site_files: list of dicts {'path': path, 'reason': reason}
        """
        self.catalog_data = catalog_data
        self.valid_site_replicas = valid_site_replicas
        self.unknown_site_files = unknown_site_files

    def compare(self, rse=None, timestamp=None):
        """
        Performs the comparison and returns discrepancies and statistics.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        site_data = {}
        for r in self.valid_site_replicas:
            key = (r['scope'], r['name'])
            if key not in site_data:
                site_data[key] = []
            site_data[key].append(r)

        catalog_keys = set(self.catalog_data.keys())
        site_keys = set(site_data.keys())

        # Helper to attach metadata to detail objects
        def add_meta(d):
            if rse:
                d['rse'] = rse
            if timestamp:
                d['@timestamp'] = timestamp
            return d

        # Dark Data: Correct path format but NOT in Rucio
        dark_data_keys = site_keys - catalog_keys
        dark_files = []
        for key in dark_data_keys:
            replicas = site_data[key]
            dark_files.append(add_meta({
                'scope': key[0],
                'name': key[1],
                'paths': [r['path'] for r in replicas],
                'bytes': replicas[0]['bytes'],
                'adler32': replicas[0]['adler32']
            }))

        # Missing Data: In Rucio but NOT in site dump
        missing_data_keys = catalog_keys - site_keys
        missing_files = []
        missing_stats_by_dataset = {} # { (scope, dataset): {'count': 0, 'bytes': 0} }

        for key in missing_data_keys:
            entry = self.catalog_data[key]
            scope = key[0]
            datasets = entry['datasets']
            size = entry['bytes']
            
            missing_files.append(add_meta({
                'scope': scope,
                'name': key[1],
                'datasets': datasets,
                'bytes': size
            }))
            
            for dataset in datasets:
                stats_key = (scope, dataset)
                if stats_key not in missing_stats_by_dataset:
                    missing_stats_by_dataset[stats_key] = {'count': 0, 'bytes': 0}
                missing_stats_by_dataset[stats_key]['count'] += 1
                missing_stats_by_dataset[stats_key]['bytes'] += size

        # Helper to convert bytes to GB
        to_gb = lambda b: round(b / (1024.0 ** 3), 6) if b is not None else 0.0

        # Format missing_stats for JSON output
        formatted_missing_stats = []
        for (scope, dataset), stats in missing_stats_by_dataset.items():
            entry = {
                'scope': scope,
                'dataset': dataset,
                'missing_file_count': stats['count'],
                'missing_size_GB': to_gb(stats['bytes'])
            }
            formatted_missing_stats.append(add_meta(entry))

        # Checksum and Size Mismatches for common files
        size_mismatch = []
        checksum_mismatch = []

        for key in catalog_keys & site_keys:
            catalog_entry = self.catalog_data[key]
            for site_replica in site_data[key]:
                path = site_replica['path']
                site_bytes = site_replica.get('bytes')
                site_adler32 = site_replica.get('adler32')
                
                catalog_bytes = catalog_entry.get('bytes')
                catalog_adler32 = catalog_entry.get('adler32')
                
                if site_bytes is not None and catalog_bytes is not None:
                    if site_bytes != catalog_bytes:
                        size_mismatch.append(add_meta({
                            'scope': key[0],
                            'name': key[1],
                            'path': path,
                            'catalog_bytes': catalog_bytes,
                            'site_bytes': site_bytes
                        }))
                
                if site_adler32 is not None and catalog_adler32 is not None:
                    c_adler = str(catalog_adler32).strip().lower()
                    s_adler = str(site_adler32).strip().lower()
                    if c_adler != s_adler:
                        checksum_mismatch.append(add_meta({
                            'scope': key[0],
                            'name': key[1],
                            'path': path,
                            'catalog_adler32': catalog_adler32,
                            'site_adler32': site_adler32,
                            'catalog_bytes': catalog_bytes
                        }))

        # Formatted unknown_files with metadata
        unknown_files_formatted = [add_meta(dict(u)) for u in self.unknown_site_files]

        # Calculate total sizes and statistics
        total_catalog_count = len(catalog_keys)
        total_missing_count = len(missing_files)
        total_size_mismatch_count = len(size_mismatch)
        total_checksum_mismatch_count = len(checksum_mismatch)

        total_catalog_bytes = sum(self.catalog_data[k]['bytes'] for k in self.catalog_data if self.catalog_data[k]['bytes'] is not None)
        total_site_bytes = sum(r['bytes'] for r in self.valid_site_replicas if r['bytes'] is not None)
        total_dark_bytes = sum(d['bytes'] for d in dark_files if d['bytes'] is not None)
        total_missing_bytes = sum(d['bytes'] for d in missing_files if d['bytes'] is not None)
        total_size_mismatch_bytes = sum(s['catalog_bytes'] for s in size_mismatch if s.get('catalog_bytes') is not None)
        total_checksum_mismatch_bytes = sum(c['catalog_bytes'] for c in checksum_mismatch if c.get('catalog_bytes') is not None)

        # Catalog consistency percentages
        total_present_files = total_catalog_count - total_missing_count
        total_present_bytes = max(0, total_catalog_bytes - total_missing_bytes)

        mismatched_keys = set()
        for s in size_mismatch:
            mismatched_keys.add((s['scope'], s['name']))
        for c in checksum_mismatch:
            mismatched_keys.add((c['scope'], c['name']))
        
        total_consistent_files = total_catalog_count - total_missing_count - len(mismatched_keys)
        
        mismatched_bytes = 0
        for k in mismatched_keys:
            mismatched_bytes += self.catalog_data[k].get('bytes', 0)
        total_consistent_bytes = max(0, total_catalog_bytes - total_missing_bytes - mismatched_bytes)

        percentage_catalog_present_files = (total_present_files / total_catalog_count * 100) if total_catalog_count > 0 else 100.0
        percentage_catalog_present_size = (total_present_bytes / total_catalog_bytes * 100) if total_catalog_bytes > 0 else 100.0
        percentage_catalog_consistent_files = (total_consistent_files / total_catalog_count * 100) if total_catalog_count > 0 else 100.0
        percentage_catalog_consistent_size = (total_consistent_bytes / total_catalog_bytes * 100) if total_catalog_bytes > 0 else 100.0
        
        total_site_unknown_count = len(self.unknown_site_files)
        total_site_total_count = len(site_keys) + total_site_unknown_count
        percentage_site_known_files = (len(site_keys) / total_site_total_count * 100) if total_site_total_count > 0 else 100.0

        res = {
            '@timestamp': timestamp,
            'rse': rse or "UNKNOWN",
            'dark_files': dark_files,
            'missing_files': missing_files,
            'unknown_files': unknown_files_formatted,
            'size_mismatch': size_mismatch,
            'checksum_mismatch': checksum_mismatch,
            'missing_stats_by_dataset': formatted_missing_stats,
            'stats': {
                'total_catalog_file_count': total_catalog_count,
                'total_catalog_size_GB': to_gb(total_catalog_bytes),
                'total_site_valid_file_count': len(site_keys),
                'total_site_valid_size_GB': to_gb(total_site_bytes),
                'total_site_unknown_file_count': total_site_unknown_count,
                'total_dark_file_count': len(dark_files),
                'total_dark_size_GB': to_gb(total_dark_bytes),
                'total_missing_file_count': total_missing_count,
                'total_missing_size_GB': to_gb(total_missing_bytes),
                'total_size_mismatch_file_count': total_size_mismatch_count,
                'total_size_mismatch_size_GB': to_gb(total_size_mismatch_bytes),
                'total_checksum_mismatch_file_count': total_checksum_mismatch_count,
                'total_checksum_mismatch_size_GB': to_gb(total_checksum_mismatch_bytes),
                'catalog_present_files': round(percentage_catalog_present_files, 2),
                'catalog_present_size': round(percentage_catalog_present_size, 2),
                'catalog_consistent_files': round(percentage_catalog_consistent_files, 2),
                'catalog_consistent_size': round(percentage_catalog_consistent_size, 2),
                'site_known_files': round(percentage_site_known_files, 2)
            }
        }
        return res

if __name__ == "__main__":
    catalog = {
        ('scope1', 'file1'): {'bytes': 100, 'adler32': 'aaa111bbb', 'datasets': ['ds1']},
        ('scope1', 'file2'): {'bytes': 200, 'adler32': 'ccc222ddd', 'datasets': ['ds1']}
    }
    site = [
        {'scope': 'scope1', 'name': 'file1', 'path': '/prefix/scope1/file1', 'bytes': 100, 'adler32': 'aaa111bbb'},
        {'scope': 'scope1', 'name': 'file2', 'path': '/prefix/scope1/file2', 'bytes': 250, 'adler32': 'wrong_checksum'},
        {'scope': 'scope2', 'name': 'file3', 'path': '/prefix/scope2/file3', 'bytes': 500, 'adler32': 'eee333fff'}
    ]
    unknown = [{'path': '/prefix/invalid_path', 'reason': 'Invalid format'}]
    comparator = ConsistencyComparator(catalog, site, unknown)
    results = comparator.compare("TEST_RSE")
    import json
    print(json.dumps(results, indent=2))

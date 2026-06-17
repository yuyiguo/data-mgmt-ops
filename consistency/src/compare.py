class ConsistencyComparator:
    def __init__(self, catalog_data, valid_site_replicas, unknown_site_files):
        """
        :param catalog_data: dict {(scope, name): {'bytes': size, 'dataset': dataset}}
        :param valid_site_replicas: list of dicts {'scope': scope, 'name': name, 'path': path}
        :param unknown_site_files: list of dicts {'path': path, 'reason': reason}
        """
        self.catalog_data = catalog_data
        self.valid_site_replicas = valid_site_replicas
        self.unknown_site_files = unknown_site_files

    def compare(self):
        """
        Performs the comparison and returns discrepancies.
        """
        site_data = {}
        for r in self.valid_site_replicas:
            key = (r['scope'], r['name'])
            if key not in site_data:
                site_data[key] = []
            site_data[key].append(r['path'])

        catalog_keys = set(self.catalog_data.keys())
        site_keys = set(site_data.keys())

        # Dark Data: Correct path format but NOT in Rucio
        dark_data_keys = site_keys - catalog_keys
        dark_data = []
        for key in dark_data_keys:
            dark_data.append({
                'scope': key[0],
                'name': key[1],
                'paths': site_data[key]
            })

        # Missing Data: In Rucio but NOT in site dump
        missing_data_keys = catalog_keys - site_keys
        missing_data = []
        missing_stats_by_dataset = {} # { (scope, dataset): {'count': 0, 'bytes': 0} }

        for key in missing_data_keys:
            entry = self.catalog_data[key]
            scope = key[0]
            datasets = entry['datasets']
            size = entry['bytes']
            
            missing_data.append({
                'scope': scope,
                'name': key[1],
                'datasets': datasets,
                'bytes': size
            })
            
            for dataset in datasets:
                stats_key = (scope, dataset)
                if stats_key not in missing_stats_by_dataset:
                    missing_stats_by_dataset[stats_key] = {'count': 0, 'bytes': 0}
                missing_stats_by_dataset[stats_key]['count'] += 1
                missing_stats_by_dataset[stats_key]['bytes'] += size

        # Format missing_stats for JSON output
        formatted_missing_stats = []
        for (scope, dataset), stats in missing_stats_by_dataset.items():
            formatted_missing_stats.append({
                'scope': scope,
                'dataset': dataset,
                'missing_count': stats['count'],
                'missing_bytes': stats['bytes']
            })

        return {
            'dark_data': dark_data,
            'missing_data': missing_data,
            'unknown_files': self.unknown_site_files,
            'missing_stats_by_dataset': formatted_missing_stats,
            'stats': {
                'total_catalog': len(catalog_keys),
                'total_site_valid': len(site_keys),
                'total_site_unknown': len(self.unknown_site_files),
                'total_dark': len(dark_data),
                'total_missing': len(missing_data),
                'total_missing_bytes': sum(d['bytes'] for d in missing_data)
            }
        }

if __name__ == "__main__":
    # Small test case
    catalog = {('scope1', 'file1'): {'bytes': 100}, ('scope1', 'file2'): {'bytes': 200}}
    site = [
        {'scope': 'scope1', 'name': 'file1', 'path': '/prefix/scope1/file1'},
        {'scope': 'scope2', 'name': 'file3', 'path': '/prefix/scope2/file3'}
    ]
    comparator = ConsistencyComparator(catalog, site)
    results = comparator.compare()
    print(results)

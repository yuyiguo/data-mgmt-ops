import csv
import os

class CatalogIngester:
    def __init__(self, db_dump_path):
        self.db_dump_path = db_dump_path

    def ingest(self):
        """
        Ingests the Rucio DB replicas dump.
        Assumes a CSV format with at least 'scope', 'name', and 'bytes'.
        Returns a dictionary keyed by (scope, name) with 'bytes' as value.
        """
        if not os.path.exists(self.db_dump_path):
            raise FileNotFoundError(f"DB dump file not found: {self.db_dump_path}")

        catalog = {}
        with open(self.db_dump_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                scope = row.get('scope')
                name = row.get('name')
                size = row.get('bytes')
                dataset = row.get('dataset', 'UnknownDataset')
                
                if scope and name:
                    key = (scope, name)
                    if key not in catalog:
                        catalog[key] = {
                            'bytes': int(size) if size and str(size).isdigit() else 0,
                            'datasets': set()
                        }
                    catalog[key]['datasets'].add(dataset)
        
        # Convert sets back to lists for easier serialization later
        for key in catalog:
            catalog[key]['datasets'] = list(catalog[key]['datasets'])
            
        return catalog

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        ingester = CatalogIngester(sys.argv[1])
        data = ingester.ingest()
        print(f"Ingested {len(data)} catalog entries.")
        if data:
            first_key = list(data.keys())[0]
            print(f"First entry: {first_key} -> {data[first_key]}")

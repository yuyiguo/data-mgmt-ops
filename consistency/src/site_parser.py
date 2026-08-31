import os
import hashlib
import json

class SiteDumpParser:
    def __init__(self, dump_path, rse_name, rse_config_path="rse_config.json"):
        self.dump_path = dump_path
        self.rse_name = rse_name
        self.algorithm = self._load_algorithm(rse_config_path)

    def _load_algorithm(self, config_path):
        if not os.path.exists(config_path):
            print(f"Warning: {config_path} not found. Defaulting to 'hash' algorithm.")
            return "hash"
        
        with open(config_path, 'r') as f:
            config = json.load(f)
            rse_info = config.get(self.rse_name, {})
            return rse_info.get("lfn2pfn_algorithm", "hash")

    @staticmethod
    def get_rucio_hash(scope, name):
        """Standard Rucio 'hash' algorithm."""
        s = f"{scope}:{name}"
        h = hashlib.md5(s.encode()).hexdigest()
        return f"{h[:2]}/{h[2:4]}"

    @staticmethod
    def _strip_known_prefix(path):
        for prefix in ("dune/RSE/", "protodune/RSE/", "RSE/"):
            if path.startswith(prefix):
                return path[len(prefix):]
        return path

    def validate_path(self, path):
        """
        Validates the path based on the RSE's algorithm.
        Returns (is_valid, scope, name, reason)
        """
        path = self._strip_known_prefix(path.lstrip('/'))
            
        parts = path.split('/')
        if not parts or not parts[-1]:
            return False, None, None, "Empty path or filename"
        
        name = parts[-1]
        scope = parts[0] if len(parts) > 0 else "unknown"

        # Special Case: DUNE Algorithm or Deterministic (per user request: only match scope/name)
        if self.algorithm == "DUNE" or self.algorithm == "deterministic":
            # For now, we only care that we can extract a scope and name
            if len(parts) >= 2:
                return True, scope, name, None
            return False, scope, name, "Path too short to extract scope/name"

        if self.algorithm == "hash":
            if len(parts) < 4:
                return False, scope, name, "Path too short for hash algo (expected /scope/h1/h2/LFN)"

            # Site dumps may include a storage mount prefix before the Rucio
            # deterministic path, e.g. /cephfs/grid/dune/<scope>/<h1>/<h2>/<LFN>.
            scope = parts[-4]
            actual_hash = "/".join(parts[-3:-1])
            expected_hash = self.get_rucio_hash(scope, name)
            
            if actual_hash == expected_hash:
                return True, scope, name, None
            else:
                # If name matches but hash doesn't, it is UNKNOWN
                return False, scope, name, f"Hash mismatch. Expected {expected_hash}, got {actual_hash}"

        elif self.algorithm == "identity":
            return True, scope, name, None

        return False, scope, name, f"Unsupported algorithm: {self.algorithm}"

    def parse(self):
        """
        Parses the site dump file.
        Returns two lists: 'valid_replicas' and 'unknown_files'.
        """
        if not os.path.exists(self.dump_path):
            raise FileNotFoundError(f"Dump file not found: {self.dump_path}")

        valid_replicas = []
        unknown_files = []

        with open(self.dump_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                if '\t' in line:
                    parts = line.split('\t')
                else:
                    parts = line.split()
                
                path = parts[0] if parts else ''
                size = None
                adler32 = None
                
                if len(parts) > 1:
                    try:
                        size = int(parts[1])
                    except ValueError:
                        pass
                if len(parts) > 2:
                    adler32 = parts[2]
                    if adler32.upper() == 'N/A':
                        adler32 = None
                
                is_valid, scope, name, reason = self.validate_path(path)
                
                entry = {
                    'scope': scope,
                    'name': name,
                    'path': path,
                    'bytes': size,
                    'adler32': adler32
                }

                if is_valid:
                    valid_replicas.append(entry)
                else:
                    entry['reason'] = reason
                    unknown_files.append(entry)
                    
        return valid_replicas, unknown_files

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        parser = SiteDumpParser(sys.argv[1])
        results = parser.parse()
        print(f"Parsed {len(results)} replicas.")
        if results:
            print(f"First 5 results: {results[:5]}")

import json
import sys
from rucio.client.rseclient import RSEClient

def fetch_rse_config(output_file="rse_config.json"):
    """
    Connects to Rucio and fetches the lfn2pfn_algorithm for all active RSEs.
    Excludes RSEs marked as decommissioned.
    Saves the mapping to a JSON file.
    """
    try:
        client = RSEClient()
        # List all RSEs and filter in Python
        rses = client.list_rses()
        
        rse_config = {}
        for rse_dict in rses:
            rse_name = rse_dict['rse']
            try:
                # Check attributes for decommissioned status
                attributes = client.list_rse_attributes(rse_name)
                if attributes.get('decommissioned') == 'True' or attributes.get('decommissioned') is True:
                    print(f"Skipping {rse_name} (decommissioned)")
                    continue

                info = client.get_rse(rse_name)
                algo = info.get('lfn2pfn_algorithm', 'hash')
                rse_type = info.get('rse_type', 'DISK')
                
                rse_config[rse_name] = {
                    'lfn2pfn_algorithm': algo,
                    'is_deterministic': info.get('deterministic', True),
                    'rse_type': rse_type
                }
                print(f"Fetched {rse_name}: {algo} ({rse_type})")
            except Exception as e:
                print(f"Error fetching details for {rse_name}: {e}")
                
        with open(output_file, 'w') as f:
            json.dump(rse_config, f, indent=4)
        print(f"\nSuccessfully saved configuration for {len(rse_config)} RSEs to {output_file}")

    except Exception as e:
        print(f"Failed to connect to Rucio: {e}")
        sys.exit(1)

if __name__ == "__main__":
    fetch_rse_config()

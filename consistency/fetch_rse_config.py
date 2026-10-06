import json
import os
import sys
from rucio.client.rseclient import RSEClient


def load_existing_config(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def fetch_protocol_prefixes(client, rse_name):
    try:
        protocols = client.get_protocols(rse_name)
    except AttributeError:
        try:
            protocols = client.list_rse_protocols(rse_name)
        except AttributeError:
            return []

    if isinstance(protocols, dict):
        protocols = protocols.get("protocols", [])

    prefixes = []
    for protocol in protocols or []:
        prefix = protocol.get("prefix")
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


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
        
        existing_config = load_existing_config(output_file)
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
                protocol_prefixes = fetch_protocol_prefixes(client, rse_name)
                existing = existing_config.get(rse_name, {})
                
                rse_config[rse_name] = dict(existing)
                rse_config[rse_name].update({
                    'lfn2pfn_algorithm': algo,
                    'is_deterministic': info.get('deterministic', True),
                    'rse_type': rse_type
                })
                if protocol_prefixes and not existing.get('prefix'):
                    rse_config[rse_name]['prefix'] = protocol_prefixes[0]
                if protocol_prefixes:
                    rse_config[rse_name]['protocol_prefixes'] = protocol_prefixes
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

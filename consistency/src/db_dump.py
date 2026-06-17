import json
import csv
import sys
import os
from sqlalchemy import create_engine, text

def get_db_engine(config_path):
    with open(config_path, 'r') as f:
        conf = json.load(f)
    
    # Construct connection string based on db_type
    db_type = conf.get('db_type', 'postgresql')
    user = conf['user']
    import urllib.parse
    password = urllib.parse.quote_plus(conf['password'])
    host = conf['host']
    port = conf['port']
    dbname = conf['dbname']

    if db_type == 'postgresql':
        url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    elif db_type == 'oracle':
        # Requires cx_Oracle or oracledb
        url = f"oracle+thin://{user}:{password}@{host}:{port}/?service_name={dbname}"
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

    return create_engine(url)

def dump_replicas(rse_name, output_path, config_path):
    engine = get_db_engine(config_path)
    
    # Query to get scope, name, bytes, and the parent dataset
    # Note: Using a subquery or join to get the dataset name from the 'contents' table
    query = text("""
        SELECT 
            r.scope, 
            r.name, 
            r.bytes, 
            c.name as dataset
        FROM replicas r
        JOIN rses rs ON r.rse_id = rs.id
        LEFT JOIN contents c ON r.scope = c.child_scope AND r.name = c.child_name
        WHERE rs.rse = :rse_name
    """)

    print(f"Connecting to database and dumping replicas for RSE: {rse_name}...")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"rse_name": rse_name})
            
            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['scope', 'name', 'bytes', 'dataset']) # Header
                
                count = 0
                for row in result:
                    writer.writerow(row)
                    count += 1
                    if count % 100000 == 0:
                        print(f"  Dumped {count} rows...")
                        
        print(f"Successfully dumped {count} replicas to {output_path}")

    except Exception as e:
        print(f"Error during DB dump: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 db_dump.py <RSE_NAME> <OUTPUT_CSV_PATH>")
        sys.exit(1)
    
    rse = sys.argv[1]
    output = sys.argv[2]
    secrets = os.path.join(os.path.dirname(__file__), "..", "etc", ".secrets", "db.json")
    
    dump_replicas(rse, output, secrets)

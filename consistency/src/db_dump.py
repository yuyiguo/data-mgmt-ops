import json
import csv
import sys
import os
import time
import argparse
from sqlalchemy import create_engine, text

def format_elapsed(seconds):
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {seconds:.2f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {seconds:.2f}s"

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

def get_rse_id(conn, rse_name):
    query = text("""
        SELECT id
        FROM rses
        WHERE rse = :rse_name
    """)
    rows = conn.execute(query, {"rse_name": rse_name}).fetchall()

    if not rows:
        raise ValueError(f"RSE not found in rses table: {rse_name}")
    if len(rows) > 1:
        raise ValueError(f"Multiple rses rows found for {rse_name}; cannot choose a unique rse_id")

    return rows[0][0]

def dump_replicas(rse_name, output_path, config_path, fetch_size=10000):
    total_start = time.perf_counter()
    engine = get_db_engine(config_path)
    count = 0
    
    # Query to get scope, name, bytes, adler32, and the parent dataset
    # Note: Filter replicas directly by rse_id, then join contents for the dataset name.
    query = text("""
        SELECT 
            r.scope, 
            r.name, 
            r.bytes, 
            r.adler32, 
            c.name as dataset
        FROM replicas r
        LEFT JOIN contents c ON r.scope = c.child_scope AND r.name = c.child_name
        WHERE r.rse_id = :rse_id
    """)

    print(f"Connecting to database and dumping replicas for RSE: {rse_name}...")
    
    try:
        phase_start = time.perf_counter()
        with engine.connect() as conn:
            print(f"Connected to database in {format_elapsed(time.perf_counter() - phase_start)}")

            phase_start = time.perf_counter()
            rse_id = get_rse_id(conn, rse_name)
            print(f"Resolved RSE ID: {rse_id}")
            print(f"RSE ID lookup completed in {format_elapsed(time.perf_counter() - phase_start)}")

            phase_start = time.perf_counter()
            stream_conn = conn.execution_options(stream_results=True, yield_per=fetch_size)
            result = stream_conn.execute(query, {"rse_id": rse_id}).yield_per(fetch_size)
            print(f"Replica query started in {format_elapsed(time.perf_counter() - phase_start)}")
            print(f"Streaming query results with fetch size {fetch_size}")
            
            write_start = time.perf_counter()
            last_progress = write_start
            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['scope', 'name', 'bytes', 'adler32', 'dataset']) # Header
                
                for row in result:
                    writer.writerow(row)
                    count += 1
                    if count % 100000 == 0:
                        now = time.perf_counter()
                        total_rate = count / (now - write_start)
                        batch_rate = 100000 / (now - last_progress)
                        print(
                            f"  Dumped {count} rows "
                            f"(write elapsed {format_elapsed(now - write_start)}, "
                            f"batch {batch_rate:.0f} rows/s, avg {total_rate:.0f} rows/s)..."
                        )
                        last_progress = now

            print(f"CSV write completed in {format_elapsed(time.perf_counter() - write_start)}")
                        
        print(f"Successfully dumped {count} replicas to {output_path}")
        print(f"Total DB dump time: {format_elapsed(time.perf_counter() - total_start)}")

    except KeyboardInterrupt:
        print(f"DB dump interrupted after {format_elapsed(time.perf_counter() - total_start)}")
        print(f"Rows written before interruption: {count}")
        sys.exit(130)
    except Exception as e:
        print(f"Error during DB dump: {e}")
        print(f"DB dump failed after {format_elapsed(time.perf_counter() - total_start)}")
        print(f"Rows written before failure: {count}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dump Rucio replicas for one RSE to CSV")
    parser.add_argument("rse", help="Name of the RSE to dump")
    parser.add_argument("output", help="Output CSV path")
    parser.add_argument(
        "--fetch-size",
        type=int,
        default=10000,
        help="Number of rows to fetch per database round trip when streaming results",
    )
    args = parser.parse_args()

    if args.fetch_size <= 0:
        print("Error: --fetch-size must be positive", file=sys.stderr)
        sys.exit(2)

    secrets = os.path.join(os.path.dirname(__file__), "..", "etc", ".secrets", "db.json")
    
    dump_replicas(args.rse, args.output, secrets, fetch_size=args.fetch_size)

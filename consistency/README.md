# DUNE Rucio Consistency Checker

This tool compares Rucio's catalog (Database) against physical storage (Site Dumps) to identify inconsistencies in the DUNE data environment.

## File Categorization

The tool categorizes files into four distinct states:

| Category | Definition | Rucio Status | Physical Status |
| :--- | :--- | :--- | :--- |
| **Valid Site Replica** | Path follows `/scope/hash1/hash2/LFN` and matches Rucio MD5 hash. | TBD (compared later) | OK |
| **Unknown File** | Path does not follow the Rucio deterministic hash format. | N/A | Malformed Path |
| **Dark Data** | File has a valid Rucio path format but is **not** in the Rucio DB. | Missing | Present |
| **Missing Data** | File is registered in the Rucio DB but is **not** in the Site Dump. | Present | Missing |
| **Lost Data** | File is permanently lost (not part of this daily check). | N/A | N/A |

> **Note on Rucio Hash:** The hash is calculated as `MD5(scope:LFN)`. The first two characters of the MD5 are `hash1`, and the next two are `hash2`.

## Input Requirements

### 1. Site Admin Storage Dump (`--site-dump`)
A plain text file provided by the site admin.
- **Format:** One absolute path per line.
- **Requirement:** No size information is required.
- **Example:**
  ```
  /fardet-hd/00/03/anue_dune10kt_1x2x6_..._ana.root
  ```

### 2. Rucio DB Replica Dump (`--db-dump`)
A CSV export from the Rucio database (specifically the `replicas` table joined with dataset info).
- **Format:** CSV with headers.
- **Required Columns:** `scope`, `name`, `bytes`, `dataset`.
- **Example:**
  ```csv
  scope,name,bytes,dataset
  fardet-hd,file1.root,1048576,dataset_A
  ```

## Outputs

### 1. Console Summary
A high-level overview of the counts for Dark, Missing, and Unknown data, including the total volume (in bytes) of missing data.

### 2. Discrepancies Report (`--output`)
A detailed JSON file containing:
- `dark_data`: List of files found on site with correct paths but missing from Rucio.
- `missing_data`: List of files in Rucio missing from the site, including their size and dataset.
- `unknown_files`: List of files on site with invalid Rucio path formats.
- `missing_stats_by_dataset`: Aggregated statistics (file count and total bytes) of missing data per Scope and Dataset.

## Usage

### 1. Manual Automation (Recommended)
Use the provided shell script to automate directory creation, DB dumping, and consistency checking in one command:

```bash
./run_check.sh <RSE_NAME> <SITE_DUMP_PATH> <DATE_STAMP>
```

**Example:**
```bash
./run_check.sh DUNE_UK_MANCHESTER_CEPH gfal-downloads/DUNE_UK_MANCHESTER_CEPH/manchester-20260611 20260611
```

### 2. Manual Step-by-Step
If you need more control, you can run the components individually:

**Generate DB Dump:**
```bash
PYTHONPATH=. python3 src/db_dump.py <RSE_NAME> <OUTPUT_CSV>
```

**Run Checker:**
```bash
python3 main.py --rse <RSE_NAME> --site-dump /path/to/site_dump.txt --db-dump /path/to/rucio_db.csv --output results.json
```

## Configuration

*   **RSE Config (`rse_config.json`):** Contains site-specific `lfn2pfn` algorithms. Update manually using `fetch_rse_config.py`.
*   **DB Secrets (`etc/.secrets/db.json`):** Database connection details (Host, Port, User, Password, DBName).

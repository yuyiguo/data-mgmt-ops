# DUNE Rucio Consistency Checker
Yuyi Guo Aug. 28, 2026

This tool compares Rucio's catalog (Database) against physical storage (Site Dumps) to identify inconsistencies in the DUNE data environment.

## File Categorization

The tool categorizes files into the following distinct states:

| Category | Definition | Rucio Status | Physical Status |
| :--- | :--- | :--- | :--- |
| **Valid Site Replica** | Path follows `/scope/hash1/hash2/LFN` and matches Rucio MD5 hash. | TBD (compared later) | OK |
| **Unknown File** | Path does not follow the Rucio deterministic hash format. | N/A | Malformed Path |
| **Dark Files** | File has a valid Rucio path format but is **not** in the Rucio DB. | Missing | Present |
| **Missing Files** | File is registered in the Rucio DB but is **not** in the Site Dump. | Present | Missing |
| **Size Mismatch** | File exists in both DB and site, but their sizes do not match. | Present | Present (Size mismatch) |
| **Checksum Mismatch** | File exists in both DB and site, but their checksums do not match. | Present | Present (Checksum mismatch) |
| **Lost Data** | File is permanently lost (not part of this daily check). | N/A | N/A |

> **Note on Rucio Hash:** The hash is calculated as `MD5(scope:LFN)`. The first two characters of the MD5 are `hash1`, and the next two are `hash2`.

## Input Requirements

### 1. Site Admin Storage Dump (`--site-dump`)
A plain text file provided by the site admin.
- **Format:** One absolute path, file size and checksum/adler32 per line.
- **Example:**
  ```
  /protodune/RSE/ehn1-beam-np04/01/85/H4_v34b_-1GeV_-27.7_001921_20250614T054346Z_001921.root     27709722        feae4721
  ```

### 2. Rucio DB Replica Dump (`--db-dump`)
A CSV export from the Rucio database (specifically the `replicas` table joined with dataset info).
- **Format:** CSV with headers.
- **Required Columns:** `scope`, `name`, `bytes`, `dataset`.
- **Example:**
  ```csv
  scope,name,bytes,adler32,dataset 
  usertests,H2_v27c_0.5GeV_000298_20260226T124733Z_000298.root,19607810,4ad1e1bf,fnal-w13788s1p1-RAL-PP 
 ```

## Outputs

### 1. Console Summary
A high-level overview of counts, sizes (in GB), consistency percentages (present files/sizes, fully matching files/sizes), and mismatches (size, checksum) for the RSE.

### 2. Discrepancies Report (`--output`)
A detailed JSON file containing:
- `dark_files`: List of files found on site with correct paths but missing from Rucio.
- `missing_files`: List of files in Rucio missing from the site, including their size and dataset.
- `unknown_files`: List of files on site with invalid Rucio path formats.
- `size_mismatch`: List of files present in both catalog and site storage but differing in size.
- `checksum_mismatch`: List of files present in both catalog and site storage but differing in adler32 checksum.
- `missing_stats_by_dataset`: Aggregated statistics (`missing_file_count`, `missing_bytes`, and `missing_size_GB`) of missing data per Scope and Dataset.
- `stats`: General summary statistics, size metrics in GB, checksum mismatch volumes, and catalog consistency metrics.

### 3. Stats Summary (`--summary`)
A lightweight JSON file containing `rse` and the `stats` dictionary. This file is intended for low-cardinality dashboard metrics export.

### 4. Catalog Consistency Metrics
The statistics section (`stats` dictionary) in the JSON report includes consistency percentages:

*   **`catalog_present_files`** (or `catalog_present_files_pct`): Percentage of catalog files present physically on site (regardless of size/checksum mismatch).
    $$\text{Present Files \%} = \frac{\text{Total Catalog File Count} - \text{Total Missing File Count}}{\text{Total Catalog File Count}} \times 100$$
*   **`catalog_present_size`** (or `catalog_present_size_pct`): Percentage of catalog data volume (bytes) present physically on site.
    $$\text{Present Size \%} = \frac{\text{Total Catalog Bytes} - \text{Total Missing Bytes}}{\text{Total Catalog Bytes}} \times 100$$
*   **`catalog_consistent_files`** (or `catalog_consistent_files_pct`): Percentage of catalog files present on site **and** fully matching in size and checksum.
    $$\text{Consistent Files \%} = \frac{\text{Total Catalog File Count} - \text{Total Missing File Count} - \text{Mismatched Files Count}}{\text{Total Catalog File Count}} \times 100$$
*   **`catalog_consistent_size`** (or `catalog_consistent_size_pct`): Percentage of catalog volume present on site **and** fully matching in size and checksum.
    $$\text{Consistent Size \%} = \frac{\text{Total Catalog Bytes} - \text{Total Missing Bytes} - \text{Mismatched Bytes}}{\text{Total Catalog Bytes}} \times 100$$
*   **`site_known_files`** (or `site_known_files_pct`): Percentage of physical files on site that follow valid Rucio path structures.
    $$\text{Site Known Files \%} = \frac{\text{Total Site Valid File Count}}{\text{Total Site Valid File Count} + \text{Total Site Unknown File Count}} \times 100$$

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

The DB dump streams query results in batches instead of buffering the full result set in the client. The default fetch size is `10000` rows. You can tune it with:

```bash
PYTHONPATH=. python3 src/db_dump.py <RSE_NAME> <OUTPUT_CSV> --fetch-size 5000
```

**Run Checker:**
```bash
python3 main.py --rse <RSE_NAME> --site-dump /path/to/site_dump.txt --db-dump /path/to/rucio_db.csv --output results.json
```

For large dumps where you only need `summary.json` for Landscape metrics, use summary-only mode. This streams the site dump and skips the detailed `results.json` discrepancy lists:

```bash
python3 main.py --rse <RSE_NAME> --site-dump /path/to/site_dump.txt --db-dump /path/to/rucio_db.csv --summary summary.json --summary-only
```

### 3. Export to Landscape
The checker output can be exported to Landscape as OpenTelemetry data without rerunning the check:

```bash
source setup_landscape_otlp.sh

landscape_export_summary DUNE_UK_MANCHESTER_CEPH 20260611
landscape_export_results_logs DUNE_UK_MANCHESTER_CEPH 20260611
```

Use `--dry-run` to validate record counts without posting to Landscape.

The exporter sends `summary.json` stats as low-cardinality metrics with `rse` as a metric attribute. It sends `results.json` discrepancies and `missing_stats_by_dataset` as structured logs. Missing-file records with multiple datasets are normalized to one log record per dataset so queries like `event_type = "missing_file" AND dataset = "abc"` work reliably.

### 4. Monthly Automation
The monthly automation discovers new remote site dumps, copies them locally, runs the checker, exports summary metrics to Landscape, and records state only after a successful export.

Configure remote dump locations in `rse_url.txt`:

```text
# rse_name remote_url local_dir mode
QMUL https://webdav.esc.qmul.ac.uk:8443/dune/dumps gfal-downloads/QMUL list
RAL_ECHO https://webdav.echo.stfc.ac.uk:1094/dune:/protodune/dumps/dump_latest gfal-downloads/RAL_ECHO latest
```

Modes:

*   `list`: use `gfal-ls` on `remote_url`, then `gfal-stat` candidate dump files.
*   `latest`: do not list; use `gfal-stat` directly on `remote_url` and copy it locally as `dump_YYYYMMDD` based on the remote creation or modification time.

The automation tracks processed remote metadata in `state/rse_dumps.json`. A dump is treated as new when the remote path, size, creation time, or modification time differs from the saved state. By default, the selected remote dump is stat'ed twice with a 300 second wait, and it is skipped if metadata changes during that interval.

Run the same workflow manually at any time:

```bash
cd /Users/yuyi/github-dev/data-mgmt-ops/consistency
source setup_landscape_otlp.sh
./monthly_check_and_export.sh
```

That performs the same steps as the cron job for every RSE in `rse_url.txt`: refresh a GFAL token, discover new dumps, copy new dumps locally, run the checker, export summary metrics to Landscape, and update `state/rse_dumps.json` after success.

Monthly automation runs the checker with `CHECKER_SUMMARY_ONLY=1` by default. This is the intended mode for the metric dashboard because it avoids keeping millions of detailed discrepancy records in memory. To force full `results.json` generation from the monthly script, set:

```bash
export CHECKER_MONTHLY_SUMMARY_ONLY=0
```

Before running on a new server checkout, create the local DB secrets file. It is intentionally ignored by Git:

```bash
mkdir -p etc/.secrets
vi etc/.secrets/db.json
```

Before running the full workflow, you can inspect what discovery would process:

```bash
python3 src/discover_new_dump.py discover \
  --config rse_url.txt \
  --state state/rse_dumps.json \
  --stability-wait 0
```

To inspect one RSE:

```bash
python3 src/discover_new_dump.py discover \
  --config rse_url.txt \
  --state state/rse_dumps.json \
  --rse QMUL \
  --stability-wait 0
```

To force discovery to emit current remote dumps even if they are already recorded in state:

```bash
python3 src/discover_new_dump.py discover \
  --config rse_url.txt \
  --state state/rse_dumps.json \
  --all \
  --stability-wait 0
```

For a full manual run with the same stability check used by cron:

```bash
export CHECKER_PYTHON=/Users/yuyi/venv312/bin/python3
export DUMP_STABILITY_WAIT_SECONDS=300
export CHECKER_ALERT_EMAIL=you@example.org

source setup_landscape_otlp.sh
./monthly_check_and_export.sh
```

After a run, check:

```bash
tail -n 100 logs/monthly_checker.log
find logs -path '*/export_summary.log' -mtime -1 -print
cat state/rse_dumps.json
```

Useful environment variables:

```bash
export DUMP_STABILITY_WAIT_SECONDS=300
export CHECKER_ALERT_EMAIL=you@example.org
export CHECKER_PYTHON=/Users/yuyi/venv312/bin/python3
export CHECKER_MONTHLY_SUMMARY_ONLY=1
export HTGETTOKENOPTS=--credkey=dunepro/managedtokens/fifeutilgpvm01.fnal.gov
```

`setup_landscape_otlp.sh` defines `setup_gfal_token`, but does not refresh a token just by being sourced. The monthly automation refreshes the short-lived DUNE production token immediately before GFAL discovery and before each GFAL copy:

```bash
HTGETTOKENOPTS=--credkey=dunepro/managedtokens/fifeutilgpvm01.fnal.gov \
  htgettoken -i dune -r production -a htvaultprod.fnal.gov
export BEARER_TOKEN="$(cat /run/user/$(id -u)/bt_u$(id -u))"
```

Landscape metric timestamps use the remote dump creation time when available. If `gfal-stat` does not expose creation time for a site, the automation falls back to modification time.

If `CHECKER_ALERT_EMAIL` is set and the `mail` command is available, failures send an email with the failed stage and the tail of the stage log.

Cron runs without your interactive shell environment. Before relying on the midnight job, confirm that the cron context can obtain a token. The token stage logs are:

```bash
logs/<RSE>/<RUN_DATE>/gfal_token_copy.log
```

and for discovery:

```bash
/tmp/rucio-consistency.*/gfal_token_discover.log
```

Those logs print the cron user, `XDG_RUNTIME_DIR`, `HTGETTOKENOPTS`, and the expected bearer token path. The server login environment normally sets `HTGETTOKENOPTS`, but cron does not. `setup_landscape_otlp.sh` sets a default managed-token credkey for the `dunepro` cron job:

```bash
HTGETTOKENOPTS=--credkey=dunepro/managedtokens/fifeutilgpvm01.fnal.gov
```

Cron example for midnight US Central time, assuming the VM timezone is `America/Chicago`:

```cron
0 0 * * * cd /Users/yuyi/github-dev/data-mgmt-ops/consistency && /bin/bash ./monthly_check_and_export.sh >> logs/cron.log 2>&1
```

The automation writes an audit log to `logs/monthly_checker.log` and per-RSE stage logs under `logs/<RSE>/<RUN_DATE>/`.

## Configuration

*   **RSE Config (`rse_config.json`):** Contains site-specific `lfn2pfn` algorithms. Update manually using `fetch_rse_config.py`.
*   **DB Secrets (`etc/.secrets/db.json`):** Database connection details (Host, Port, User, Password, DBName).

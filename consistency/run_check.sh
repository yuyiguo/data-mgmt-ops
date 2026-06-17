#!/bin/bash

# DUNE Rucio Consistency Checker - Automation Script
# Usage: ./run_check.sh <RSE_NAME> <SITE_DUMP_PATH> <DATE_STAMP>

if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <RSE_NAME> <SITE_DUMP_PATH> <DATE_STAMP>"
    echo "Example: $0 DUNE_UK_MANCHESTER_CEPH gfal-downloads/DUNE_UK_MANCHESTER_CEPH/manchester-20260611 20260611"
    exit 1
fi

RSE=$1
SITE_DUMP=$2
DATE=$3

# Project paths
PROJECT_ROOT=$(pwd)
# Default to venv if it exists, otherwise use system python3
VENV_PYTHON="$PROJECT_ROOT/../../venv312/bin/python3"
if [ -f "$VENV_PYTHON" ]; then
    PYTHON_BIN="$VENV_PYTHON"
else
    PYTHON_BIN=$(which python3)
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "Error: python3 not found."
    exit 1
fi
DB_DUMP_DIR="db-dump/$RSE"
OUTPUT_DIR="check-output/$RSE/$DATE"
RSE_LOWER=$(echo "$RSE" | tr '[:upper:]' '[:lower:]')
DB_DUMP_FILE="$DB_DUMP_DIR/${RSE_LOWER}-db-$DATE.csv"
RESULTS_FILE="$OUTPUT_DIR/results.json"

# 1. Create necessary directories
echo "--- Preparing Directories ---"
mkdir -p "$DB_DUMP_DIR"
mkdir -p "$OUTPUT_DIR"
echo "Directories ready: $DB_DUMP_DIR, $OUTPUT_DIR"

# 2. Generate DB Dump
echo "--- Step 1: Generating DB Dump ---"
export PYTHONPATH="$PROJECT_ROOT"
$PYTHON_BIN src/db_dump.py "$RSE" "$DB_DUMP_FILE"

if [ $? -ne 0 ]; then
    echo "Error: DB dump failed."
    exit 1
fi

# 3. Run Consistency Check
echo "--- Step 2: Running Consistency Check ---"
$PYTHON_BIN main.py \
    --rse "$RSE" \
    --site-dump "$SITE_DUMP" \
    --db-dump "$DB_DUMP_FILE" \
    --output "$RESULTS_FILE"

if [ $? -ne 0 ]; then
    echo "Error: Consistency check failed."
    exit 1
fi

echo "--- Process Complete ---"
echo "Results saved to: $RESULTS_FILE"

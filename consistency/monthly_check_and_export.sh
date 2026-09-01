#!/usr/bin/env bash

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT" || exit 1

CONFIG_FILE="${CHECKER_RSE_URL_FILE:-rse_url.txt}"
STATE_FILE="${CHECKER_STATE_FILE:-state/rse_dumps.json}"
LOG_ROOT="${CHECKER_LOG_ROOT:-logs}"
AUDIT_LOG="${CHECKER_AUDIT_LOG:-$LOG_ROOT/monthly_checker.log}"
STABILITY_WAIT_SECONDS="${DUMP_STABILITY_WAIT_SECONDS:-300}"
PYTHON_BIN="${CHECKER_PYTHON:-python3}"
ALERT_EMAIL="${CHECKER_ALERT_EMAIL:-}"
MONTHLY_SUMMARY_ONLY="${CHECKER_MONTHLY_SUMMARY_ONLY:-1}"

mkdir -p "$LOG_ROOT" "$(dirname "$STATE_FILE")"

timestamp() {
    date +"%Y-%m-%dT%H:%M:%S%z"
}

audit() {
    echo "[$(timestamp)] $*" | tee -a "$AUDIT_LOG"
}

display_log_path() {
    case "$1" in
        /*) echo "$1" ;;
        *) echo "$PROJECT_ROOT/$1" ;;
    esac
}

send_failure_email() {
    local rse="$1"
    local stage="$2"
    local log_file="$3"

    if [ -z "$ALERT_EMAIL" ]; then
        return 0
    fi
    if ! command -v mail >/dev/null 2>&1; then
        audit "EMAIL_SKIPPED mail_command_not_found to=$ALERT_EMAIL"
        return 0
    fi

    {
        echo "Rucio consistency checker failed."
        echo
        echo "RSE: $rse"
        echo "Stage: $stage"
        echo "Host: $(hostname)"
        echo "Time: $(timestamp)"
        echo "Log: $(display_log_path "$log_file")"
        echo
        echo "Last 80 log lines:"
        tail -n 80 "$log_file" 2>/dev/null
    } | mail -s "Rucio consistency checker failed: $rse $stage" "$ALERT_EMAIL"
}

run_stage() {
    local rse="$1"
    local stage="$2"
    local log_file="$3"
    shift 3

    audit "STAGE_START rse=$rse stage=$stage log=$log_file"
    "$@" >"$log_file" 2>&1
    local rc=$?
    if [ $rc -ne 0 ]; then
        audit "STAGE_FAILED rse=$rse stage=$stage rc=$rc log=$log_file"
        send_failure_email "$rse" "$stage" "$log_file"
        return $rc
    fi
    audit "STAGE_OK rse=$rse stage=$stage log=$log_file"
    return 0
}

source setup_landscape_otlp.sh >/dev/null

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/rucio-consistency.XXXXXX")"
DISCOVER_JSON="$WORK_DIR/work_items.json"

audit "DISCOVER_START config=$CONFIG_FILE state=$STATE_FILE stability_wait=${STABILITY_WAIT_SECONDS}s"
if ! run_stage "ALL" "gfal_token_discover" "$WORK_DIR/gfal_token_discover.log" \
    setup_gfal_token; then
    exit 1
fi

if ! "$PYTHON_BIN" src/discover_new_dump.py discover \
    --config "$CONFIG_FILE" \
    --state "$STATE_FILE" \
    --stability-wait "$STABILITY_WAIT_SECONDS" \
    >"$DISCOVER_JSON" 2>"$WORK_DIR/discover.err"; then
    audit "DISCOVER_FAILED stderr=$WORK_DIR/discover.err"
    send_failure_email "ALL" "discover" "$WORK_DIR/discover.err"
    exit 1
fi

"$PYTHON_BIN" - "$DISCOVER_JSON" "$WORK_DIR" <<'PY'
import json
import os
import sys

with open(sys.argv[1]) as f:
    items = json.load(f)

for index, item in enumerate(items):
    path = os.path.join(sys.argv[2], f"item_{index:04d}.json")
    with open(path, "w") as f:
        json.dump(item, f)
PY

item_count=$(find "$WORK_DIR" -name 'item_*.json' | wc -l | tr -d ' ')
audit "DISCOVER_OK new_dumps=$item_count"

if [ "$item_count" -eq 0 ]; then
    audit "NO_NEW_DUMPS"
    exit 0
fi

for item_file in "$WORK_DIR"/item_*.json; do
    rse=$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["rse"])' "$item_file")
    remote_path=$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["remote_path"])' "$item_file")
    local_path=$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["local_path"])' "$item_file")
    local_dir=$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["local_dir"])' "$item_file")
    run_date=$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_date"])' "$item_file")
    created_at=$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("created_at") or "")' "$item_file")
    modified_at=$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("modified_at") or "")' "$item_file")
    dump_timestamp="${created_at:-$modified_at}"

    run_log_dir="$LOG_ROOT/$rse/$run_date"
    mkdir -p "$run_log_dir" "$local_dir"

    audit "RSE_START rse=$rse run_date=$run_date remote=$remote_path local=$local_path created_at=${created_at:-unknown} modified_at=${modified_at:-unknown}"

    if ! run_stage "$rse" "gfal_token_copy" "$run_log_dir/gfal_token_copy.log" \
        setup_gfal_token; then
        continue
    fi

    copy_url="file://$PROJECT_ROOT/$local_path"
    if ! run_stage "$rse" "copy" "$run_log_dir/copy.log" \
        gfal-copy -f "$remote_path" "$copy_url"; then
        continue
    fi

    if [ "$MONTHLY_SUMMARY_ONLY" = "1" ]; then
        if ! run_stage "$rse" "check" "$run_log_dir/check.log" \
            env CHECKER_SUMMARY_ONLY=1 ./run_check.sh "$rse" "$local_path" "$run_date"; then
            continue
        fi
    else
        if ! run_stage "$rse" "check" "$run_log_dir/check.log" \
            ./run_check.sh "$rse" "$local_path" "$run_date"; then
            continue
        fi
    fi

    export_args=()
    if [ -n "$dump_timestamp" ]; then
        export_args+=(--timestamp "$dump_timestamp")
    fi

    if ! run_stage "$rse" "export_summary" "$run_log_dir/export_summary.log" \
        landscape_export_summary "$rse" "$run_date" "${export_args[@]}"; then
        continue
    fi

    if ! run_stage "$rse" "mark_processed" "$run_log_dir/mark_processed.log" \
        "$PYTHON_BIN" src/discover_new_dump.py mark-processed \
            --state "$STATE_FILE" \
            --item "$item_file"; then
        continue
    fi

    audit "RSE_DONE rse=$rse run_date=$run_date"
done

audit "RUN_DONE"

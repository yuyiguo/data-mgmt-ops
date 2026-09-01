#!/usr/bin/env bash

# Source this file from the repository root before exporting checker output:
#
#   source setup_landscape_otlp.sh
#   landscape_export_summary DUNE_UK_LANCASTER_CEPH 20260819
#
# To validate without posting:
#
#   landscape_export_summary DUNE_UK_LANCASTER_CEPH 20260819 --dry-run

export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-https://landscape.fnal.gov/otlp}"
export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-dune-rucio-consistency-checker}"
export HTGETTOKENOPTS="${HTGETTOKENOPTS:---credkey=dunepro/managedtokens/fifeutilgpvm01.fnal.gov}"

_landscape_instance_id="${LANDSCAPE_INSTANCE_ID:-$(hostname)}"
export OTEL_RESOURCE_ATTRIBUTES="${OTEL_RESOURCE_ATTRIBUTES:-experiment=dune,service.namespace=data-mgmt-ops,service.instance.id=${_landscape_instance_id}}"
unset _landscape_instance_id

setup_gfal_token() {
    if ! command -v htgettoken >/dev/null 2>&1; then
        echo "Warning: htgettoken not found; GFAL bearer token was not refreshed." >&2
        return 0
    fi

    echo "Refreshing GFAL bearer token on host $(hostname) as user $(id -un)"
    echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-unset}"
    echo "HTGETTOKENOPTS=${HTGETTOKENOPTS}"

    local htgettoken_opts=()
    if [ -n "${HTGETTOKENOPTS:-}" ]; then
        read -r -a htgettoken_opts <<< "$HTGETTOKENOPTS"
    fi

    htgettoken "${htgettoken_opts[@]}" -i dune -r production -a htvaultprod.fnal.gov || return $?

    local token_file="/run/user/$(id -u)/bt_u$(id -u)"
    echo "Expected bearer token file: $token_file"
    if [ ! -r "$token_file" ]; then
        echo "Error: bearer token file not readable: $token_file" >&2
        return 1
    fi

    export BEARER_TOKEN="$(cat "$token_file")"
}

landscape_export_summary() {
    if [ "$#" -lt 2 ]; then
        echo "Usage: landscape_export_summary <RSE_NAME> <DATE_STAMP> [extra export args]" >&2
        echo "Example: landscape_export_summary DUNE_UK_LANCASTER_CEPH 20260819 --dry-run" >&2
        return 2
    fi

    local rse="$1"
    local date_stamp="$2"
    shift 2

    python3 src/export_landscape_otlp.py \
        --summary "check-output/${rse}/${date_stamp}/summary.json" \
        --skip-logs \
        "$@"
}

landscape_export_results_logs() {
    if [ "$#" -lt 2 ]; then
        echo "Usage: landscape_export_results_logs <RSE_NAME> <DATE_STAMP> [extra export args]" >&2
        echo "Example: landscape_export_results_logs DUNE_UK_LANCASTER_CEPH 20260819 --dry-run" >&2
        return 2
    fi

    local rse="$1"
    local date_stamp="$2"
    shift 2

    python3 src/export_landscape_otlp.py \
        --results "check-output/${rse}/${date_stamp}/results.json" \
        --skip-metrics \
        "$@"
}

echo "Landscape OTLP environment configured:"
echo "  OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT}"
echo "  OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME}"
echo "  OTEL_RESOURCE_ATTRIBUTES=${OTEL_RESOURCE_ATTRIBUTES}"
echo "  HTGETTOKENOPTS=${HTGETTOKENOPTS}"
echo
echo "Upload summary metrics:"
echo "  landscape_export_summary <RSE_NAME> <DATE_STAMP>"
echo
echo "Dry-run summary metrics:"
echo "  landscape_export_summary <RSE_NAME> <DATE_STAMP> --dry-run"

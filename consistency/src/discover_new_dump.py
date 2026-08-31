import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


CENTRAL_TZ = ZoneInfo("America/Chicago")
DEFAULT_STATE_PATH = "state/rse_dumps.json"
DATE_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")


@dataclass
class RSEConfig:
    rse: str
    remote_url: str
    local_dir: str
    mode: str


@dataclass
class DumpInfo:
    rse: str
    mode: str
    remote_url: str
    remote_path: str
    local_dir: str
    local_path: str
    basename: str
    run_date: str
    size: int | None
    created_at: str | None
    modified_at: str | None


def parse_config(path):
    configs = []
    with open(path, "r") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                raise ValueError(f"{path}:{lineno}: expected at least RSE and URL")

            rse = parts[0]
            remote_url = parts[1]
            local_dir = parts[2] if len(parts) >= 3 else os.path.join("gfal-downloads", rse)
            mode = parts[3] if len(parts) >= 4 else infer_mode(remote_url)
            if mode not in ("list", "latest"):
                raise ValueError(f"{path}:{lineno}: unsupported mode: {mode}")
            configs.append(RSEConfig(rse, remote_url, local_dir, mode))
    return configs


def infer_mode(remote_url):
    basename = remote_url.rstrip("/").split("/")[-1].lower()
    if basename in ("latest", "dump_latest"):
        return "latest"
    return "list"


def run_command(args):
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)} failed with rc={proc.returncode}: {proc.stderr.strip()}"
        )
    return proc.stdout


def join_url(base_url, name):
    if base_url.endswith("/"):
        return base_url + name
    return base_url + "/" + name


def parse_gfal_ls(stdout):
    names = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or line in (".", ".."):
            continue
        if line.startswith("total "):
            continue
        parts = line.split()
        name = parts[-1]
        if name in (".", ".."):
            continue
        names.append(name)
    return names


def parse_datetime(value):
    value = value.strip()
    if not value:
        return None

    normalized = re.sub(r"\s+", " ", value)
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%a %b %d %H:%M:%S %Y",
        "%b %d %H:%M:%S %Y",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(normalized, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CENTRAL_TZ)
            return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return None


def parse_gfal_stat(stdout):
    size = None
    created_at = None
    modified_at = None

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "size":
            match = re.search(r"\d+", value)
            if match:
                size = int(match.group(0))
        elif key in ("created", "creation", "birth", "created at", "creation time"):
            created_at = parse_datetime(value) or value
        elif key in ("modify", "modified", "mtime", "modify time", "modified at"):
            modified_at = parse_datetime(value) or value

    return size, created_at, modified_at


def date_from_timestamp(timestamp):
    if not timestamp:
        return None
    normalized = timestamp
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized).astimezone(CENTRAL_TZ).strftime("%Y%m%d")
    except ValueError:
        return None


def date_from_name(name):
    match = DATE_RE.search(name)
    if not match:
        return None
    return "".join(match.groups())


def local_name(config, remote_basename, run_date):
    if config.mode == "latest":
        return f"dump_{run_date}"
    return remote_basename


def inspect_remote(config):
    if config.mode == "latest":
        return inspect_remote_file(config, config.remote_url, config.remote_url.rstrip("/").split("/")[-1])

    listing = run_command(["gfal-ls", config.remote_url])
    names = parse_gfal_ls(listing)
    candidates = [name for name in names if "dump" in name.lower() or config.rse.lower() in name.lower()]
    if not candidates:
        candidates = names
    if not candidates:
        return None

    inspected = []
    for name in candidates:
        remote_path = join_url(config.remote_url, name)
        try:
            inspected.append(inspect_remote_file(config, remote_path, name))
        except RuntimeError:
            continue
    if not inspected:
        return None

    return max(
        inspected,
        key=lambda item: (
            item.created_at or item.modified_at or "",
            item.basename,
        ),
    )


def inspect_remote_file(config, remote_path, basename):
    stat_output = run_command(["gfal-stat", remote_path])
    size, created_at, modified_at = parse_gfal_stat(stat_output)
    run_date = (
        date_from_timestamp(created_at)
        or date_from_timestamp(modified_at)
        or date_from_name(basename)
        or datetime.now(CENTRAL_TZ).strftime("%Y%m%d")
    )
    name = local_name(config, basename, run_date)
    return DumpInfo(
        rse=config.rse,
        mode=config.mode,
        remote_url=config.remote_url,
        remote_path=remote_path,
        local_dir=config.local_dir,
        local_path=os.path.join(config.local_dir, name),
        basename=name,
        run_date=run_date,
        size=size,
        created_at=created_at,
        modified_at=modified_at,
    )


def load_state(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def state_key(info):
    return {
        "remote_path": info.remote_path,
        "size": info.size,
        "created_at": info.created_at,
        "modified_at": info.modified_at,
    }


def is_new_dump(info, state):
    previous = state.get(info.rse)
    if not previous:
        return True
    return state_key(info) != {
        "remote_path": previous.get("remote_path"),
        "size": previous.get("size"),
        "created_at": previous.get("created_at"),
        "modified_at": previous.get("modified_at"),
    }


def discover(args):
    configs = parse_config(args.config)
    if args.rse:
        selected = set(args.rse)
        configs = [config for config in configs if config.rse in selected]

    state = load_state(args.state)
    work_items = []
    for config in configs:
        info = inspect_remote(config)
        if not info:
            continue
        if args.stability_wait > 0:
            time.sleep(args.stability_wait)
            stable_info = inspect_remote_file(config, info.remote_path, info.basename)
            if state_key(info) != state_key(stable_info):
                print(
                    f"Skipping unstable dump for {config.rse}: {info.remote_path}",
                    file=sys.stderr,
                )
                continue
            info = stable_info
        if args.all or is_new_dump(info, state):
            work_items.append(asdict(info))
    return work_items


def mark_processed(args):
    state = load_state(args.state)
    with open(args.item, "r") as f:
        info = DumpInfo(**json.load(f))
    entry = state_key(info)
    entry["local_path"] = info.local_path
    entry["processed_at"] = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    state[info.rse] = entry
    os.makedirs(os.path.dirname(args.state), exist_ok=True)
    with open(args.state, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Discover new remote RSE dump files with GFAL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser("discover", help="Find new dump files")
    discover_parser.add_argument("--config", default="rse_url.txt")
    discover_parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    discover_parser.add_argument("--rse", action="append", help="Limit discovery to one RSE; repeatable")
    discover_parser.add_argument("--all", action="store_true", help="Emit work items even if state is unchanged")
    discover_parser.add_argument(
        "--stability-wait",
        type=int,
        default=0,
        help="Seconds to wait and re-stat the selected dump before emitting it",
    )

    mark_parser = subparsers.add_parser("mark-processed", help="Record one completed work item in state")
    mark_parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    mark_parser.add_argument("--item", required=True, help="Path to a work-item JSON file")

    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.command == "discover":
            print(json.dumps(discover(args), indent=2))
        elif args.command == "mark-processed":
            mark_processed(args)
    except Exception as exc:
        print(f"discover_new_dump error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

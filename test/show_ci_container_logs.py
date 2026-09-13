from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print CI media-server container logs.")
    parser.add_argument("directory", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    for compose_file in sorted(args.directory.rglob("docker-compose.yml")):
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "logs"],
            check=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

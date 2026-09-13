from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _docker(
    arguments: list[str], *, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    if not arguments or arguments[0] != "run":
        raise ValueError("Docker smoke commands must start with run")
    docker_arguments = [
        "run",
        "--env",
        f"PUID={os.getuid()}",
        "--env",
        f"PGID={os.getgid()}",
        *arguments[1:],
    ]
    return subprocess.run(
        ["docker", *docker_arguments],
        cwd=ROOT,
        check=False,
        capture_output=capture_output,
        text=True,
    )


def _check_startup_paths(image: str) -> None:
    sample_result = _docker(
        [
            "run",
            "--rm",
            "--env",
            "ENV_FILE=/app/missing.env",
            "--env",
            "YAML_FILE=/app/config/config.yaml",
            "--volume",
            f"{ROOT / 'sample.config.yaml'}:/app/config/config.yaml:ro",
            image,
            "python",
            "-m",
            "src.runtime_paths",
        ],
        capture_output=True,
    )
    if sample_result.returncode:
        raise RuntimeError(sample_result.stderr)

    with tempfile.TemporaryDirectory(prefix="jpw-protected-config-") as directory:
        protected_file = Path(directory) / "config.yaml"
        protected_file.write_text(
            (ROOT / "sample.config.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        protected_file.chmod(0o600)
        protected_result = _docker(
            [
                "run",
                "--rm",
                "--env",
                "ENV_FILE=/app/missing.env",
                "--env",
                "YAML_FILE=/app/config/config.yaml",
                "--volume",
                f"{protected_file}:/app/config/config.yaml:ro",
                image,
                "python",
                "-m",
                "src.runtime_paths",
            ],
            capture_output=True,
        )
        if protected_result.returncode:
            raise RuntimeError(
                "protected YAML startup failed; pass matching PUID/PGID:\n"
                + protected_result.stderr
            )

    with tempfile.TemporaryDirectory(prefix="jpw-docker-smoke-") as directory:
        config_dir = Path(directory)
        legacy_result = _docker(
            [
                "run",
                "--rm",
                "--env",
                "ENV_FILE=/app/.env",
                "--env",
                "YAML_FILE=/app/config/legacy-generated.yaml",
                "--volume",
                f"{config_dir}:/app/config",
                "--volume",
                f"{ROOT / 'test' / 'ci_plex.env'}:/app/.env:ro",
                image,
                "python",
                "-c",
                'from pathlib import Path; from src.settings import load_settings; load_settings(); assert Path("/app/config/legacy-generated.yaml").exists()',
            ],
            capture_output=True,
        )
        if legacy_result.returncode:
            raise RuntimeError(legacy_result.stderr)


def _check_invalid_configuration(image: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".yaml",
        prefix="jpw-invalid-",
    ) as invalid_file:
        invalid_file.write(
            "plex:\n"
            "  - name: plex-only\n"
            "    baseurl: http://localhost:32400\n"
            "    token: docker-smoke-secret\n"
        )
        invalid_file.flush()
        result = _docker(
            [
                "run",
                "--rm",
                "--env",
                "ENV_FILE=/app/missing.env",
                "--env",
                "YAML_FILE=/app/config/invalid.yaml",
                "--volume",
                f"{invalid_file.name}:/app/config/invalid.yaml:ro",
                image,
                "python",
                "-m",
                "src.runtime_paths",
            ],
            capture_output=True,
        )

    output = result.stdout + result.stderr
    print(output, end="")
    if result.returncode == 0:
        raise RuntimeError("invalid one-server configuration unexpectedly succeeded")
    if "At least two servers" not in output:
        raise RuntimeError("startup failure did not identify the minimum topology error")
    if "docker-smoke-secret" in output:
        raise RuntimeError("startup failure exposed the synthetic credential")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Docker startup smoke checks.")
    parser.add_argument("--image", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _check_startup_paths(args.image)
    _check_invalid_configuration(args.image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

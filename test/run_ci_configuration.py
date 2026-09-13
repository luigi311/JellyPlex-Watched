from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.legacy_settings import LEGACY_ENV_VARS  # noqa: E402
from src.settings import AppSettings  # noqa: E402


_CHECK_FLAGS = {
    "plex": "--plex",
    "jellyfin": "--jellyfin",
    "emby": "--emby",
    "guids": "--guids",
    "locations": "--locations",
    "write": "--write",
}


def _rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _clear_settings_environment(environment: dict[str, str]) -> None:
    recognized_names = {
        *AppSettings.model_fields,
        *LEGACY_ENV_VARS,
        "ENV_FILE",
        "YAML_FILE",
    }
    recognized_names = {name.casefold() for name in recognized_names}
    for key in list(environment):
        if key.casefold() in recognized_names or key.casefold().startswith("jpw_"):
            del environment[key]


def _child_environment(
    state_dir: Path,
    *,
    env_file: Path | None,
    yaml_file: Path,
) -> dict[str, str]:
    environment = os.environ.copy()
    _clear_settings_environment(environment)
    environment["ENV_FILE"] = (
        str(env_file) if env_file is not None else str(state_dir / "missing.env")
    )
    environment["YAML_FILE"] = str(yaml_file)
    return environment


def _prepare_state(state_dir: Path, preserve_state: bool) -> None:
    if not preserve_state and state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)


def _run_host(
    state_dir: Path,
    *,
    env_file: Path | None,
    yaml_file: Path,
    check: str,
    repeat: int,
) -> None:
    environment = _child_environment(
        state_dir,
        env_file=env_file,
        yaml_file=yaml_file,
    )
    for _ in range(repeat):
        subprocess.run(
            [sys.executable, str(ROOT / "main.py")],
            cwd=state_dir,
            env=environment,
            check=True,
        )
    subprocess.run(
        [sys.executable, str(ROOT / "test" / "validate_ci_marklog.py"), _CHECK_FLAGS[check]],
        cwd=state_dir,
        check=True,
    )


def _docker_paths(state_dir: Path) -> tuple[Path, Path]:
    config_dir = state_dir / "config"
    runtime_dir = state_dir / "runtime"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return config_dir, runtime_dir


def _container_identity() -> list[str]:
    return [
        "--env",
        f"PUID={os.getuid()}",
        "--env",
        f"PGID={os.getgid()}",
    ]


def _docker_command(
    *,
    image: str,
    config_dir: Path,
    runtime_dir: Path,
    env_file: Path | None,
    yaml_file: str,
) -> list[str]:
    container_env_file = "/app/.env" if env_file is not None else "/app/missing.env"
    arguments = [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        *_container_identity(),
        "--env",
        f"ENV_FILE={container_env_file}",
        "--env",
        f"YAML_FILE={yaml_file}",
        "--env",
        "LOG_FILE=/app/runtime/log.log",
        "--env",
        "MARK_FILE=/app/runtime/mark.log",
        "--volume",
        f"{config_dir}:/app/config",
        "--volume",
        f"{runtime_dir}:/app/runtime",
    ]
    if env_file is not None:
        arguments.extend(["--volume", f"{env_file}:/app/.env:ro"])
    arguments.extend([image, "python", "-u", "main.py"])
    return arguments


def _run_docker(
    state_dir: Path,
    *,
    image: str,
    env_file: Path | None,
    yaml_file: Path,
    check: str,
    repeat: int,
) -> None:
    config_dir, runtime_dir = _docker_paths(state_dir)
    if yaml_file.exists():
        shutil.copy2(yaml_file, config_dir / "config.yaml")

    docker_args = _docker_command(
        image=image,
        config_dir=config_dir,
        runtime_dir=runtime_dir,
        env_file=env_file,
        yaml_file="/app/config/config.yaml",
    )

    for _ in range(repeat):
        subprocess.run(docker_args, cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, str(ROOT / "test" / "validate_ci_marklog.py"), _CHECK_FLAGS[check]],
        cwd=runtime_dir,
        check=True,
    )


def _run_migration(
    state_dir: Path,
    *,
    env_file: Path,
    yaml_output: Path,
    image: str | None,
    check: str,
) -> None:
    if image is None:
        yaml_file = state_dir / yaml_output.name
        _run_host(
            state_dir,
            env_file=env_file,
            yaml_file=yaml_file,
            check=check,
            repeat=1,
        )
        (state_dir / "mark.log").unlink(missing_ok=True)
        (state_dir / "log.log").unlink(missing_ok=True)
        _run_host(
            state_dir,
            env_file=None,
            yaml_file=yaml_file,
            check=check,
            repeat=1,
        )
        return

    config_dir, runtime_dir = _docker_paths(state_dir)
    docker_args = _docker_command(
        image=image,
        config_dir=config_dir,
        runtime_dir=runtime_dir,
        env_file=env_file,
        yaml_file="/app/config/" + yaml_output.name,
    )
    subprocess.run(docker_args, cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, str(ROOT / "test" / "validate_ci_marklog.py"), _CHECK_FLAGS[check]],
        cwd=runtime_dir,
        check=True,
    )
    (runtime_dir / "mark.log").unlink(missing_ok=True)
    (runtime_dir / "log.log").unlink(missing_ok=True)

    yaml_only_args = _docker_command(
        image=image,
        config_dir=config_dir,
        runtime_dir=runtime_dir,
        env_file=None,
        yaml_file="/app/config/" + yaml_output.name,
    )
    subprocess.run(yaml_only_args, cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, str(ROOT / "test" / "validate_ci_marklog.py"), _CHECK_FLAGS[check]],
        cwd=runtime_dir,
        check=True,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one CI configuration scenario.")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--yaml-file", type=Path)
    parser.add_argument("--yaml-output", type=Path, default=Path("ci-migrated.yaml"))
    parser.add_argument("--check", choices=sorted(_CHECK_FLAGS), required=True)
    parser.add_argument("--image")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--preserve-state", action="store_true")
    parser.add_argument("--migration", action="store_true")
    args = parser.parse_args()

    if args.repeat < 1:
        parser.error("--repeat must be at least one")
    if args.migration:
        if args.env_file is None or args.yaml_file is not None:
            parser.error("migration requires --env-file and does not accept --yaml-file")
    elif args.env_file is None and args.yaml_file is None:
        parser.error("provide --env-file or --yaml-file")
    if args.preserve_state and args.state_dir is None:
        parser.error("--preserve-state requires --state-dir")
    return args


def main() -> int:
    args = _parse_args()
    env_file = _rooted(args.env_file) if args.env_file is not None else None
    yaml_file = _rooted(args.yaml_file) if args.yaml_file is not None else None
    state_dir = _rooted(args.state_dir) if args.state_dir is not None else None

    if state_dir is None:
        with tempfile.TemporaryDirectory(prefix="jpw-ci-") as temporary_dir:
            state_path = Path(temporary_dir)
            _prepare_state(state_path, preserve_state=False)
            if args.migration:
                if env_file is None:
                    raise ValueError("migration requires an environment file")
                _run_migration(
                    state_path,
                    env_file=env_file,
                    yaml_output=args.yaml_output,
                    image=args.image,
                    check=args.check,
                )
            elif args.image is None:
                _run_host(
                    state_path,
                    env_file=env_file,
                    yaml_file=yaml_file or state_path / "config.yaml",
                    check=args.check,
                    repeat=args.repeat,
                )
            else:
                _run_docker(
                    state_path,
                    image=args.image,
                    env_file=env_file,
                    yaml_file=yaml_file or state_path / "config.yaml",
                    check=args.check,
                    repeat=args.repeat,
                )
        return 0

    if state_dir == ROOT:
        raise ValueError("CI state directory cannot be the repository root")
    _prepare_state(state_dir, preserve_state=args.preserve_state)
    if args.migration:
        if env_file is None:
            raise ValueError("migration requires an environment file")
        _run_migration(
            state_dir,
            env_file=env_file,
            yaml_output=args.yaml_output,
            image=args.image,
            check=args.check,
        )
    elif args.image is None:
        _run_host(
            state_dir,
            env_file=env_file,
            yaml_file=yaml_file or state_dir / "config.yaml",
            check=args.check,
            repeat=args.repeat,
        )
    else:
        _run_docker(
            state_dir,
            image=args.image,
            env_file=env_file,
            yaml_file=yaml_file or state_dir / "config.yaml",
            check=args.check,
            repeat=args.repeat,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

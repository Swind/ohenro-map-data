"""Cache a pinned Blutter checkout and run it without installing system packages."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import venv

DOCKER_BASE = "ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517"
BLUTTER_REVISION = "4a60ac648bf448c5a7596437243bcd0b9376fdf0"
BLUTTER_REPOSITORY = "https://github.com/worawit/blutter.git"
PYTHON_REQUIREMENTS = (
    "pyelftools==0.33", "requests==2.34.2", "certifi==2026.7.22",
    "charset-normalizer==3.5.0", "idna==3.18", "urllib3==2.7.0",
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, check=True, **kwargs)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required command is missing: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Command failed ({exc.returncode}): {' '.join(command)}") from exc


def _source(tools: Path) -> Path:
    source = tools / "blutter"
    if not source.exists():
        with tempfile.TemporaryDirectory(prefix=".blutter-", dir=tools) as temporary:
            stage = Path(temporary) / "source"
            _run(["git", "init", str(stage)])
            _run(["git", "-C", str(stage), "remote", "add", "origin", BLUTTER_REPOSITORY])
            _run(["git", "-C", str(stage), "fetch", "--depth=1", "origin", BLUTTER_REVISION])
            _run(["git", "-C", str(stage), "checkout", "--detach", "FETCH_HEAD"])
            stage.rename(source)
    revision = _run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    changes = _run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip()
    if revision != BLUTTER_REVISION or changes or not (source / "blutter.py").is_file():
        raise RuntimeError(f"Blutter cache {source} is modified or not at {BLUTTER_REVISION}; move it aside and rerun")
    return source


def _host_requirements() -> tuple[dict[str, str], list[str]]:
    missing = [name for name in ("git", "cmake", "ninja", "pkg-config") if not shutil.which(name)]
    environment = os.environ.copy()
    if platform.system() != "Linux":
        missing.append("Linux host (otherwise use Docker)")
    compiler = environment.get("CXX") or shutil.which("g++")
    if not compiler:
        missing.append("g++ >= 13")
    else:
        try:
            version = _run([compiler, "--version"], capture_output=True, text=True).stdout
            match = re.search(r"(?:clang version |\) )(\d+)", version)
            minimum = 16 if "clang" in version.lower() else 13
            if not match or int(match.group(1)) < minimum:
                missing.append("g++ >= 13 or clang++ >= 16 with a C++20 standard library")
            else:
                environment["CXX"] = compiler
        except RuntimeError:
            missing.append("g++ >= 13 or clang++ >= 16")
    if shutil.which("pkg-config"):
        try:
            _run(["pkg-config", "--exists", "icu-i18n", "capstone"], capture_output=True)
        except RuntimeError:
            missing.append("libicu-dev and libcapstone-dev")
    return environment, missing


def _environment(tools: Path) -> Path:
    directory = tools / f"venv-py{sys.version_info.major}.{sys.version_info.minor}"
    python = directory / "bin" / "python"
    stamp = directory / ".requirements.json"
    expected = list(PYTHON_REQUIREMENTS)
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(directory)
    if not stamp.exists() or json.loads(stamp.read_text()) != expected:
        _run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
              "--cache-dir", str(tools / "pip-cache"), *PYTHON_REQUIREMENTS])
        stamp.write_text(json.dumps(expected) + "\n")
    return python


def _docker_image(tools: Path) -> str:
    if not shutil.which("docker"):
        raise RuntimeError("Docker is unavailable")
    _run(["docker", "info"], capture_output=True)
    requirements = " ".join(PYTHON_REQUIREMENTS)
    dockerfile = (
        f"FROM {DOCKER_BASE}\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        "ca-certificates git cmake ninja-build g++ pkg-config libicu-dev libcapstone-dev python3-venv "
        "&& rm -rf /var/lib/apt/lists/*\n"
        "RUN python3 -m venv /opt/blutter-venv\n"
        f"RUN /opt/blutter-venv/bin/python -m pip install --no-cache-dir {requirements}\n"
        "ENV PATH=/opt/blutter-venv/bin:$PATH\n"
    )
    digest = hashlib.sha256(dockerfile.encode()).hexdigest()[:16]
    image = f"ohenro-henro-helper-blutter:{digest}"
    marker = tools / f"docker-{digest}.json"
    if not marker.exists():
        with tempfile.TemporaryDirectory(prefix=".docker-", dir=tools) as temporary:
            (Path(temporary) / "Dockerfile").write_text(dockerfile)
            _run(["docker", "build", "--tag", image, temporary])
        marker.write_text(json.dumps({"image": image}) + "\n")
    else:
        # An image may have been pruned independently of the on-disk cache.
        try:
            _run(["docker", "image", "inspect", image], capture_output=True)
        except RuntimeError:
            marker.unlink()
            return _docker_image(tools)
    return image


def bootstrap(tools: Path) -> dict:
    """Prepare only the cached toolchain; Dart/Blutter compilation happens on use."""
    tools = Path(tools).resolve()
    tools.mkdir(parents=True, exist_ok=True)
    source = _source(tools)
    _, missing = _host_requirements()
    metadata = {"repository": BLUTTER_REPOSITORY, "revision": BLUTTER_REVISION,
                "python_requirements": list(PYTHON_REQUIREMENTS)}
    if not missing:
        python = _environment(tools)
        metadata.update(backend="host", python=str(python), source=str(source))
    else:
        try:
            image = _docker_image(tools)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Host Blutter prerequisites missing: {', '.join(missing)}. "
                "Install Debian/Ubuntu packages git cmake ninja-build g++ pkg-config "
                "libicu-dev libcapstone-dev python3-venv (g++ must be >=13), "
                f"or provide a working Docker daemon. Blutter source is cached at {source}. {exc}"
            ) from exc
        image_id = _run(["docker", "image", "inspect", "--format={{.Id}}", image], capture_output=True, text=True).stdout.strip()
        metadata.update(backend="docker", image=image, image_id=image_id, source=str(source))
    return metadata


def disassemble(libraries: Path, output: Path, tools: Path) -> dict:
    """Disassemble trusted cached ARM64 libraries into a new output directory."""
    libraries, output, tools = (Path(path).resolve() for path in (libraries, output, tools))
    for name in ("libapp.so", "libflutter.so"):
        library = libraries / name
        if not library.is_file() or library.stat().st_size == 0:
            raise RuntimeError(f"Missing or empty ARM64 input library: {library}")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing Blutter output: {output}")
    metadata = bootstrap(tools)
    output.mkdir(parents=True)
    source = Path(metadata["source"])
    if metadata["backend"] == "host":
        environment, _ = _host_requirements()
        _run([metadata["python"], str(source / "blutter.py"), str(libraries), str(output)], cwd=source, env=environment)
    else:
        home = tools / "docker-home"
        home.mkdir(exist_ok=True)
        _run([
            "docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", f"HOME={home}", "--volume", f"{tools}:{tools}",
            "--volume", f"{libraries}:{libraries}:ro", "--volume", f"{output}:{output}",
            "--workdir", str(source), metadata["image_id"],
            "python", str(source / "blutter.py"), str(libraries), str(output),
        ])
    pool = output / "pp.txt"
    assembly = output / "asm"
    if not pool.is_file() or pool.stat().st_size == 0 or not assembly.is_dir() or not any(assembly.rglob("*.dart")):
        raise RuntimeError(f"Blutter did not produce a nonempty pp.txt and asm/**/*.dart in {output}")
    return metadata

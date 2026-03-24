import re
import tomllib
from enum import Enum
from pathlib import Path

import typer

BASE_PATH = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_PATH / "orchestration/airflow/Dockerfile.k8s.template"
DEFAULT_PYTHON_VERSION = "3.12"

app = typer.Typer()


class NetworkMode(str, Enum):
    proxy = "proxy"
    default = "default"


def log(msg: str) -> None:
    typer.echo(msg, err=True)


def extract_version(spec: str) -> str:
    match = re.search(r"\d+\.\d+", spec)
    if not match:
        raise ValueError(f"Could not parse Python version from: {spec}")
    return match.group()


def resolve_python_version(src: Path) -> str:
    # 1. .python_version
    py_version_file = src / ".python_version"
    if py_version_file.exists():
        value = py_version_file.read_text().strip()
        log(f".python_version → {value}")
        return extract_version(value)

    # 2. pyproject.toml
    pyproject = src / "pyproject.toml"
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_bytes().decode())
        requires = data.get("project", {}).get("requires-python") or data.get(
            "tool", {}
        ).get("poetry", {}).get("dependencies", {}).get("python")
        if requires:
            version = extract_version(requires)
            log(f"pyproject.toml requires-python='{requires}' → {version}")
            return version

    # 3. uv.lock
    uv_lock = src / "uv.lock"
    if uv_lock.exists():
        data = tomllib.loads(uv_lock.read_bytes().decode())
        requires = data.get("metadata", {}).get("requires-python")
        if requires:
            version = extract_version(requires)
            log(f"uv.lock requires-python='{requires}' → {version}")
            return version

    log(f"No Python version found, falling back to {DEFAULT_PYTHON_VERSION}")
    return DEFAULT_PYTHON_VERSION


def render_dockerfile(python_version: str, network_mode: str, src_dir: str) -> str:
    template = TEMPLATE_PATH.read_text()
    return (
        template.replace("${PYTHON_VERSION}", python_version)
        .replace("${NETWORK_MODE}", network_mode)
        .replace("${SRC_DIR}", src_dir)
    )


@app.command()
def containerize_microservice(
    service_name: str = typer.Option(..., help="Name of the microservice."),
    service_path: str = typer.Option(..., help="Path to the microservice directory (relative to repo root or absolute)."),
    network_mode: NetworkMode = typer.Option(..., case_sensitive=False, help="Network mode: proxy or default."),
) -> None:
    """Render a Dockerfile for a microservice from the k8s template."""
    src = Path(service_path)
    if not src.is_absolute():
        src = BASE_PATH / src

    if not src.exists():
        typer.echo(f"Error: service path '{src}' does not exist.", err=True)
        raise typer.Exit(1)

    python_version = resolve_python_version(src)
    log(f"Resolved Python version: {python_version}")

    # SRC_DIR is always relative to repo root for the Docker build context
    try:
        src_dir = str(src.relative_to(BASE_PATH))
    except ValueError:
        src_dir = str(src)

    rendered = render_dockerfile(python_version, network_mode.value, src_dir)

    output_path = src / f"Dockerfile.{service_name}.{network_mode.value}"
    output_path.write_text(rendered)
    typer.echo(f"Rendered Dockerfile saved to {output_path}")


if __name__ == "__main__":
    app()

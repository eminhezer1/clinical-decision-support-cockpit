from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
DEFAULT_MODEL = "qwen2.5:7b-instruct"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def find_command(name: str) -> str:
    command = shutil.which(name)
    if command is None and os.name == "nt" and name == "npm":
        command = shutil.which("npm.cmd")
    if command is None:
        raise RuntimeError(f"Gerekli komut bulunamadı: {name}")
    return command


def run_checked(command: Sequence[str], cwd: Path, label: str) -> None:
    print(f"\n==> {label}", flush=True)
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{label} başarısız oldu (çıkış kodu {result.returncode}).")


def is_http_ready(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_for_http(
    url: str, process: subprocess.Popen[bytes] | None, label: str, timeout: int = 60
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_http_ready(url):
            return
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{label} beklenmedik biçimde kapandı.")
        time.sleep(1)
    raise RuntimeError(f"{label} {timeout} saniye içinde hazır olmadı: {url}")


def ensure_port_free(port: int, service: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        try:
            server.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                f"{service} portu 127.0.0.1:{port} kullanımda. "
                "Önce o portu kullanan uygulamayı kapatın."
            ) from exc


def ensure_ollama(
    ollama_command: str, model: str, processes: list[subprocess.Popen[bytes]]
) -> None:
    if not is_http_ready(OLLAMA_TAGS_URL):
        print("\n==> Ollama servisi başlatılıyor", flush=True)
        process = subprocess.Popen(
            [ollama_command, "serve"],
            cwd=ROOT,
        )
        processes.append(process)
        wait_for_http(OLLAMA_TAGS_URL, process, "Ollama")

    with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as response:
        installed_models = response.read().decode("utf-8")
    if f'"name":"{model}"' not in installed_models.replace(" ", ""):
        run_checked([ollama_command, "pull", model], ROOT, f"Ollama modeli indiriliyor: {model}")


def install_dependencies(
    python: str, npm: str, venv_python: Path, frontend_dev: bool
) -> None:
    if not venv_python.is_file():
        run_checked(
            [python, "-m", "venv", str(BACKEND / ".venv")],
            ROOT,
            "Backend sanal ortamı oluşturuluyor",
        )

    run_checked(
        [str(venv_python), "-m", "pip", "install", "-r", str(BACKEND / "requirements.txt")],
        ROOT,
        "Backend Python bağımlılıkları kuruluyor",
    )
    run_checked(
        [npm, "install"],
        FRONTEND,
        "Frontend npm bağımlılıkları kuruluyor",
    )
    if not frontend_dev:
        run_checked(
            [npm, "run", "build", "--", "--webpack"],
            FRONTEND,
            "Frontend production build hazırlanıyor",
        )


def stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bağımlılıkları kurup Ollama, backend ve frontend'i birlikte başlatır."
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Frontend'i production build yerine Next.js geliştirme sunucusuyla açar.",
    )
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        print("Python 3.10 veya üzeri gereklidir.", file=sys.stderr)
        return 2
    if not (BACKEND / "requirements.txt").is_file() or not (
        FRONTEND / "package.json"
    ).is_file():
        print("start.py backend ve frontend klasörlerinin yanında çalıştırılmalıdır.", file=sys.stderr)
        return 2

    started_processes: list[subprocess.Popen[bytes]] = []
    try:
        python = find_command("python")
        node = find_command("node")
        npm = find_command("npm")
        ollama = find_command("ollama")
        env = read_env_file(BACKEND / ".env")
        model = os.environ.get("OLLAMA_MODEL", env.get("OLLAMA_MODEL", DEFAULT_MODEL)).strip()
        if not model:
            model = DEFAULT_MODEL

        ensure_port_free(8000, "Backend")
        ensure_port_free(3000, "Frontend")

        venv_python = BACKEND / ".venv" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        install_dependencies(python, npm, venv_python, args.dev)
        ensure_ollama(ollama, model, started_processes)

        print("\n==> Backend başlatılıyor", flush=True)
        backend_process = subprocess.Popen(
            [
                str(venv_python),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=BACKEND,
        )
        started_processes.append(backend_process)
        wait_for_http("http://127.0.0.1:8000/docs", backend_process, "Backend")

        print("\n==> Frontend başlatılıyor", flush=True)
        next_command = [
            node,
            str(FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"),
            "dev" if args.dev else "start",
            "--hostname",
            "127.0.0.1",
            "--port",
            "3000",
        ]
        frontend_process = subprocess.Popen(next_command, cwd=FRONTEND)
        started_processes.append(frontend_process)
        wait_for_http("http://127.0.0.1:3000/", frontend_process, "Frontend")

        print("\nSistem hazır:", flush=True)
        print("  Kokpit:     http://127.0.0.1:3000", flush=True)
        print("  Backend API: http://127.0.0.1:8000/docs", flush=True)
        print(f"  Ollama modeli: {model}", flush=True)
        print("Durdurmak için Ctrl+C kullanın.", flush=True)

        while True:
            for name, process in (
                ("Backend", backend_process),
                ("Frontend", frontend_process),
            ):
                return_code = process.poll()
                if return_code is not None:
                    raise RuntimeError(f"{name} durdu (çıkış kodu {return_code}).")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nServisler durduruluyor...", flush=True)
        return 0
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"\nBaşlatma hatası: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_processes(started_processes)


if __name__ == "__main__":
    raise SystemExit(main())

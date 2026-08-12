from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx


def runtime_directory() -> Path:
    """Return the directory beside the executable when packaged by PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def client_config_path() -> Path:
    configured = os.getenv("IMAGE2_CLIENT_CONFIG")
    return Path(configured).expanduser() if configured else runtime_directory() / "image2-client.json"


def client_config() -> dict:
    path = client_config_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not read Image2 client configuration: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Image2 client configuration must be a JSON object")
    return value


def ensure_token_file(config: dict) -> Path:
    configured = config.get("token_path")
    token_path = Path(configured).expanduser() if configured else runtime_directory() / ".image2-token"
    if not token_path.exists():
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return token_path


def ensure_server(server: str, config: dict | None = None) -> None:
    config = config or client_config()
    headers = local_headers(config)
    try:
        response = httpx.get(f"{server}/api/health", headers=headers, timeout=2)
        response.raise_for_status()
        return
    except httpx.ConnectError:
        pass
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Image2 service is unhealthy: {exc}") from exc
    if server != "http://127.0.0.1:8765":
        raise RuntimeError(f"Image2 service is unavailable at {server}")
    root = Path(config.get("service_root") or runtime_directory())
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    launcher = config.get("launcher")
    if getattr(sys, "frozen", False):
        if not launcher:
            raise RuntimeError("Image2 service is unavailable and no packaged launcher is configured")
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(Path(launcher))],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    else:
        log_path = root / "image2-server.log"
        log_handle = log_path.open("a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8765"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            creationflags=creationflags,
        )
    for _ in range(15):
        time.sleep(1)
        try:
            response = httpx.get(f"{server}/api/health", headers=headers, timeout=2)
            response.raise_for_status()
            return
        except httpx.ConnectError:
            continue
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Image2 service is unhealthy: {exc}") from exc
    raise RuntimeError("Image2 service did not start within 15 seconds")


def local_headers(config: dict) -> dict[str, str]:
    token_path = ensure_token_file(config)
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Could not read local service token: {exc}") from exc
    if not token:
        raise RuntimeError("Local service token is empty")
    return {"X-Image2-Local-Token": token}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an image through the local Image2 provider service.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="medium")
    parser.add_argument("--image-url", help="Public reference image URL; uses /api/edit")
    parser.add_argument("--image-path", action="append", help="Local reference image path; may be supplied up to 8 times")
    parser.add_argument("--server", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validate and display the final call without sending it")
    args = parser.parse_args()
    try:
        config = client_config()
        server = args.server or str(config.get("server") or "http://127.0.0.1:8765")
        if args.dry_run:
            provider_model = "active provider model"
            try:
                health = httpx.get(f"{server}/api/health", headers=local_headers(config), timeout=2).json()
                print("[1/6] Local service: reachable")
                provider_model = health.get("model") or provider_model
                print(f"      provider={health.get('provider')} model={health.get('model')} configured={health.get('configured')} base_url={health.get('base_url')}")
            except httpx.HTTPError:
                print("[1/6] Local service: unavailable (would start it before a real call)")
            if args.image_url and args.image_path:
                raise RuntimeError("Use --image-url or --image-path, not both")
            if args.image_url:
                endpoint = "/api/edit-url"
                payload = {"prompt": args.prompt, "image_url": args.image_url, "size": args.size, "quality": args.quality}
                mode = "multipart image[] after backend URL download"
            elif args.image_path:
                if len(args.image_path) > 8:
                    raise RuntimeError("At most 8 reference images are supported")
                missing = [path for path in args.image_path if not Path(path).is_file()]
                if missing:
                    raise RuntimeError(f"Reference image not found: {missing[0]}")
                endpoint = "/api/edit"
                payload = {"prompt": args.prompt, "size": args.size, "quality": args.quality, "image[]": [Path(path).name for path in args.image_path]}
                mode = "multipart image[] upload"
            else:
                endpoint = "/api/generate"
                payload = {"model": provider_model, "prompt": args.prompt, "size": args.size, "quality": args.quality, "n": 1}
                mode = "JSON"
            print("[2/6] Prompt: accepted (the caller should optimize it before this CLI step)")
            print("[3/6] Route:", endpoint)
            print("[4/6] Body mode:", mode)
            print("[5/6] Final payload (API key omitted):")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print("[6/6] STOPPED before the final generation request; no provider quota used.")
            return 0

        ensure_server(server, config)
        if args.image_url and args.image_path:
            raise RuntimeError("Use --image-url or --image-path, not both")
        if args.image_url:
            response = httpx.post(f"{server}/api/edit-url", headers=local_headers(config), json={"prompt": args.prompt, "image_url": args.image_url, "size": args.size, "quality": args.quality}, timeout=240)
        elif args.image_path:
            if len(args.image_path) > 8:
                raise RuntimeError("At most 8 reference images are supported")
            opened = []
            try:
                files = []
                for path in args.image_path:
                    file_path = Path(path).resolve()
                    handle = file_path.open("rb")
                    opened.append(handle)
                    files.append(("image[]", (file_path.name, handle, mimetypes.guess_type(file_path.name)[0] or "image/png")))
                response = httpx.post(f"{server}/api/edit", headers=local_headers(config), data={"prompt": args.prompt, "size": args.size, "quality": args.quality}, files=files, timeout=240)
            finally:
                for handle in opened:
                    handle.close()
        else:
            response = httpx.post(f"{server}/api/generate", headers=local_headers(config), json={"prompt": args.prompt, "size": args.size, "quality": args.quality}, timeout=240)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except ValueError:
            detail = exc.response.text
        print(f"Image2 request failed ({exc.response.status_code}): {detail}", file=sys.stderr)
        return 1
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"Image2 request failed: {exc}", file=sys.stderr)
        return 1
    payload = response.json()
    urls = payload.get("urls", [payload.get("url")])
    output_root = Path(config.get("output_dir") or runtime_directory() / "outputs").expanduser()
    paths = [str(output_root / url.rstrip("/").rsplit("/", 1)[-1]) for url in urls if url]
    print(json.dumps({"urls": urls, "paths": paths, "server": server}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

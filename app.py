from __future__ import annotations

import base64
import binascii
import asyncio
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import keyring
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

SOURCE_ROOT = Path(__file__).parent
if getattr(sys, "frozen", False):
    executable_root = Path(sys.executable).resolve().parent
    ROOT = executable_root.parent.parent if executable_root.parent.name.lower() == "dist" else executable_root
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", executable_root))
else:
    ROOT = SOURCE_ROOT
    RESOURCE_ROOT = SOURCE_ROOT
OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(exist_ok=True)
DB = ROOT / "image2.sqlite3"
KEYRING_SERVICE = f"local-image2-{hashlib.sha256(str(ROOT).encode('utf-8')).hexdigest()[:16]}"
LEGACY_KEYRING_SERVICE = "local-image2"
PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ALLOWED_AUTH_TYPES = {"bearer", "x-api-key", "none"}
TIMEOUT = float(os.getenv("IMAGE2_TIMEOUT", "120"))
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_UPLOAD_BYTES = 80 * 1024 * 1024
MAX_GENERATED_BYTES = 50 * 1024 * 1024
try:
    MAX_STORED_IMAGES = max(1, min(int(os.getenv("IMAGE2_MAX_STORED_IMAGES", "200")), 1000))
except ValueError:
    MAX_STORED_IMAGES = 200
TOKEN_PATH = ROOT / ".image2-token"
ALLOWED_QUALITIES = {"low", "medium", "high"}
MIN_IMAGE_DIMENSION = 256
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 16_777_216
MAX_PROMPT_LENGTH = 10000
CODEX_SKILL_ID = "image2"
DB_LOCK = threading.RLock()
PROVIDER_REQUEST_LOCK = asyncio.Lock()

app = FastAPI(title="Local Image2", version="0.1.1")


@contextmanager
def database():
    with DB_LOCK:
        conn = sqlite3.connect(DB, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def local_token() -> str:
    try:
        try:
            token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            token = ""
        if token:
            return token
        token = secrets.token_urlsafe(32)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(token, encoding="utf-8")
        return token
    except OSError as exc:
        raise RuntimeError(f"Could not initialize local service token: {exc}") from exc


def require_local_token(request: Request) -> None:
    if request.headers.get("X-Image2-Local-Token") != local_token():
        raise HTTPException(401, "Missing or invalid local service token")


def codex_home() -> Path:
    return Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def codex_project_root() -> Path:
    return ROOT


def codex_skill_source() -> Path:
    packaged = RESOURCE_ROOT / "skills" / CODEX_SKILL_ID
    return packaged if packaged.exists() else SOURCE_ROOT / "skills" / CODEX_SKILL_ID


def codex_project_skill_path() -> Path:
    return codex_project_root() / "skills" / CODEX_SKILL_ID


def codex_project_cli_path() -> Path | None:
    for candidate in (codex_project_root() / "image2_cli.py", codex_project_root() / "Image2CLI.exe"):
        if candidate.exists():
            return candidate
    return None


def codex_cli_artifact() -> Path | None:
    candidates = (
        ROOT / "Image2CLI.exe",
        RESOURCE_ROOT / "Image2CLI.exe",
        RESOURCE_ROOT / "image2_cli.py",
        SOURCE_ROOT / "image2_cli.py",
    )
    return next((candidate for candidate in candidates if candidate.exists()), None)


def codex_launcher_path() -> Path | None:
    candidates = (
        ROOT / "start_image2.ps1",
        ROOT.parent / "start_image2.ps1",
        SOURCE_ROOT / "start_image2.ps1",
    )
    return next((candidate for candidate in candidates if candidate.exists()), None)


def codex_prompt() -> str:
    return f"""请把当前 Image2 Studio 接入当前 Codex 工作流。\n\n项目目录：{ROOT}\n本地服务：http://127.0.0.1:8765\n全局 Skill 目标目录：%CODEX_HOME%\\skills\\{CODEX_SKILL_ID}\n\n请按以下步骤执行：\n1. 检查本地 Image2 服务是否运行；如果没有运行，从项目目录启动它。\n2. 检查项目级 Image2 Skill 和 CLI 是否可用；如果当前 Codex 支持安装本地 Skill，请安装或更新项目内的 skills/{CODEX_SKILL_ID}。\n3. 后续用户提出生成或编辑图片时，必须调用本地 image2_cli.py 和当前已配置的图片 API，不要调用内置 imagegen。\n4. 生成前优化提示词；有参考图时自动使用 --image-url 或 --image-path。\n5. 在不生成图片、不消耗额度的前提下，完成检查后告诉我当前 Skill 接入范围和下一步操作。\n\n不要读取、输出、复制或要求我在对话中粘贴任何 API Key。"""


def codex_prompt_v2() -> str:
    global_target = rf"%CODEX_HOME%\skills\{CODEX_SKILL_ID}"
    cli_command = f'"{global_target}\\Image2CLI.exe"' if getattr(sys, "frozen", False) else f'python "{ROOT / "image2_cli.py"}"'
    return f"Use Image2 Studio for image requests in this Codex workflow. Service: http://127.0.0.1:8765. Global Skill: {global_target}. Preferred CLI: {cli_command}. Check the local service and active provider first. For image generation or editing, use the Image2 CLI instead of built-in imagegen; optimize prompts and use --image-url or --image-path for references. Do not read, print, copy, or request any API key."


def codex_status_payload() -> dict[str, Any]:
    source = codex_skill_source()
    project_skill = codex_project_skill_path()
    project_cli = codex_project_cli_path()
    global_skill = codex_home() / "skills" / CODEX_SKILL_ID
    project_connected = (project_skill / "SKILL.md").exists() and project_cli is not None
    global_connected = (global_skill / "SKILL.md").exists()
    global_client_ready = (
        global_connected
        and ((global_skill / "Image2CLI.exe").exists() or (global_skill / "image2_cli.py").exists())
        and (global_skill / "image2-client.json").exists()
    )
    return {
        "connected": project_connected or global_connected,
        "project_connected": project_connected,
        "global_connected": global_connected,
        "project_skill": str(project_skill) if (project_skill / "SKILL.md").exists() else None,
        "project_cli": str(project_cli) if project_cli else None,
        "global_skill": str(global_skill) if global_connected else None,
        "global_client_ready": global_client_ready,
        "global_skill_target": str(global_skill),
        "install_available": (source / "SKILL.md").exists() and codex_cli_artifact() is not None,
        "skill_id": CODEX_SKILL_ID,
        "service_url": "http://127.0.0.1:8765",
        "prompt": codex_prompt_v2(),
        "note": "本地页面只能检查接入文件，无法确认已经打开的 Codex 对话是否已重新加载 Skill；安装或更新后请新开窗口或重新开始任务。",
    }


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    size: str = "1024x1024"
    quality: str = "medium"
    n: int = Field(default=1, ge=1, le=4)


class EditUrlRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    image_url: HttpUrl
    size: str = "1024x1024"
    quality: str = "medium"


class ProviderRequest(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    generation_path: str = Field(default="/images/generations", max_length=200)
    edit_path: str = Field(default="/images/edits", max_length=200)
    auth_type: str = "bearer"
    image_field: str = Field(default="image[]", min_length=1, max_length=100)
    api_key: str | None = Field(default=None, max_length=2000)


def init_db() -> None:
    with database() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("CREATE TABLE IF NOT EXISTS generations (id INTEGER PRIMARY KEY, prompt TEXT, path TEXT, created_at REAL)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS provider_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                generation_path TEXT NOT NULL,
                edit_path TEXT NOT NULL,
                auth_type TEXT NOT NULL,
                image_field TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        conn.execute("CREATE TABLE IF NOT EXISTS image2_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def keyring_password(provider_id: str) -> str | None:
    try:
        value = keyring.get_password(KEYRING_SERVICE, provider_id)
        if value is None and KEYRING_SERVICE != LEGACY_KEYRING_SERVICE:
            value = keyring.get_password(LEGACY_KEYRING_SERVICE, provider_id)
        return value
    except Exception:
        return None


def save_keyring_password(provider_id: str, value: str) -> None:
    try:
        keyring.set_password(KEYRING_SERVICE, provider_id, value)
    except Exception as exc:
        raise HTTPException(500, "Secure API key storage is unavailable") from exc


def delete_keyring_password(provider_id: str) -> None:
    for service in (KEYRING_SERVICE, LEGACY_KEYRING_SERVICE):
        try:
            keyring.delete_password(service, provider_id)
        except Exception:
            continue


def row_to_provider(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    keys = ("id", "name", "base_url", "model", "generation_path", "edit_path", "auth_type", "image_field", "created_at", "updated_at")
    return dict(zip(keys, row))


def provider_api_key(provider: dict[str, Any]) -> str | None:
    return keyring_password(provider["id"])


def validate_provider_values(values: dict[str, Any]) -> dict[str, Any]:
    if not PROVIDER_ID_PATTERN.fullmatch(values["id"]):
        raise HTTPException(400, "Provider id must use lowercase letters, digits, hyphens, or underscores")
    parsed = urlparse(values["base_url"])
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(400, "Provider base_url must be a plain http(s) URL without credentials or query parameters")
    for field in ("generation_path", "edit_path"):
        path = values[field]
        if not path.startswith("/") or "://" in path or len(path) > 200:
            raise HTTPException(400, f"{field} must be a relative API path")
        values[field] = path
    if values["auth_type"] not in ALLOWED_AUTH_TYPES:
        raise HTTPException(400, "Unsupported provider authentication type")
    values["base_url"] = values["base_url"].rstrip("/")
    return values


def provider_public(provider: dict[str, Any], active_id: str | None) -> dict[str, Any]:
    return {
        "id": provider["id"],
        "name": provider["name"],
        "base_url": provider["base_url"],
        "model": provider["model"],
        "generation_path": provider["generation_path"],
        "edit_path": provider["edit_path"],
        "auth_type": provider["auth_type"],
        "image_field": provider["image_field"],
        "configured": bool(provider_api_key(provider)) or provider["auth_type"] == "none",
        "active": provider["id"] == active_id,
    }


def active_provider() -> dict[str, Any] | None:
    init_db()
    with database() as conn:
        conn.row_factory = sqlite3.Row
        setting = conn.execute("SELECT value FROM image2_settings WHERE key = 'active_provider'").fetchone()
        active_id = setting[0] if setting else None
        row = conn.execute("SELECT * FROM provider_profiles WHERE id = ?", (active_id,)).fetchone()
    return row_to_provider(row) if row is not None else None


def require_active_provider() -> dict[str, Any]:
    provider = active_provider()
    if provider is None:
        raise HTTPException(409, "No image provider is configured. Open API settings to complete first-time setup.")
    if provider["auth_type"] != "none" and not provider_api_key(provider):
        raise HTTPException(409, f"No API key is configured for '{provider['name']}'. Open API settings to finish setup.")
    return provider


def provider_by_id(provider_id: str) -> dict[str, Any]:
    init_db()
    with database() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM provider_profiles WHERE id = ?", (provider_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Image provider not found")
    return row_to_provider(row)


def provider_headers(provider: dict[str, Any], key: str | None) -> dict[str, str]:
    if provider["auth_type"] == "none":
        return {}
    if not key:
        raise HTTPException(500, f"No API key configured for provider '{provider['id']}'")
    if provider["auth_type"] == "bearer":
        return {"Authorization": f"Bearer {key}"}
    return {"x-api-key": key}


def image_suffix(mime_type: str | None) -> str:
    return {"image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get((mime_type or "").split(";", 1)[0].lower(), ".png")


async def validate_public_host(host: str) -> None:
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, None)
        for address in addresses:
            if not ipaddress.ip_address(address[4][0]).is_global:
                raise HTTPException(400, "Private or local image URLs are not allowed")
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        raise HTTPException(400, "Could not resolve image URL") from exc


async def fetch_image_bytes(url: str, *, allow_private: bool, private_host: str | None = None, max_bytes: int) -> tuple[str, bytes, str]:
    current_url = url
    timeout = httpx.Timeout(connect=15, read=30, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(6):
            parsed = urlparse(current_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise HTTPException(400, "Image URL must be a plain http(s) URL")
            if not allow_private or not private_host or parsed.hostname.lower() != private_host.lower():
                await validate_public_host(parsed.hostname)
            async with client.stream("GET", current_url) as response:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(400, "Image URL redirect did not include a location")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type and not content_type.startswith("image/"):
                    raise HTTPException(400, "Image URL did not return an image")
                try:
                    content_length = int(response.headers.get("content-length", "0"))
                except ValueError as exc:
                    raise HTTPException(400, "Image URL returned an invalid content length") from exc
                if content_length > max_bytes:
                    raise HTTPException(413, "Image exceeds the local size limit")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(413, "Image exceeds the local size limit")
                    chunks.append(chunk)
                return current_url, b"".join(chunks), content_type
    raise HTTPException(400, "Image URL redirected too many times")


async def save_result(prompt: str, payload: dict[str, Any], provider: dict[str, Any]) -> str:
    data = payload.get("data") or []
    if not data:
        raise HTTPException(502, "Image provider returned no image data")
    item = data[0]
    if item.get("b64_json"):
        try:
            raw = base64.b64decode(item["b64_json"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(502, "Image provider returned invalid base64 image data") from exc
        if len(raw) > MAX_GENERATED_BYTES:
            raise HTTPException(502, "Generated image exceeds the local size limit")
        suffix = image_suffix(item.get("mime_type"))
    elif item.get("url"):
        try:
            provider_host = urlparse(provider["base_url"]).hostname
            _, raw, content_type = await fetch_image_bytes(
                str(item["url"]),
                allow_private=True,
                private_host=provider_host,
                max_bytes=MAX_GENERATED_BYTES,
            )
            if len(raw) > MAX_GENERATED_BYTES:
                raise HTTPException(502, "Generated image exceeds the local size limit")
            suffix = image_suffix(content_type)
        except HTTPException as exc:
            raise HTTPException(502, f"Could not download generated image: {exc.detail}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Could not download generated image: {type(exc).__name__}") from exc
    else:
        raise HTTPException(502, "Image provider response had neither url nor b64_json")
    name = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}{suffix}"
    target = OUTPUTS / name
    target.write_bytes(raw)
    with database() as conn:
        conn.execute("INSERT INTO generations(prompt, path, created_at) VALUES (?, ?, ?)", ("", name, time.time()))
        old_rows = conn.execute("SELECT id, path FROM generations ORDER BY id DESC LIMIT -1 OFFSET ?", (MAX_STORED_IMAGES,)).fetchall()
        if old_rows:
            conn.executemany("DELETE FROM generations WHERE id = ?", [(row[0],) for row in old_rows])
    for _, old_path in old_rows:
        old_file = OUTPUTS / old_path
        if old_file.exists():
            old_file.unlink()
    return f"/outputs/{name}"


async def save_results(prompt: str, payload: dict[str, Any], provider: dict[str, Any]) -> list[str]:
    results = []
    for item in payload.get("data") or []:
        results.append(await save_result(prompt, {"data": [item]}, provider))
    if not results:
        raise HTTPException(502, "Image provider returned no image data")
    return results


async def image_provider_request(path: str, **kwargs: Any) -> dict[str, Any]:
    provider = require_active_provider()
    key = provider_api_key(provider)
    headers = provider_headers(provider, key)
    headers["Idempotency-Key"] = secrets.token_urlsafe(24)
    last: Exception | None = None
    timeout = httpx.Timeout(connect=15, read=TIMEOUT, write=30, pool=30)
    async with PROVIDER_REQUEST_LOCK:
        async with httpx.AsyncClient(base_url=provider["base_url"], timeout=timeout) as client:
            for attempt in range(3):
                response = None
                try:
                    response = await client.post(path, headers=headers, **kwargs)
                    if response.is_success:
                        try:
                            return response.json()
                        except ValueError as exc:
                            raise HTTPException(502, "Image provider returned a non-JSON success response") from exc
                    if response.status_code < 500 and response.status_code != 429:
                        detail = response.text[:2000]
                        raise HTTPException(response.status_code, f"Image provider error: {detail}")
                    last = RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
                except (httpx.HTTPError, RuntimeError) as exc:
                    last = exc
                    if attempt < 2:
                        retry_after = response.headers.get("retry-after") if response is not None else None
                        try:
                            delay = min(float(retry_after), 15) if retry_after else 2 ** attempt
                        except ValueError:
                            delay = 2 ** attempt
                        await asyncio.sleep(delay)
    raise HTTPException(502, f"Image provider request failed after retries: {last}")


def validate_image_options(size: str, quality: str) -> None:
    match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", size)
    if not match:
        raise HTTPException(400, "Size must use WIDTHxHEIGHT, for example 1920x1080")
    width, height = (int(value) for value in match.groups())
    if not MIN_IMAGE_DIMENSION <= width <= MAX_IMAGE_DIMENSION or not MIN_IMAGE_DIMENSION <= height <= MAX_IMAGE_DIMENSION:
        raise HTTPException(400, f"Each image dimension must be between {MIN_IMAGE_DIMENSION} and {MAX_IMAGE_DIMENSION}")
    if width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(400, "Requested image is larger than the local safety limit")
    if quality not in ALLOWED_QUALITIES:
        raise HTTPException(400, f"Unsupported quality: {quality}")


def validate_prompt(prompt: str) -> str:
    value = prompt.strip()
    if not value:
        raise HTTPException(400, "Prompt must not be empty")
    if len(value) > MAX_PROMPT_LENGTH:
        raise HTTPException(413, f"Prompt must be {MAX_PROMPT_LENGTH} characters or shorter")
    return value


async def read_upload(image: UploadFile) -> bytes:
    if image.content_type and not image.content_type.lower().startswith("image/"):
        raise HTTPException(400, f"Unsupported reference file type: {image.content_type}")
    content = await image.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Each reference image must be 20 MB or smaller")
    return content


async def download_reference(url: str) -> tuple[str, bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(400, "image_url must be a public http(s) image URL")
    try:
        final_url, content, content_type = await fetch_image_bytes(url, allow_private=False, max_bytes=MAX_IMAGE_BYTES)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(400, f"Could not download reference image: {type(exc).__name__}") from exc
    filename = Path(urlparse(final_url).path).name or "reference.png"
    return filename, content, content_type or "image/png"


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/providers", dependencies=[Depends(require_local_token)])
def providers() -> dict[str, Any]:
    init_db()
    with database() as conn:
        conn.row_factory = sqlite3.Row
        setting = conn.execute("SELECT value FROM image2_settings WHERE key = 'active_provider'").fetchone()
        active_id = setting[0] if setting else None
        rows = conn.execute("SELECT * FROM provider_profiles ORDER BY name COLLATE NOCASE").fetchall()
    return {"active": active_id, "providers": [provider_public(row_to_provider(row), active_id) for row in rows]}


@app.post("/api/providers", dependencies=[Depends(require_local_token)])
def save_provider(request: ProviderRequest) -> dict[str, Any]:
    values = validate_provider_values(request.model_dump(exclude={"api_key"}))
    init_db()
    now = time.time()
    with database() as conn:
        conn.execute(
            """INSERT INTO provider_profiles
               (id, name, base_url, model, generation_path, edit_path, auth_type, image_field, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, base_url=excluded.base_url, model=excluded.model,
                 generation_path=excluded.generation_path, edit_path=excluded.edit_path, auth_type=excluded.auth_type,
                 image_field=excluded.image_field, updated_at=excluded.updated_at""",
            (values["id"], values["name"], values["base_url"], values["model"], values["generation_path"], values["edit_path"], values["auth_type"], values["image_field"], now, now),
        )
        active = conn.execute("SELECT value FROM image2_settings WHERE key = 'active_provider'").fetchone()
        active_exists = active and conn.execute("SELECT 1 FROM provider_profiles WHERE id = ?", (active[0],)).fetchone()
        if not active_exists:
            conn.execute(
                "INSERT INTO image2_settings(key, value) VALUES ('active_provider', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (values["id"],),
            )
    if request.auth_type == "none":
        delete_keyring_password(values["id"])
    elif request.api_key:
        save_keyring_password(values["id"], request.api_key)
    active = active_provider()
    return provider_public(provider_by_id(values["id"]), active["id"] if active else None)


@app.post("/api/providers/{provider_id}/activate", dependencies=[Depends(require_local_token)])
def activate_provider(provider_id: str) -> dict[str, Any]:
    provider_by_id(provider_id)
    init_db()
    with database() as conn:
        conn.execute("INSERT INTO image2_settings(key, value) VALUES ('active_provider', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (provider_id,))
    return {"active": provider_id}


@app.delete("/api/providers/{provider_id}", dependencies=[Depends(require_local_token)])
def delete_provider(provider_id: str) -> dict[str, Any]:
    provider_by_id(provider_id)
    init_db()
    with database() as conn:
        setting = conn.execute("SELECT value FROM image2_settings WHERE key = 'active_provider'").fetchone()
        active_id = setting[0] if setting else None
        conn.execute("DELETE FROM provider_profiles WHERE id = ?", (provider_id,))
        if active_id == provider_id:
            replacement = conn.execute("SELECT id FROM provider_profiles ORDER BY updated_at DESC, name COLLATE NOCASE LIMIT 1").fetchone()
            if replacement:
                conn.execute("UPDATE image2_settings SET value = ? WHERE key = 'active_provider'", (replacement[0],))
            else:
                conn.execute("DELETE FROM image2_settings WHERE key = 'active_provider'")
    delete_keyring_password(provider_id)
    replacement = active_provider()
    return {"active": replacement["id"] if replacement else None}


@app.delete("/api/providers/{provider_id}/key", dependencies=[Depends(require_local_token)])
def clear_provider_key(provider_id: str) -> dict[str, Any]:
    provider = provider_by_id(provider_id)
    delete_keyring_password(provider_id)
    active = active_provider()
    return provider_public(provider, active["id"] if active else None)


@app.post("/api/providers/{provider_id}/probe", dependencies=[Depends(require_local_token)])
async def probe_provider(provider_id: str) -> dict[str, Any]:
    provider = provider_by_id(provider_id)
    if provider["auth_type"] != "none" and not provider_api_key(provider):
        return {"ok": False, "message": "请先保存 API Key，再测试提供商连接"}
    headers = provider_headers(provider, provider_api_key(provider))
    try:
        async with httpx.AsyncClient(base_url=provider["base_url"], timeout=20) as client:
            response = await client.get("/models", headers=headers)
    except httpx.HTTPError:
        return {"ok": False, "message": "Could not connect to provider"}
    if 200 <= response.status_code < 300:
        return {"ok": True, "status_code": response.status_code, "message": "Provider responded successfully"}
    if response.status_code in {401, 403}:
        return {"ok": False, "status_code": response.status_code, "message": "Provider rejected authentication"}
    if response.status_code == 404:
        return {"ok": False, "status_code": response.status_code, "message": "Provider is reachable but does not expose /models"}
    return {"ok": False, "status_code": response.status_code, "message": f"Provider returned HTTP {response.status_code}"}


@app.get("/api/health", dependencies=[Depends(require_local_token)])
def health() -> dict[str, Any]:
    provider = active_provider()
    if provider is None:
        return {
            "ok": True,
            "provider": None,
            "provider_name": "尚未配置",
            "model": None,
            "configured": False,
            "first_use": True,
            "base_url": None,
        }
    configured = bool(provider_api_key(provider)) or provider["auth_type"] == "none"
    return {
        "ok": True,
        "provider": provider["id"],
        "provider_name": provider["name"],
        "model": provider["model"],
        "configured": configured,
        "first_use": not configured,
        "base_url": provider["base_url"],
    }


@app.get("/api/codex-status", dependencies=[Depends(require_local_token)])
def codex_status() -> dict[str, Any]:
    return codex_status_payload()


@app.post("/api/codex/install", dependencies=[Depends(require_local_token)])
def install_codex_skill() -> dict[str, Any]:
    source = codex_skill_source()
    artifact = codex_cli_artifact()
    if not (source / "SKILL.md").exists():
        raise HTTPException(500, "Bundled Codex Skill is missing from this installation")
    if artifact is None:
        raise HTTPException(500, "Image2 CLI is missing from this installation")
    target = codex_home() / "skills" / CODEX_SKILL_ID
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True)
        cli_target = target / ("Image2CLI.exe" if artifact.suffix.lower() == ".exe" else "image2_cli.py")
        shutil.copy2(artifact, cli_target)
        launcher = codex_launcher_path()
        client_config = {
            "server": "http://127.0.0.1:8765",
            "service_root": str(ROOT),
            "token_path": str(TOKEN_PATH),
            "output_dir": str(OUTPUTS),
            "launcher": str(launcher) if launcher else None,
        }
        (target / "image2-client.json").write_text(json.dumps(client_config, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise HTTPException(500, f"Could not install the Codex Skill: {exc}") from exc
    result = codex_status_payload()
    result["message"] = "Codex Skill 已安装或更新；请新开 Codex 窗口或重新开始任务以加载它。"
    return result


@app.post("/api/generate", dependencies=[Depends(require_local_token)])
async def generate(request: GenerateRequest) -> dict[str, Any]:
    prompt = validate_prompt(request.prompt)
    validate_image_options(request.size, request.quality)
    provider = require_active_provider()
    body = {
        "model": provider["model"],
        "prompt": prompt,
        "size": request.size,
        "quality": request.quality,
        "n": request.n,
    }
    payload = await image_provider_request(provider["generation_path"], json=body)
    urls = await save_results(prompt, payload, provider)
    return {"url": urls[0], "urls": urls}


@app.post("/api/edit", dependencies=[Depends(require_local_token)])
async def edit(prompt: str = Form(...), images: list[UploadFile] = File(..., alias="image[]"), size: str = Form("1024x1024"), quality: str = Form("medium")) -> dict[str, Any]:
    prompt = validate_prompt(prompt)
    if not 1 <= len(images) <= 8:
        raise HTTPException(400, "The active provider supports 1 to 8 reference images")
    validate_image_options(size, quality)
    files = []
    total = 0
    for image in images:
        content = await read_upload(image)
        total += len(content)
        if total > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, "Total reference image size must be 80 MB or smaller")
        files.append(("image[]", (image.filename or "reference.png", content, image.content_type or "image/png")))
    provider = require_active_provider()
    files = [(provider["image_field"], item[1]) for item in files]
    data = {"model": provider["model"], "prompt": prompt, "size": size, "quality": quality}
    payload = await image_provider_request(provider["edit_path"], data=data, files=files)
    urls = await save_results(prompt, payload, provider)
    return {"url": urls[0], "urls": urls}


@app.post("/api/edit-url", dependencies=[Depends(require_local_token)])
async def edit_url(request: EditUrlRequest) -> dict[str, Any]:
    prompt = validate_prompt(request.prompt)
    filename, content, content_type = await download_reference(str(request.image_url))
    validate_image_options(request.size, request.quality)
    provider = require_active_provider()
    files = [(provider["image_field"], (filename, content, content_type))]
    data = {"model": provider["model"], "prompt": prompt, "size": request.size, "quality": request.quality}
    payload = await image_provider_request(provider["edit_path"], data=data, files=files)
    urls = await save_results(prompt, payload, provider)
    return {"url": urls[0], "urls": urls}


@app.get("/api/history", dependencies=[Depends(require_local_token)])
def history() -> list[dict[str, Any]]:
    files = []
    for path in OUTPUTS.iterdir():
        if not path.is_file() or path.name == ".gitkeep" or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            continue
        stat = path.stat()
        files.append({"filename": path.name, "url": f"/outputs/{path.name}", "created_at": stat.st_mtime, "bytes": stat.st_size})
    return sorted(files, key=lambda item: item["created_at"], reverse=True)[:MAX_STORED_IMAGES]


app.mount("/outputs", StaticFiles(directory=OUTPUTS), name="outputs")
app.mount("/static", StaticFiles(directory=RESOURCE_ROOT / "static"), name="static")


@app.get("/")
def index() -> HTMLResponse:
    html = (RESOURCE_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    token_meta = f'<meta name="image2-local-token" content="{local_token()}">'
    return HTMLResponse(html.replace("</head>", f"{token_meta}</head>"))

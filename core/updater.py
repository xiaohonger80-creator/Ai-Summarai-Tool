import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

APP_VERSION = "1.7.5"
CONFIG_FILENAME = "updater_config.json"

# Official GitHub Update Server (migrated from Google Drive -> GitHub)
GITHUB_OWNER = "xiaohonger80-creator"
GITHUB_REPO = "Ai-Summarai-Tool"
GITHUB_BRANCH = "main"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_GIT_URL = f"{GITHUB_REPO_URL}.git"
GITHUB_MANIFEST_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/version.json"
)
GITHUB_UPDATE_ZIP_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/release_output/AiSummarai_Update.zip"
)


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _ver_tuple(v_str: str) -> Tuple[int, ...]:
    nums = [int(n) for n in re.findall(r"\d+", (v_str or "0.0.0").strip())]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def get_effective_app_version() -> str:
    """
    Returns the highest valid active version across APP_VERSION, local version.json,
    and updater_config.json so hot-updated builds ALWAYS display the exact latest version.
    """
    best = APP_VERSION
    base = _get_base_dir()
    for fname, key in (("version.json", "version"), (CONFIG_FILENAME, "app_version")):
        for root_cand in (base, base / "_internal"):
            fp = root_cand / fname
            if fp.exists():
                try:
                    dat = json.loads(fp.read_text(encoding="utf-8"))
                    v = str(dat.get(key) or dat.get("app_version") or "").strip().lstrip("vV")
                    if v and _ver_tuple(v) > _ver_tuple(best):
                        best = v
                except Exception:
                    pass
    return best


APP_VERSION = get_effective_app_version()


def _is_legacy_gdrive_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return "drive.google.com" in u or "drive.usercontent.google.com" in u


def get_updater_config() -> Dict:
    base = _get_base_dir()
    cfg_path = base / CONFIG_FILENAME
    default_cfg = {
        "app_version": APP_VERSION,
        "update_provider": "github",
        "github_repo_url": GITHUB_REPO_URL,
        "github_branch": GITHUB_BRANCH,
        "manifest_url": GITHUB_MANIFEST_URL,
        "update_zip_url": GITHUB_UPDATE_ZIP_URL,
        "github_token": "",
        "auto_check_updates": True,
        "last_check_timestamp": 0,
    }
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                default_cfg.update(data)
        except Exception:
            pass

    # Auto-migrate any legacy Google Drive URLs to the official GitHub Update Server
    if not default_cfg.get("github_repo_url") or _is_legacy_gdrive_url(default_cfg.get("github_repo_url", "")):
        default_cfg["github_repo_url"] = GITHUB_REPO_URL
    if not default_cfg.get("github_branch"):
        default_cfg["github_branch"] = GITHUB_BRANCH
    if not default_cfg.get("manifest_url") or _is_legacy_gdrive_url(default_cfg.get("manifest_url", "")):
        default_cfg["manifest_url"] = GITHUB_MANIFEST_URL
    if not default_cfg.get("update_zip_url") or _is_legacy_gdrive_url(default_cfg.get("update_zip_url", "")):
        default_cfg["update_zip_url"] = GITHUB_UPDATE_ZIP_URL
    default_cfg["update_provider"] = "github"
    return default_cfg


def save_updater_config(data: Dict) -> bool:
    base = _get_base_dir()
    cfg_path = base / CONFIG_FILENAME
    try:
        current = get_updater_config()
        current.update(data)
        # Drop stale Google Drive keys on save
        for legacy_k in (
            "gdrive_update_url",
            "gdrive_file_id",
            "gdrive_folder_id",
            "gdrive_secondary_folder_url",
            "gdrive_secondary_folder_id",
        ):
            current.pop(legacy_k, None)
        cfg_path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


class InAppPackageUpdater:
    USER_AGENT = "AiSummarai-Updater/2.0 (+https://github.com/xiaohonger80-creator/Ai-Summarai-Tool)"

    @staticmethod
    def _parse_ver(v_str: str) -> Tuple[int, ...]:
        parts = []
        for x in (v_str or "0.0.0").strip().lstrip("vV").split("."):
            num = ""
            for char in x:
                if char.isdigit():
                    num += char
                else:
                    break
            parts.append(int(num) if num else 0)
        return tuple(parts) if parts else (0, 0, 0)

    @staticmethod
    def bump_version(v_str: str) -> str:
        """
        Auto decimal rollover versioning (0..9 carry-over):
        e.g. 1.6.0 -> 1.6.1 -> ... -> 1.6.9 -> 1.7.0 -> ... -> 1.9.9 -> 2.0.0
        """
        nums = [int(n) for n in re.findall(r"\d+", (v_str or "1.0.0").strip())]
        while len(nums) < 3:
            nums.append(0)
        major, minor, patch = nums[0], nums[1], nums[2]
        patch += 1
        if patch >= 10:
            patch = 0
            minor += 1
        if minor >= 10:
            minor = 0
            major += 1
        return f"{major}.{minor}.{patch}"

    @classmethod
    def _build_headers(cls, github_token: str = "", accept: str = "") -> Dict[str, str]:
        headers = {
            "User-Agent": cls.USER_AGENT,
            "Cache-Control": "no-cache",
        }
        if accept:
            headers["Accept"] = accept
        tok = (github_token or os.environ.get("AISUMMARAI_GITHUB_TOKEN", "")).strip()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        return headers

    @staticmethod
    def parse_github_repo(url: str) -> Optional[Tuple[str, str, str]]:
        """
        Extracts (owner, repo, branch) from any GitHub URL:
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        - https://github.com/owner/repo/tree/main/...
        - https://github.com/owner/repo/blob/main/...
        - https://github.com/owner/repo/releases/...
        - https://raw.githubusercontent.com/owner/repo/main/...
        Returns None if not a GitHub URL.
        """
        s = (url or "").strip()
        if not s:
            return None

        m_raw = re.match(
            r"^https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)(?:/.*)?$",
            s,
            re.IGNORECASE,
        )
        if m_raw:
            return m_raw.group(1), m_raw.group(2), m_raw.group(3)

        m_gh = re.match(
            r"^https?://(?:www\.)?github\.com/([^/]+)/([^/?#]+?)(?:\.git)?(?:/(tree|blob|raw)/([^/]+))?(?:/.*)?$",
            s,
            re.IGNORECASE,
        )
        if m_gh:
            owner = m_gh.group(1)
            repo = m_gh.group(2)
            branch = m_gh.group(4) or GITHUB_BRANCH
            return owner, repo, branch

        return None

    @staticmethod
    def normalize_github_raw_url(url: str) -> str:
        """Converts GitHub web /blob/ URLs to direct raw.githubusercontent.com download URLs."""
        s = (url or "").strip()
        m = re.match(
            r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$",
            s,
            re.IGNORECASE,
        )
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
        return s

    @classmethod
    def _http_get_bytes(
        cls,
        url: str,
        timeout: int = 15,
        github_token: str = "",
        accept: str = "",
    ) -> bytes:
        sep = "&" if "?" in url else "?"
        req_url = f"{url}{sep}t={int(time.time())}"
        headers = cls._build_headers(github_token=github_token, accept=accept)
        try:
            import requests
            resp = requests.get(req_url, headers=headers, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp.content
        except ImportError:
            req = urllib.request.Request(req_url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()

    @classmethod
    def _fetch_github_head_sha(cls, owner: str, repo: str, branch: str = "main", github_token: str = "") -> str:
        """Returns the exact latest commit SHA on a GitHub branch (zero CDN cache lag)."""
        api_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
        try:
            raw = cls._http_get_bytes(
                api_url,
                timeout=8,
                github_token=github_token,
                accept="application/vnd.github.sha",
            )
            sha = raw.decode("utf-8", errors="ignore").strip()
            if re.fullmatch(r"[0-9a-fA-F]{40}", sha):
                return sha
        except Exception:
            pass
        return ""

    @classmethod
    def _fetch_github_latest_release(cls, owner: str, repo: str, github_token: str = "") -> Optional[Dict]:
        api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        try:
            raw = cls._http_get_bytes(
                api_url,
                timeout=12,
                github_token=github_token,
                accept="application/vnd.github+json",
            )
            rel = json.loads(raw.decode("utf-8"))
            if not isinstance(rel, dict) or not rel.get("tag_name"):
                return None

            tag_ver = str(rel.get("tag_name", "")).strip().lstrip("vV")
            dl_url = ""
            file_size_kb = 0
            for asset in rel.get("assets") or []:
                name = str(asset.get("name", "")).lower()
                if name.endswith(".zip"):
                    dl_url = asset.get("browser_download_url", "")
                    file_size_kb = round(int(asset.get("size", 0)) / 1024, 1)
                    if "aisummarai" in name or "update" in name:
                        break
            if not dl_url:
                dl_url = rel.get("zipball_url", "")

            pub_date = str(rel.get("published_at", ""))[:10]
            return {
                "version": tag_ver,
                "release_date": pub_date,
                "download_url": dl_url,
                "file_size_kb": file_size_kb,
                "changelog": rel.get("body") or f"• កំណែថ្មី v{tag_ver} ពី GitHub Releases",
                "repo_url": f"https://github.com/{owner}/{repo}",
                "provider": "github_release",
            }
        except Exception:
            return None

    @classmethod
    def _inspect_zip_bytes(cls, raw_bytes: bytes, source_url: str = "") -> Dict:
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
                names = zf.namelist()
                for cand in ("version.json", "release_output/version.json"):
                    match = next((n for n in names if n == cand or n.endswith("/" + cand)), None)
                    if match:
                        v_data = json.loads(zf.read(match).decode("utf-8"))
                        v_data["is_direct_zip"] = True
                        if source_url and not v_data.get("download_url"):
                            v_data["download_url"] = source_url
                        return v_data
                cfg_match = next((n for n in names if n == "updater_config.json" or n.endswith("/updater_config.json")), None)
                if cfg_match:
                    u_cfg = json.loads(zf.read(cfg_match).decode("utf-8"))
                    return {
                        "version": u_cfg.get("app_version", APP_VERSION),
                        "has_update": True,
                        "is_direct_zip": True,
                        "download_url": source_url,
                        "changelog": "• កញ្ចប់កូដអាប់ដេតថ្មី AiSummarai_Update.zip\n• គាំទ្រការអាប់ដេតស្វ័យប្រវត្តិ និងរក្សាទុក data/ ១០០%",
                    }
        except Exception:
            pass
        return {
            "version": APP_VERSION,
            "has_update": True,
            "is_direct_zip": True,
            "download_url": source_url,
            "changelog": "• កញ្ចប់កូដអាប់ដេតថ្មី AiSummarai_Update.zip ត្រៀមរួចរាល់\n• ចុច 'ទាញយក និងអាប់ដេតឥឡូវនេះ' ដើម្បីដំឡើង!",
        }

    @classmethod
    def check_manifest(cls, url_or_path: str, github_token: str = "") -> Optional[Dict]:
        """
        Reads version manifest from:
        1. Local .json or .zip file
        2. GitHub repo URL (https://github.com/owner/repo[.git]) -> version.json on main/master or GitHub Releases API
        3. Direct GitHub raw URL or HTTPS URL to version.json / .zip
        """
        s = (url_or_path or "").strip()
        if not s:
            return None

        # 1. Local file (.json or .zip)
        p = Path(s)
        if p.exists() and p.is_file():
            try:
                if p.suffix.lower() == ".zip":
                    return cls._inspect_zip_bytes(p.read_bytes(), source_url=str(p))
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None

        s = cls.normalize_github_raw_url(s)
        gh_info = cls.parse_github_repo(s)

        # 2. Build ordered manifest candidates (GitHub Contents API first for zero CDN cache lag!)
        is_direct_file_url = (
            s.lower().endswith(".json")
            or s.lower().endswith(".zip")
            or "raw.githubusercontent.com" in s.lower()
            or "/releases/download/" in s.lower()
        )
        candidate_requests: List[Tuple[str, str]] = []
        if gh_info and not s.lower().endswith(".zip"):
            owner, repo, branch = gh_info
            branches = [branch] + ([b for b in ("main", "master") if b != branch])
            for br in branches:
                candidate_requests.append((
                    f"https://api.github.com/repos/{owner}/{repo}/contents/version.json?ref={br}",
                    "application/vnd.github.raw+json",
                ))
        if is_direct_file_url:
            candidate_requests.append((s, ""))

        # 3. Raw CDN fallbacks (works even if GitHub REST API hits unauthenticated rate limit)
        if gh_info:
            owner, repo, branch = gh_info
            branches = [branch] + ([b for b in ("main", "master") if b != branch])
            for br in branches:
                for rel_path in ("version.json", "release_output/version.json"):
                    cand = (f"https://raw.githubusercontent.com/{owner}/{repo}/{br}/{rel_path}", "")
                    if cand not in candidate_requests:
                        candidate_requests.append(cand)
        elif not candidate_requests:
            candidate_requests.append((s, ""))

        for cand_url, accept_hdr in candidate_requests:
            try:
                raw_bytes = cls._http_get_bytes(
                    cand_url,
                    timeout=12,
                    github_token=github_token,
                    accept=accept_hdr,
                )
                if raw_bytes.startswith(b"PK\x03\x04") or raw_bytes.startswith(b"PK\x05\x06"):
                    return cls._inspect_zip_bytes(raw_bytes, source_url=cand_url)
                data = json.loads(raw_bytes.decode("utf-8"))
                if isinstance(data, dict) and (data.get("version") or data.get("app_version")):
                    if not data.get("version"):
                        data["version"] = data.get("app_version", "")
                    if gh_info:
                        owner, repo, branch = gh_info
                        data.setdefault("repo_url", f"https://github.com/{owner}/{repo}")
                        if not data.get("download_url") or _is_legacy_gdrive_url(data.get("download_url", "")):
                            data["download_url"] = (
                                f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/release_output/AiSummarai_Update.zip"
                            )
                    data.setdefault("provider", "github")
                    return data
            except Exception:
                continue

        # 4. Fallback to GitHub Releases API (/releases/latest)
        if gh_info:
            owner, repo, _ = gh_info
            rel_data = cls._fetch_github_latest_release(owner, repo, github_token=github_token)
            if rel_data:
                return rel_data

        return None

    @classmethod
    def check_for_updates(cls, target_url_or_path: str = "") -> Optional[Dict]:
        """
        ពិនិត្យរកមើលកំណែថ្មីពី GitHub Repository / Manifest URL (version.json) ឬ Local .zip។
        ត្រឡប់ជា Dict៖ {'has_update': bool, 'remote_version': str, 'current_version': str, 'changelog': str, ...}
        """
        cfg = get_updater_config()
        src = (
            (target_url_or_path or "").strip()
            or cfg.get("manifest_url")
            or cfg.get("github_repo_url")
            or GITHUB_MANIFEST_URL
        )
        if _is_legacy_gdrive_url(src):
            src = GITHUB_MANIFEST_URL
        if not src:
            return None

        token = cfg.get("github_token", "")
        try:
            info = cls.check_manifest(src, github_token=token)
            if not info or not isinstance(info, dict):
                return None
            remote_ver = str(info.get("version") or info.get("app_version") or "").strip()
            if not remote_ver:
                return None

            curr_tuple = cls._parse_ver(APP_VERSION)
            rem_tuple = cls._parse_ver(remote_ver)
            if info.get("is_direct_zip"):
                has_update = True
            else:
                has_update = rem_tuple > curr_tuple

            dl_url = info.get("download_url", "")
            if _is_legacy_gdrive_url(dl_url) or not dl_url:
                dl_url = cfg.get("update_zip_url") or GITHUB_UPDATE_ZIP_URL

            return {
                "has_update": has_update,
                "remote_version": remote_ver,
                "current_version": APP_VERSION,
                "changelog": info.get("changelog", "• កែសម្រួលប្រព័ន្ធទូទៅ និងបង្កើនល្បឿន"),
                "release_date": info.get("release_date", ""),
                "download_url": dl_url,
                "repo_url": info.get("repo_url", cfg.get("github_repo_url", GITHUB_REPO_URL)),
                "file_size_kb": info.get("file_size_kb", 0),
                "provider": info.get("provider", "github"),
            }
        except Exception:
            return None

    @classmethod
    def _download_http_file(
        cls,
        url: str,
        dest_path: Path,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        github_token: str = "",
    ) -> bool:
        """
        ទាញយកឯកសារ .zip ពី GitHub (Raw / Releases / Branch Archive) ឬ Direct HTTPS URL ដោយមាន Progress Callback។
        """
        clean_url = cls.normalize_github_raw_url(url)
        sep = "&" if "?" in clean_url else "?"
        dl_url = f"{clean_url}{sep}t={int(time.time())}"
        headers = cls._build_headers(github_token=github_token)

        if progress_cb:
            progress_cb(12, "កំពុងភ្ជាប់ទៅកាន់ GitHub Update Server...")

        # Method 1: requests (fast streaming + GitHub 302 redirect handling)
        try:
            import requests
            with requests.get(dl_url, headers=headers, stream=True, timeout=45, allow_redirects=True) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0 and progress_cb:
                                pct = min(88, max(15, int((downloaded / total_size) * 88)))
                                progress_cb(pct, f"កំពុងទាញយកកញ្ចប់កូដពី GitHub ({pct}%)...")
                            elif progress_cb and downloaded > 0:
                                mb = round(downloaded / (1024 * 1024), 2)
                                progress_cb(50, f"កំពុងទាញយកកញ្ចប់កូដពី GitHub ({mb} MB)...")
            if dest_path.exists() and zipfile.is_zipfile(dest_path):
                return True
        except ImportError:
            pass
        except Exception:
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            return False

        # Method 2: urllib fallback
        try:
            req = urllib.request.Request(dl_url, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0 and progress_cb:
                            pct = min(88, max(15, int((downloaded / total_size) * 88)))
                            progress_cb(pct, f"កំពុងទាញយកកញ្ចប់កូដពី GitHub ({pct}%)...")
                        elif progress_cb and downloaded > 0:
                            mb = round(downloaded / (1024 * 1024), 2)
                            progress_cb(50, f"កំពុងទាញយកកញ្ចប់កូដពី GitHub ({mb} MB)...")
            return dest_path.exists() and zipfile.is_zipfile(dest_path)
        except Exception:
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            return False

    @classmethod
    def extract_package_safe(cls, zip_path: Path, extract_dir: Path) -> Path:
        """
        Safely extracts an update .zip package (supports both AiSummarai_Update.zip and GitHub archive ZIPs):
        - Blocks path-traversal (Zip Slip) entries
        - Strictly skips/strips any 'data/' user database/workspace entries so user projects are NEVER overwritten
        - Skips VCS/build/admin files (.git/, build/, dist/, installer_output/, release_output/, admin_keygen.py)
        Returns the resolved source_root containing updated app code.
        """
        extract_dir = Path(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        resolved_root = extract_dir.resolve()

        blocked_dirs = {
            "data", "__macosx", ".git", ".agents", ".venv", "venv",
            "build", "dist", "installer_output", "release_output", ".idea", ".vscode",
        }
        blocked_files = {
            "admin_keygen.py", "admin_keygen.bat",
            "push_update_to_gdrive.bat", "push_update_to_github.bat",
            "build_exe.bat", "build_installer.bat",
        }

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                norm_parts = Path(member.filename).parts
                if not norm_parts or any(p == ".." for p in norm_parts):
                    continue
                lower_parts = [p.lower() for p in norm_parts]
                # Never extract blocked directories at root or nested 1 level inside a GitHub archive folder
                if lower_parts[0] in blocked_dirs or (len(lower_parts) >= 2 and lower_parts[1] in blocked_dirs):
                    continue
                if lower_parts[-1] in blocked_files:
                    continue
                dest = (resolved_root / member.filename).resolve()
                if not str(dest).startswith(str(resolved_root)):
                    continue
                if member.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member, "r") as src_f, open(dest, "wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)

        source_root = extract_dir
        sub_items = [p for p in extract_dir.iterdir() if p.name != "__MACOSX"]
        if len(sub_items) == 1 and sub_items[0].is_dir():
            if (sub_items[0] / "core").exists() or (sub_items[0] / "main.py").exists():
                source_root = sub_items[0]

        for protected_dir in ("data", ".git", "release_output"):
            p_dir = source_root / protected_dir
            if p_dir.exists():
                shutil.rmtree(p_dir, ignore_errors=True)
        return source_root

    @classmethod
    def _build_github_download_candidates(cls, src: str, github_token: str = "") -> List[str]:
        candidates: List[str] = []

        def _add(u: str):
            u = cls.normalize_github_raw_url((u or "").strip())
            if u and not _is_legacy_gdrive_url(u) and u not in candidates:
                candidates.append(u)

        src = cls.normalize_github_raw_url(src)
        gh_info = cls.parse_github_repo(src)

        # 1. If GitHub repo, resolve latest commit SHA first so Fastly CDN NEVER serves a stale ZIP!
        if gh_info and not src.lower().endswith(".zip"):
            owner, repo, branch = gh_info
            head_sha = cls._fetch_github_head_sha(owner, repo, branch, github_token=github_token)
            if head_sha:
                _add(f"https://raw.githubusercontent.com/{owner}/{repo}/{head_sha}/release_output/AiSummarai_Update.zip")

        # 2. If src is direct .zip URL, try it first
        if src.lower().endswith(".zip") or "/releases/download/" in src.lower():
            _add(src)

        # 3. If src is version.json or a GitHub repo URL, inspect manifest
        if not src.lower().endswith(".zip"):
            info = cls.check_manifest(src, github_token=github_token) or {}
            if info.get("download_url"):
                _add(info["download_url"])

        # 3. Smart GitHub fallbacks (release_output/AiSummarai_Update.zip -> root zip -> Release asset -> branch archive)
        if gh_info:
            owner, repo, branch = gh_info
            branches = [branch] + [b for b in ("main", "master") if b != branch]
            for br in branches:
                _add(f"https://raw.githubusercontent.com/{owner}/{repo}/{br}/release_output/AiSummarai_Update.zip")
                _add(f"https://raw.githubusercontent.com/{owner}/{repo}/{br}/AiSummarai_Update.zip")
            rel = cls._fetch_github_latest_release(owner, repo, github_token=github_token)
            if rel and rel.get("download_url"):
                _add(rel["download_url"])
            for br in branches:
                _add(f"https://github.com/{owner}/{repo}/archive/refs/heads/{br}.zip")
        elif src and src not in candidates:
            _add(src)

        return candidates

    @classmethod
    def apply_extracted_files_to_dir(cls, source_root: Path, app_root: Path) -> int:
        """
        Pure-Python direct hot-update installer:
        - Clears stale __pycache__ directories in both app_root and _internal
        - Copies all updated .py / .json / asset files directly using shutil.copy2
          (Python source & config files are never locked by Windows while the .exe runs!)
        - Never touches data/ user databases or locked running .exe/.dll binaries
        Returns the number of files updated.
        """
        source_root = Path(source_root).resolve()
        app_root = Path(app_root).resolve()
        internal_dir = app_root / "_internal"
        target_roots = [app_root]
        if internal_dir.exists() and internal_dir.is_dir():
            target_roots.append(internal_dir)

        # 1. Clear stale bytecode caches in both app_root and _internal
        for t_root in target_roots:
            for sub in ("core", "ui"):
                cache_dir = t_root / sub / "__pycache__"
                if cache_dir.exists():
                    shutil.rmtree(cache_dir, ignore_errors=True)

        # 2. Copy every extracted file cleanly in pure Python (100% reliable, zero cmd/xcopy bugs!)
        copied = 0
        for dirpath, dirnames, filenames in os.walk(source_root):
            dirnames[:] = [d for d in dirnames if d.lower() not in ("data", ".git", "__pycache__")]
            rel_dir = Path(dirpath).relative_to(source_root)
            for fname in filenames:
                src_file = Path(dirpath) / fname
                rel_file = rel_dir / fname if str(rel_dir) != "." else Path(fname)
                # Copy into app_root (always highest priority via _HotUpdateDiskFinder)
                dst_main = app_root / rel_file
                try:
                    dst_main.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_main)
                    copied += 1
                except PermissionError:
                    pass
                # Mirror core/, ui/, version.json, updater_config.json into _internal as well
                if internal_dir.exists():
                    top_part = rel_file.parts[0].lower() if rel_file.parts else ""
                    if top_part in ("core", "ui") or str(rel_file).lower() in ("version.json", "updater_config.json"):
                        dst_int = internal_dir / rel_file
                        try:
                            dst_int.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src_file, dst_int)
                        except PermissionError:
                            pass
        return copied

    @classmethod
    def download_and_apply_package(
        cls,
        source_url_or_path: str = "",
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """
        ទាញយកកញ្ចប់កូដថ្មី (.zip) ពី GitHub Official Server ឬ Local .zip
        ហើយអាប់ដេតកូដកម្មវិធីភ្លាមៗដោយមិនចាំបាច់ដំឡើងឡើងវិញ និងរក្សាទុក data/ ទាំងអស់!
        """
        cfg = get_updater_config()
        src = (source_url_or_path or "").strip()
        if not src or _is_legacy_gdrive_url(src):
            src = cfg.get("manifest_url") or cfg.get("github_repo_url") or GITHUB_MANIFEST_URL

        if not src:
            raise ValueError(
                "សូមភ្ជាប់តំណភ្ជាប់ GitHub Repository ឬជ្រើសរើសឯកសារ .zip ជាមុនសិន!"
            )

        tmp_dir = Path("data/_update_temp")
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = tmp_dir / "update_pkg.zip"
        extract_dir = tmp_dir / "extracted"

        # ១. ទទួលយកឯកសារ .zip (ពី Local File ឬ GitHub Server)
        if Path(src).exists() and Path(src).is_file():
            if progress_cb:
                progress_cb(40, "កំពុងអានកញ្ចប់កូដ .zip ពីកុំព្យូទ័រ...")
            shutil.copy2(src, zip_path)
        else:
            token = cfg.get("github_token", "")
            if progress_cb:
                progress_cb(10, "កំពុងពិនិត្យកំណែថ្មីនៅលើ GitHub...")
            candidates = cls._build_github_download_candidates(src, github_token=token)
            downloaded_ok = False
            for dl_url in candidates:
                if cls._download_http_file(dl_url, zip_path, progress_cb=progress_cb, github_token=token):
                    downloaded_ok = True
                    break
            if not downloaded_ok:
                raise RuntimeError(
                    "មិនអាចទាញយកកញ្ចប់កូដពី GitHub បានទេ!\n"
                    f"Repository: {cfg.get('github_repo_url', GITHUB_REPO_URL)}\n"
                    "សូមពិនិត្យការភ្ជាប់អ៊ីនធឺណិត ឬប្រាកដថា GitHub Repository ត្រូវបានបើកជា Public "
                    "ហើយបាន Push ឯកសារ version.json និង release_output/AiSummarai_Update.zip រួចរាល់។"
                )

        if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
            raise RuntimeError(
                "ឯកសារដែលទាញយកមិនមែនជាកញ្ចប់ .zip ត្រឹមត្រូវទេ! "
                "សូមពិនិត្យមើលឯកសារនៅលើ GitHub Repository របស់អ្នក។"
            )

        # ២. ពន្លាកញ្ចប់ .zip និងស្វែងរក Root Folder (ការពារ Zip Slip និងមិនជាន់លើ data/ ដាច់ខាត!)
        if progress_cb:
            progress_cb(90, "កំពុងពន្លា និងផ្ទៀងផ្ទាត់កូដថ្មី...")
        source_root = cls.extract_package_safe(zip_path, extract_dir)

        # ៣. កំណត់លេខ Version ថ្មី (Detect & Ensure New Version)
        new_version = ""
        v_json = source_root / "version.json"
        if v_json.exists():
            try:
                v_dat = json.loads(v_json.read_text(encoding="utf-8"))
                new_version = (v_dat.get("version") or "").strip()
            except Exception:
                pass

        if not new_version:
            u_cfg = source_root / "updater_config.json"
            if u_cfg.exists():
                try:
                    u_dat = json.loads(u_cfg.read_text(encoding="utf-8"))
                    new_version = (u_dat.get("app_version") or "").strip()
                except Exception:
                    pass

        if not new_version:
            u_py = source_root / "core" / "updater.py"
            if u_py.exists():
                try:
                    m_v = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', u_py.read_text(encoding="utf-8"))
                    if m_v:
                        new_version = m_v.group(1).strip()
                except Exception:
                    pass

        if not new_version or cls._parse_ver(new_version) <= cls._parse_ver(APP_VERSION):
            new_version = cls.bump_version(APP_VERSION)

        # កត់ត្រា និងរក្សា GitHub config ទៅក្នុង source_root និង config បច្ចុប្បន្ន
        if new_version:
            s_upd = source_root / "core" / "updater.py"
            if s_upd.exists():
                try:
                    txt = s_upd.read_text(encoding="utf-8")
                    txt = re.sub(r'APP_VERSION\s*=\s*["\'][^"\']+["\']', f'APP_VERSION = "{new_version}"', txt, count=1)
                    s_upd.write_text(txt, encoding="utf-8")
                except Exception:
                    pass

            s_cfg = source_root / "updater_config.json"
            cfg_dict = dict(cfg)
            if s_cfg.exists():
                try:
                    loaded = json.loads(s_cfg.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        cfg_dict.update(loaded)
                except Exception:
                    pass
            cfg_dict["app_version"] = new_version
            cfg_dict["update_provider"] = "github"
            cfg_dict["github_repo_url"] = cfg.get("github_repo_url", GITHUB_REPO_URL)
            cfg_dict["github_branch"] = cfg.get("github_branch", GITHUB_BRANCH)
            cfg_dict["manifest_url"] = cfg.get("manifest_url", GITHUB_MANIFEST_URL)
            cfg_dict["update_zip_url"] = cfg.get("update_zip_url", GITHUB_UPDATE_ZIP_URL)
            try:
                s_cfg.write_text(json.dumps(cfg_dict, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

        # ៤. កំណត់ទីតាំង Install/App Directory និងចម្លងកូដថ្មីដោយផ្ទាល់តាម Pure Python (100% Reliable!)
        if getattr(sys, "frozen", False):
            app_root = Path(sys.executable).resolve().parent
            exe_name = Path(sys.executable).name
            launch_cmd = f'start "" "{exe_name}"'
        else:
            app_root = Path(__file__).resolve().parent.parent
            py_exe = sys.executable
            launch_cmd = (
                'if exist "RUN_AISUMMARAI.vbs" (\r\n'
                '    start "" wscript.exe "RUN_AISUMMARAI.vbs"\r\n'
                ') else if exist "AiSummarai.exe" (\r\n'
                '    start "" "AiSummarai.exe"\r\n'
                ') else (\r\n'
                f'    start "" "{py_exe}" "main.py"\r\n'
                ')'
            )

        if progress_cb:
            progress_cb(94, f"កំពុងបញ្ចូលឯកសារកូដថ្មី v{new_version}...")

        copied_count = cls.apply_extracted_files_to_dir(source_root, app_root)
        if copied_count <= 0:
            raise RuntimeError(
                f"មិនអាចចម្លងឯកសារកូដថ្មីចូល {app_root} បានទេ! សូមសាកល្បង Run as Administrator។"
            )

        # Update active updater_config.json and DB ONLY AFTER files are verified copied!
        try:
            save_updater_config({"app_version": new_version})
        except Exception:
            pass
        try:
            from core.database import Database
            db = Database()
            db.set_setting("app_version", new_version)
            db.close()
        except Exception:
            pass

        # Clean temp download directory immediately
        shutil.rmtree(tmp_dir, ignore_errors=True)

        # ៥. រៀបចំ Pure-ASCII CRLF Relaunch Script ក្នុង TEMP (គ្មានបញ្ហា UTF-8 ឬ timeout/xcopy!)
        temp_dir = Path(os.environ.get("TEMP", os.environ.get("TMP", "C:/Windows/Temp")))
        bat_path = temp_dir / f"ai_summarai_relaunch_{int(time.time())}.bat"
        pid = os.getpid()

        bat_content = (
            "@echo off\r\n"
            f"taskkill /F /PID {pid} >nul 2>&1\r\n"
            "ping -n 3 127.0.0.1 >nul\r\n"
            f'cd /d "{app_root.resolve()}"\r\n'
            f"{launch_cmd}\r\n"
            'del "%~f0" >nul 2>&1\r\n'
            "exit\r\n"
        )
        bat_path.write_bytes(bat_content.encode("ascii", errors="ignore"))

        if progress_cb:
            progress_cb(100, f"អាប់ដេតជោគជ័យ {copied_count} ឯកសារទៅកាន់ v{new_version}! កំពុងបើកកម្មវិធីឡើងវិញ...")

        # ៦. បើកដំណើរការ Relaunch Script (CREATE_NO_WINDOW + CREATE_NEW_PROCESS_GROUP — NO conflicting DETACHED_PROCESS!)
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        flags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0

        popen_cls = getattr(subprocess, "_orig_popen", subprocess.Popen)
        popen_cls(
            ["cmd.exe", "/c", str(bat_path.resolve())],
            creationflags=flags,
            close_fds=True,
            startupinfo=si,
        )
        os._exit(0)

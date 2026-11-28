import argparse
import datetime
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.updater import (
    InAppPackageUpdater,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_BRANCH,
    GITHUB_REPO_URL,
    GITHUB_MANIFEST_URL,
    GITHUB_UPDATE_ZIP_URL,
)


def fetch_remote_github_version(timeout: int = 5) -> str:
    """Fetch live published version from GitHub raw version.json directly with cache-busting."""
    url = f"{GITHUB_MANIFEST_URL}?t={int(datetime.datetime.now().timestamp())}"
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AiSummarai-Updater", "Cache-Control": "no-cache", "Pragma": "no-cache"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            v = str(data.get("version") or data.get("app_version") or "").strip().lstrip("vV")
            if v:
                return v
    except Exception:
        pass
    return ""


def read_current_version() -> str:
    rem_v = fetch_remote_github_version()
    if rem_v:
        return rem_v
    upd_path = ROOT / "core" / "updater.py"
    if upd_path.exists():
        m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', upd_path.read_text(encoding="utf-8"))
        if m:
            return m.group(1).strip()
    v_path = ROOT / "version.json"
    if v_path.exists():
        try:
            d = json.loads(v_path.read_text(encoding="utf-8"))
            if d.get("version"):
                return str(d["version"]).strip()
        except Exception:
            pass
    return "1.6.0"


def main(target_version: str = "", bump: bool = False, changelog: str = ""):
    if not target_version and not bump and len(sys.argv) > 1 and Path(sys.argv[0]).name == "sync_and_pack.py":
        parser = argparse.ArgumentParser(description="Sync & Package Ai Summarai (GitHub Auto-Updater)")
        parser.add_argument("--bump", action="store_true", help="Auto-increment version with 0..9 rollover (e.g. 1.6.9 -> 1.7.0)")
        parser.add_argument("--version", default="", help="Explicit target version (e.g. 1.6.1)")
        parser.add_argument("--changelog", default="", help="Custom release changelog")
        args = parser.parse_args()
        target_version = args.version.strip()
        bump = args.bump
        changelog = args.changelog.strip()

    curr_ver = read_current_version()
    if target_version:
        app_version = target_version
    elif bump:
        app_version = InAppPackageUpdater.bump_version(curr_ver)
    else:
        app_version = curr_ver

    print("=" * 60)
    print(f"  Sync & Package Ai Summarai v{app_version} (GitHub Update Engine)")
    if app_version != curr_ver:
        print(f"  Auto-Bump Rollover: v{curr_ver} -> v{app_version}")
    print("=" * 60)

    # 1. Update core/updater.py
    upd_path = ROOT / "core" / "updater.py"
    if upd_path.exists():
        t = upd_path.read_text(encoding="utf-8")
        t = re.sub(r'APP_VERSION\s*=\s*["\'][^"\']+["\']', f'APP_VERSION = "1.7.3"', t, count=1)
        upd_path.write_text(t, encoding="utf-8")
        print(f"[OK] Updated core/updater.py to v{app_version}")

    # 2. Update updater_config.json (GitHub Official Server)
    cfg_path = ROOT / "updater_config.json"
    existing_token = ""
    if cfg_path.exists():
        try:
            existing_token = json.loads(cfg_path.read_text(encoding="utf-8")).get("github_token", "")
        except Exception:
            pass
    cfg = {
        "app_version": app_version,
        "update_provider": "github",
        "github_repo_url": GITHUB_REPO_URL,
        "github_branch": GITHUB_BRANCH,
        "manifest_url": GITHUB_MANIFEST_URL,
        "update_zip_url": GITHUB_UPDATE_ZIP_URL,
        "auto_check_updates": True,
        "last_check_timestamp": 0,
    }
    if existing_token:
        cfg["github_token"] = existing_token
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Updated updater_config.json -> GitHub ({GITHUB_OWNER}/{GITHUB_REPO})")

    # 3. Update version.json
    default_changelog = (
        "• 🔢 Auto Rollover Versioning: ប្រព័ន្ធដំឡើងលេខកំណែស្វ័យប្រវត្តិពេលកែកូដ/បន្ថែមមុខងារ (1.6.1 -> 1.6.9 -> 1.7.0 -> 2.0.0)។\n"
        "• 🐙 GitHub Auto-Updater: ទាញយក Update ផ្ទាល់ពី GitHub ផ្លូវការ (លឿន មានស្ថេរភាព និងគ្មានដែនកំណត់ Google Drive)។\n"
        "• 📚 Series Profile, 🎼 AI Vocal Remover, 🖼️ AI Hook Banner & Thumbnail, 🎬 Intro/Outro Stitcher, 🚀 1-Click Auto Pipeline។\n"
        "• ⚡ AI Viral Shorts Clipper (9:16), 🎵 Emotion SFX Auto-Matcher, 🔑 Multi-API 429 Failover, ✨ HD 1080p Upscaler & Social Pack។"
    )
    v_path = ROOT / "version.json"
    v_data = {
        "version": app_version,
        "app_version": app_version,
        "provider": "github",
        "release_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "repo_url": GITHUB_REPO_URL,
        "manifest_url": GITHUB_MANIFEST_URL,
        "download_url": GITHUB_UPDATE_ZIP_URL,
        "changelog": changelog or default_changelog,
    }
    v_path.write_text(json.dumps(v_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Updated version.json to v{app_version} (GitHub URLs)")

    # 4. Update version_info.txt
    v_info_path = ROOT / "version_info.txt"
    if v_info_path.exists():
        try:
            v_parts = [p for p in app_version.split(".") if p.isdigit()]
            while len(v_parts) < 4:
                v_parts.append("0")
            tuple_str = f"({', '.join(v_parts[:4])})"
            vt = v_info_path.read_text(encoding="utf-8")
            vt = re.sub(r'filevers=\([^)]+\)', f'filevers={tuple_str}', vt)
            vt = re.sub(r'prodvers=\([^)]+\)', f'prodvers={tuple_str}', vt)
            vt = re.sub(r"StringStruct\('FileVersion',\s*'[^']+'\)", f"StringStruct('FileVersion', '{app_version}')", vt)
            vt = re.sub(r"StringStruct\('ProductVersion',\s*'[^']+'\)", f"StringStruct('ProductVersion', '{app_version}')", vt)
            v_info_path.write_text(vt, encoding="utf-8")
            print(f"[OK] Updated version_info.txt to v{app_version}")
        except Exception as e:
            print(f"[WARN] version_info.txt: {e}")

    # 5. Update AiSummarai_Installer.iss & README.md
    iss_path = ROOT / "AiSummarai_Installer.iss"
    if iss_path.exists():
        try:
            it = iss_path.read_text(encoding="utf-8")
            it = re.sub(r'#define MyAppVersion\s+"[^"]+"', f'#define MyAppVersion "{app_version}"', it)
            iss_path.write_text(it, encoding="utf-8")
            print(f"[OK] Updated AiSummarai_Installer.iss to v{app_version}")
        except Exception as e:
            print(f"[WARN] AiSummarai_Installer.iss: {e}")

    readme_path = ROOT / "README.md"
    if readme_path.exists():
        try:
            rt = readme_path.read_text(encoding="utf-8")
            rt = re.sub(r"\(`v\d+\.\d+\.\d+`\)", f"(`v{app_version}`)", rt)
            readme_path.write_text(rt, encoding="utf-8")
        except Exception:
            pass

    # 6. Sync to dist/AiSummarai
    dist_dir = ROOT / "dist" / "AiSummarai"
    if dist_dir.exists():
        d_core = dist_dir / "core"
        d_core.mkdir(parents=True, exist_ok=True)
        for cf in (ROOT / "core").glob("*.py"):
            shutil.copy2(cf, d_core / cf.name)
        d_ui = dist_dir / "ui"
        d_ui.mkdir(parents=True, exist_ok=True)
        for uf in (ROOT / "ui").glob("*.py"):
            shutil.copy2(uf, d_ui / uf.name)
        shutil.copy2(v_path, dist_dir / "version.json")
        shutil.copy2(cfg_path, dist_dir / "updater_config.json")
        print("[OK] Synced updated files to dist/AiSummarai/")

    # 6B. Sync to installed program directory if present
    installed_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ai Summarai"
    if installed_dir.exists():
        for target_base in [installed_dir, installed_dir / "_internal"]:
            t_core = target_base / "core"
            t_core.mkdir(parents=True, exist_ok=True)
            for cf in (ROOT / "core").glob("*.py"):
                shutil.copy2(cf, t_core / cf.name)
            t_ui = target_base / "ui"
            t_ui.mkdir(parents=True, exist_ok=True)
            for uf in (ROOT / "ui").glob("*.py"):
                shutil.copy2(uf, t_ui / uf.name)
        # copy config and standalone scripts
        for fn in ["version.json", "updater_config.json", "verify_setup.py"]:
            sp = ROOT / fn
            if sp.exists():
                shutil.copy2(sp, installed_dir / fn)
        # sync data files if any
        if (ROOT / "data").exists():
            (installed_dir / "data").mkdir(parents=True, exist_ok=True)
            for df in (ROOT / "data").glob("*.json"):
                shutil.copy2(df, installed_dir / "data" / df.name)
        # purge __pycache__ in installed dir
        for cache_dir in installed_dir.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)
        print("[OK] Synced updated files to installed App & _internal, purged __pycache__")

    # 7. Repack release_output/AiSummarai_Update.zip
    out_dir = ROOT / "release_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / "AiSummarai_Update.zip"

    exclude_dirs = {
        "data", "build", "dist", "installer_output", "release_output",
        "__pycache__", ".agents", ".git", ".venv", "venv", ".idea", ".vscode", "bin",
    }
    exclude_files = {
        "admin_keygen.py", "ADMIN_KEYGEN.bat",
        "PUSH_UPDATE_TO_GDRIVE.bat", "PUSH_UPDATE_TO_GITHUB.bat",
        "BUILD_INSTALLER.bat", "BUILD_EXE.bat",
    }
    exclude_exts = {
        ".pyc", ".db", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".mp3",
        ".docx", ".log", ".tmp", ".iss",
    }

    if zip_path.exists():
        zip_path.unlink()

    print("[*] Creating AiSummarai_Update.zip...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root_folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
            rel_root = Path(root_folder).relative_to(ROOT)

            for f in files:
                if f.startswith(".") or f in exclude_files:
                    continue
                p = Path(root_folder) / f
                if p.suffix.lower() in exclude_exts:
                    continue
                arcname = str(rel_root / f) if str(rel_root) != "." else f
                zf.write(p, arcname)

    size_kb = round(zip_path.stat().st_size / 1024, 1)
    size_mb = round(size_kb / 1024, 2)
    print(f"[OK] Created {zip_path.name}: {size_kb} KB ({size_mb} MB)")

    # 8. Update both version.json and release_output/version.json with exact file_size_kb
    v_data["file_size_kb"] = size_kb
    v_json_str = json.dumps(v_data, indent=2, ensure_ascii=False)
    v_path.write_text(v_json_str, encoding="utf-8")
    (out_dir / "version.json").write_text(v_json_str, encoding="utf-8")
    if dist_dir.exists():
        shutil.copy2(v_path, dist_dir / "version.json")
    print("[OK] Saved version.json & release_output/version.json")

    print(f"\n🎉 ALL GITHUB VERSION & PACKAGING TASKS COMPLETED (v{app_version})!")
    return app_version


if __name__ == "__main__":
    main()

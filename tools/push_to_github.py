import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.updater import (
    InAppPackageUpdater,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_BRANCH,
    GITHUB_REPO_URL,
    GITHUB_GIT_URL,
    GITHUB_MANIFEST_URL,
    GITHUB_UPDATE_ZIP_URL,
)

OUTPUT_DIR = ROOT_DIR / "release_output"
UPDATER_PY = ROOT_DIR / "core" / "updater.py"
CONFIG_FILE = ROOT_DIR / "updater_config.json"
VERSION_JSON = ROOT_DIR / "version.json"
VERSION_INFO_TXT = ROOT_DIR / "version_info.txt"
ISS_FILE = ROOT_DIR / "AiSummarai_Installer.iss"


def find_git_exe() -> str:
    found = shutil.which("git")
    if found:
        return found

    candidates = [
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe",
    ]
    gh_desktop = Path(os.environ.get("LOCALAPPDATA", "")) / "GitHubDesktop"
    if gh_desktop.exists():
        for app_dir in sorted(gh_desktop.glob("app-*"), reverse=True):
            candidates.append(app_dir / "resources" / "app" / "git" / "cmd" / "git.exe")

    for c in candidates:
        if c.exists():
            return str(c)
    return ""


def read_current_version() -> str:
    if UPDATER_PY.exists():
        m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', UPDATER_PY.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return "1.6.0"


def bump_version(ver: str) -> str:
    """Auto decimal rollover (1.6.1 -> ... -> 1.6.9 -> 1.7.0 -> ... -> 1.9.9 -> 2.0.0)."""
    return InAppPackageUpdater.bump_version(ver)


def ask_input(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
        return val if val else default
    except EOFError:
        return default


def update_version_files(new_ver: str, changelog: str):
    # 1. core/updater.py
    if UPDATER_PY.exists():
        text = UPDATER_PY.read_text(encoding="utf-8")
        text = re.sub(r'APP_VERSION\s*=\s*["\'][^"\']+["\']', f'APP_VERSION = "{new_ver}"', text, count=1)
        UPDATER_PY.write_text(text, encoding="utf-8")

    # 2. tools/sync_and_pack.py
    sp = ROOT_DIR / "tools" / "sync_and_pack.py"
    if sp.exists():
        st = sp.read_text(encoding="utf-8")
        st = re.sub(r'APP_VERSION\s*=\s*["\'][^"\']+["\']', f'APP_VERSION = "{new_ver}"', st, count=1)
        sp.write_text(st, encoding="utf-8")

    # 3. updater_config.json
    cfg = {
        "app_version": new_ver,
        "update_provider": "github",
        "github_repo_url": GITHUB_REPO_URL,
        "github_branch": GITHUB_BRANCH,
        "manifest_url": GITHUB_MANIFEST_URL,
        "update_zip_url": GITHUB_UPDATE_ZIP_URL,
        "auto_check_updates": True,
        "last_check_timestamp": 0,
    }
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    # 4. version_info.txt
    if VERSION_INFO_TXT.exists():
        v_parts = [p for p in new_ver.split(".") if p.isdigit()]
        while len(v_parts) < 4:
            v_parts.append("0")
        tuple_str = f"({', '.join(v_parts[:4])})"
        vt = VERSION_INFO_TXT.read_text(encoding="utf-8")
        vt = re.sub(r'filevers=\([^)]+\)', f'filevers={tuple_str}', vt)
        vt = re.sub(r'prodvers=\([^)]+\)', f'prodvers={tuple_str}', vt)
        vt = re.sub(r"StringStruct\('FileVersion',\s*'[^']+'\)", f"StringStruct('FileVersion', '{new_ver}')", vt)
        vt = re.sub(r"StringStruct\('ProductVersion',\s*'[^']+'\)", f"StringStruct('ProductVersion', '{new_ver}')", vt)
        VERSION_INFO_TXT.write_text(vt, encoding="utf-8")

    # 5. AiSummarai_Installer.iss & README.md
    if ISS_FILE.exists():
        it = ISS_FILE.read_text(encoding="utf-8")
        it = re.sub(r'#define MyAppVersion\s+"[^"]+"', f'#define MyAppVersion "{new_ver}"', it)
        ISS_FILE.write_text(it, encoding="utf-8")

    readme_f = ROOT_DIR / "README.md"
    if readme_f.exists():
        rt = readme_f.read_text(encoding="utf-8")
        rt = re.sub(r"\(`v\d+\.\d+\.\d+`\)", f"(`v{new_ver}`)", rt)
        readme_f.write_text(rt, encoding="utf-8")

    # 6. Build release_output/AiSummarai_Update.zip
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUTPUT_DIR / "AiSummarai_Update.zip"
    if zip_path.exists():
        zip_path.unlink()

    manifest = {
        "version": new_ver,
        "app_version": new_ver,
        "provider": "github",
        "release_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "repo_url": GITHUB_REPO_URL,
        "manifest_url": GITHUB_MANIFEST_URL,
        "download_url": GITHUB_UPDATE_ZIP_URL,
        "changelog": changelog,
    }
    VERSION_JSON.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

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

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root_folder, dirs, files in os.walk(ROOT_DIR):
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
            rel_root = Path(root_folder).relative_to(ROOT_DIR)
            for f in files:
                if f.startswith(".") or f in exclude_files:
                    continue
                p = Path(root_folder) / f
                if p.suffix.lower() in exclude_exts:
                    continue
                arcname = str(rel_root / f) if str(rel_root) != "." else f
                zf.write(p, arcname)

    size_kb = round(zip_path.stat().st_size / 1024, 1)
    manifest["file_size_kb"] = size_kb
    manifest_str = json.dumps(manifest, indent=2, ensure_ascii=False)
    VERSION_JSON.write_text(manifest_str, encoding="utf-8")
    (OUTPUT_DIR / "version.json").write_text(manifest_str, encoding="utf-8")

    # Sync dist/AiSummarai if present
    dist_dir = ROOT_DIR / "dist" / "AiSummarai"
    if dist_dir.exists():
        for sub in ("core", "ui"):
            dst = dist_dir / sub
            dst.mkdir(parents=True, exist_ok=True)
            for f in (ROOT_DIR / sub).glob("*.py"):
                shutil.copy2(f, dst / f.name)
        shutil.copy2(VERSION_JSON, dist_dir / "version.json")
        shutil.copy2(CONFIG_FILE, dist_dir / "updater_config.json")

    return zip_path, size_kb


def run_git(git_exe: str, args):
    print(f"  $ git {' '.join(args)}")
    res = subprocess.run([git_exe, *args], cwd=str(ROOT_DIR))
    return res.returncode


def main():
    parser = argparse.ArgumentParser(description="Package & Push Ai Summarai Update to GitHub")
    parser.add_argument("--version", default="", help="Release version (default: prompt / bump)")
    parser.add_argument("--changelog", default="", help="Changelog text")
    parser.add_argument("--no-push", action="store_true", help="Commit locally without git push")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode")
    args = parser.parse_args()

    os.chdir(ROOT_DIR)
    print("=" * 72)
    print(f"  🐙 Ai Summarai Studio — Push Update to GitHub ({GITHUB_OWNER}/{GITHUB_REPO})")
    print("=" * 72)

    git_exe = find_git_exe()
    if not git_exe:
        print("[ERROR] មិនអាចរកឃើញ Git ក្នុងកុំព្យូទ័រទេ! សូមដំឡើង Git ឬ GitHub Desktop ជាមុនសិន។")
        sys.exit(1)
    print(f"[OK] Git: {git_exe}")

    current_ver = read_current_version()
    suggested_ver = bump_version(current_ver)

    if args.version:
        new_ver = args.version.strip()
    elif args.auto:
        new_ver = suggested_ver
        print(f"\n[1] Auto-Bump Rollover: v{current_ver} -> v{new_ver}")
    else:
        print(f"\n[1] កំណែបច្ចុប្បន្ន៖ v{current_ver} (Auto Rollover បន្ទាប់៖ v{suggested_ver})")
        new_ver = ask_input(f"    បញ្ចូលលេខ Version ថ្មី [Enter យក v{suggested_ver}]: ", suggested_ver)

    default_changelog = "• កែសម្រួលប្រព័ន្ធទូទៅ បង្កើនល្បឿន និងបន្ថែមមុខងារថ្មី (GitHub Auto-Update)"
    if args.changelog:
        changelog = args.changelog.strip()
    elif args.auto:
        changelog = default_changelog
    else:
        print("\n[2] កំណត់ត្រាការកែប្រែ (Changelog)៖")
        changelog = ask_input("    បញ្ចូលចំណុចកែប្រែ [Enter យកលំនាំដើម]: ", default_changelog)

    print(f"\n[3] កំពុងវេចខ្ចប់កំណែ v{new_ver} និងបង្កើត AiSummarai_Update.zip...")
    zip_path, size_kb = update_version_files(new_ver, changelog)
    print(f"    [OK] {zip_path.name}: {size_kb} KB ({round(size_kb / 1024, 2)} MB)")

    print(f"\n[4] កំពុងភ្ជាប់ និង Push ទៅកាន់ {GITHUB_GIT_URL} ...")
    if not (ROOT_DIR / ".git").exists():
        run_git(git_exe, ["init", "-b", GITHUB_BRANCH])

    # Ensure origin remote points to GITHUB_GIT_URL
    chk = subprocess.run([git_exe, "remote", "get-url", "origin"], cwd=str(ROOT_DIR), capture_output=True, text=True)
    if chk.returncode != 0:
        run_git(git_exe, ["remote", "add", "origin", GITHUB_GIT_URL])
    elif chk.stdout.strip() != GITHUB_GIT_URL:
        run_git(git_exe, ["remote", "set-url", "origin", GITHUB_GIT_URL])

    run_git(git_exe, ["add", "-A"])
    run_git(git_exe, ["add", "-f", "release_output/AiSummarai_Update.zip", "release_output/version.json"])
    commit_rc = run_git(git_exe, ["commit", "-m", f"Release Ai Summarai v{new_ver}"])
    if commit_rc != 0:
        print("    [INFO] គ្មានការផ្លាស់ប្តូរថ្មីសម្រាប់ Commit ឬ Commit រួចហើយ។")

    if not args.no_push:
        push_rc = run_git(git_exe, ["push", "-u", "origin", GITHUB_BRANCH])
        if push_rc != 0:
            print("\n[WARN] Git push មិនទាន់ជោគជ័យ (សូម Sign-in GitHub ក្នុង Browser ឬ GitHub Desktop ហើយសាកល្បងម្តងទៀត)!")
            sys.exit(push_rc)
        print(f"\n🎉 Push ទៅ GitHub ជោគជ័យ ១០០%! អ្នកប្រើប្រាស់អាចទាញយក v{new_ver} ក្នុង Tool បានភ្លាមៗ!")
        print(f"   • Manifest: {GITHUB_MANIFEST_URL}")
        print(f"   • Package : {GITHUB_UPDATE_ZIP_URL}")


if __name__ == "__main__":
    main()

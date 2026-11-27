import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
OUTPUT_DIR = ROOT_DIR / "release_output"
UPDATER_PY = ROOT_DIR / "core" / "updater.py"
CONFIG_FILE = ROOT_DIR / "updater_config.json"
VERSION_INFO_TXT = ROOT_DIR / "version_info.txt"


def read_current_version() -> str:
    if UPDATER_PY.exists():
        content = UPDATER_PY.read_text(encoding="utf-8")
        m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', content)
        if m:
            return m.group(1)
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if cfg.get("app_version"):
                return cfg["app_version"]
        except Exception:
            pass
    return "1.3.0"


def bump_version(ver: str) -> str:
    nums = [int(n) for n in re.findall(r"\d+", (ver or "1.0.0").strip())]
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


def update_version_in_files(new_ver: str):
    # 1. Update core/updater.py
    if UPDATER_PY.exists():
        text = UPDATER_PY.read_text(encoding="utf-8")
        text = re.sub(r'APP_VERSION\s*=\s*["\'][^"\']+["\']', f'APP_VERSION = "{new_ver}"', text)
        UPDATER_PY.write_text(text, encoding="utf-8")

    # 2. Update updater_config.json
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    cfg["app_version"] = new_ver
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Update version_info.txt
    if VERSION_INFO_TXT.exists():
        try:
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
        except Exception:
            pass


def create_update_zip(output_zip: Path, version_json_str: str = "") -> int:
    exclude_dirs = {
        "data", "build", "dist", "installer_output", "release_output",
        "__pycache__", ".agents", ".git", ".venv", "venv", ".idea", ".vscode"
    }
    exclude_exts = {
        ".pyc", ".db", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".mp3",
        ".docx", ".log", ".tmp", ".iss"
    }

    if output_zip.exists():
        output_zip.unlink()

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(ROOT_DIR):
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
            rel_root = Path(root).relative_to(ROOT_DIR)

            for f in files:
                if f.startswith(".") or f.endswith(".bat"):
                    # keep tools and config, skip root batch files from packaging
                    if f in ("PUSH_UPDATE_TO_GDRIVE.bat", "BUILD_INSTALLER.bat", "BUILD_EXE.bat"):
                        continue
                p = Path(root) / f
                if f == "version.json" and version_json_str:
                    continue
                if p.suffix.lower() in exclude_exts:
                    continue

                arcname = str(rel_root / f) if str(rel_root) != "." else f
                zf.write(p, arcname)

        if version_json_str:
            zf.writestr("version.json", version_json_str)

    return output_zip.stat().st_size


def find_google_drive_desktop_paths():
    candidates = []
    # Check drive letters from D: to Z:
    for letter in "GHIJKLMNOPQRSTUVWXYZDEF":
        drive = Path(f"{letter}:/")
        if drive.exists():
            my_drive = drive / "My Drive"
            if my_drive.exists():
                candidates.append(my_drive)
            elif (drive / "Other computers").exists() or (drive / ".shortcut-targets-by-id").exists():
                candidates.append(drive)

    # Check Local User Profile
    user_home = Path.home()
    if (user_home / "Google Drive").exists():
        candidates.append(user_home / "Google Drive")
    if (user_home / "My Drive").exists():
        candidates.append(user_home / "My Drive")

    return candidates


def ask_input(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
        return val if val else default
    except EOFError:
        return default


def main():
    os.chdir(ROOT_DIR)
    print("=" * 72)
    print("  🚀 Ai Summarai Studio — កញ្ចប់អាប់ដេតកូដ និងបញ្ជូនទៅ Google Drive")
    print("=" * 72)

    current_ver = read_current_version()
    suggested_ver = bump_version(current_ver)

    print(f"\n[1] កំណែបច្ចុប្បន្ន (Current Version)៖ v{current_ver}")
    new_ver = ask_input(f"    បញ្ចូលលេខ Version ថ្មី [ចុច Enter យក v{suggested_ver}]: ", suggested_ver)

    default_changelog = "• កែសម្រួលប្រព័ន្ធទូទៅ បង្កើនល្បឿន និងបន្ថែមមុខងារថ្មី"
    print(f"\n[2] កំណត់ត្រាការកែប្រែ (Changelog)៖")
    changelog = ask_input(f"    បញ្ចូលចំណុចកែប្រែ [ចុច Enter យកលំនាំដើម]: ", default_changelog)

    print(f"\n[3] កំពុងធ្វើបច្ចុប្បន្នភាពលេខកំណែ v{new_ver} ក្នុងកូដ...")
    update_version_in_files(new_ver)
    print("    [OK] បានកែប្រែលេខ Version រួចរាល់។")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUTPUT_DIR / "AiSummarai_Update.zip"
    manifest_path = OUTPUT_DIR / "version.json"

    # Read existing config for Google Drive Link
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    gdrive_link = cfg.get("gdrive_update_url", "")
    gdrive_file_id = cfg.get("gdrive_file_id", "")

    FOLDER_1 = "https://drive.google.com/file/d/11zKNTE0xfSriEYaGW6woZkP1Ia8zKL5i/view?usp=sharing"
    FOLDER_2 = "https://drive.google.com/drive/folders/1fwjroNGJM6FVgHE-kArT615RjDb8vhYE?usp=sharing"

    print(f"\n[4] គោលដៅ Google Drive Folders សម្រាប់ Upload កូដ៖")
    print(f"    [1] Folder 1 (Updates): {FOLDER_1}")
    print(f"    [2] Folder 2:           {FOLDER_2}")
    if gdrive_link and gdrive_link not in (FOLDER_1, FOLDER_2):
        print(f"    [Custom Link]:          {gdrive_link}")

    choice = ask_input("    ជ្រើសរើស Folder [ចុច 1 យក Folder 1, ចុច 2 យក Folder 2, ឬចុច Enter យកលំនាំដើម 1]: ", "1")
    target_browser_url = FOLDER_2 if choice.strip() == "2" else FOLDER_1

    if not gdrive_link or choice in ("1", "2"):
        gdrive_link = target_browser_url
        from core.updater import InAppPackageUpdater
        gdrive_file_id = InAppPackageUpdater.extract_gdrive_id(target_browser_url)
        cfg["gdrive_update_url"] = gdrive_link
        cfg["gdrive_file_id"] = gdrive_file_id

    # Create version manifest data
    download_url = f"https://drive.google.com/uc?export=download&id={gdrive_file_id}" if gdrive_file_id else gdrive_link
    manifest_data = {
        "version": new_ver,
        "release_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "download_url": download_url,
        "gdrive_file_id": gdrive_file_id,
        "changelog": changelog,
    }
    manifest_json_str = json.dumps(manifest_data, indent=2, ensure_ascii=False)

    print(f"\n[5] កំពុងវេចខ្ចប់កូដថ្មីទៅជា '{zip_path.name}'...")
    file_size_bytes = create_update_zip(zip_path, version_json_str=manifest_json_str)
    file_size_kb = round(file_size_bytes / 1024, 1)
    file_size_mb = round(file_size_kb / 1024, 2)
    print(f"    [OK] វេចខ្ចប់ជោគជ័យ! ទំហំកញ្ចប់កូដ៖ {file_size_kb} KB ({file_size_mb} MB)")

    manifest_data["file_size_kb"] = file_size_kb
    manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
    cfg["app_version"] = new_ver
    cfg["manifest_url"] = manifest_data["download_url"] if manifest_data["download_url"] else ""
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"    [OK] បានបង្កើត '{manifest_path.name}' រួចរាល់។")

    # [6] Check for Google Drive Desktop Sync
    gdrive_sync_paths = find_google_drive_desktop_paths()
    copied_to_desktop_sync = False
    if gdrive_sync_paths:
        print(f"\n[6] បានរកឃើញ Google Drive Desktop នៅក្នុងកុំព្យូទ័រ៖")
        for idx, p in enumerate(gdrive_sync_paths, 1):
            print(f"    [{idx}] {p}")
        ask_sync = ask_input("    តើអ្នកចង់ចម្លងកញ្ចប់កូដចូល Google Drive នេះដោយស្វ័យប្រវត្តិដែរឬទេ? (Y/N, លំនាំដើម Y): ", "y").lower()
        if ask_sync in ("", "y", "yes"):
            target_folder = gdrive_sync_paths[0] / "AiSummarai_Updates"
            target_folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(zip_path, target_folder / zip_path.name)
            shutil.copy2(manifest_path, target_folder / manifest_path.name)
            print(f"    [OK] បានចម្លងទៅ៖ {target_folder} (Google Drive នឹង Sync ឡើង Cloud ភ្លាមៗ!)")
            copied_to_desktop_sync = True

    # [7] Final Instructions & Browser Helper
    print("\n" + "=" * 72)
    print("  ⭐ របៀប Upload ទៅ Google Drive ឲ្យ Link មិនប្រែប្រួល (Permanent Link):")
    print("=" * 72)
    print("  ១. លើកដំបូង៖")
    print(f"     • អូសឯកសារ '{zip_path.name}' ទៅទម្លាក់ក្នុង Google Drive របស់អ្នក")
    print("     • Right-click លើ File នោះ -> Share -> ជ្រើស Anyone with the link -> Copy Link")
    print("     • យក Link នោះមក Paste ចូល Tool (ឬ script នេះ) រួចចុច រក្សាទុក (Save)។")
    print("\n  ២. លើកក្រោយៗពេល Update កូដនៅទីនេះ៖")
    print("     • កុំលុប File ចាស់ ឬកុំ Upload ឯកសារថ្មីដាច់ដោយឡែកឡើយ!")
    print(f"     • គ្រាន់តែ Right-click លើ '{zip_path.name}' ក្នុង Google Drive")
    print("     • ជ្រើសរើស 'File information' -> 'Manage versions' (គ្រប់គ្រងកំណែ)")
    print(f"     • ចុច 'Upload new version' រួចរើសយកឯកសារ '{zip_path.name}' ថ្មី!")
    print("\n  ==> អត្ថប្រយោជន៍ដ៏អស្ចារ្យ៖")
    print("      • Google Drive Link និង File ID នឹងនៅដដែលជារៀងរហូត ១០០%!")
    print("      • អ្នកប្រើប្រាស់ Tool គ្រាន់តែចុច Update ក្នុង Tool គឺទទួលបានកូដថ្មីភ្លាម!")
    print("      • មិនបាច់ Download ឬដំឡើងកម្មវិធីថ្មីឡើងវិញទាល់តែសោះ!")
    print("=" * 72)

    # Open release folder in Explorer
    try:
        subprocess.Popen(f'explorer "{OUTPUT_DIR.resolve()}"')
    except Exception:
        pass

    if not copied_to_desktop_sync:
        ask_browser = ask_input(f"\nតើអ្នកចង់បើក Google Drive Folder ({target_browser_url.split('?')[0]}) ក្នុង Browser ឥឡូវនេះដែរឬទេ? (Y/N, លំនាំដើម Y): ", "y").lower()
        if ask_browser in ("", "y", "yes"):
            webbrowser.open(target_browser_url)

    print(f"\n🎉 រួចរាល់ ១០០%! ឯកសារអាប់ដេតស្ថិតនៅ៖ {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

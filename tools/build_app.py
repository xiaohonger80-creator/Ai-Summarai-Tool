#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ai Summarai — Automated Desktop App & Installer Builder
-------------------------------------------------------
Handles PyInstaller build, FFmpeg bundling, and Inno Setup 6 packaging cleanly in Python,
avoiding CMD batch file UTF-8 encoding/offset bugs completely.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def log(msg: str):
    print(f"[*] {msg}", flush=True)


def log_ok(msg: str):
    print(f"[OK] {msg}", flush=True)


def log_err(msg: str):
    print(f"[ERROR] {msg}", flush=True)


def main():
    app_root = Path(__file__).resolve().parent.parent
    os.chdir(str(app_root))

    # Configure stdout for UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 68, flush=True)
    print("  Ai Summarai Studio — Windows App & Installer Builder (.exe)", flush=True)
    print("=" * 68, flush=True)
    print(f"Folder: {app_root}\n", flush=True)

    py_exe = sys.executable
    log_ok(f"Using Python: {py_exe} ({sys.version.split()[0]})")

    # Step 1: Ensure PyInstaller is installed
    log("[1/4] Checking and installing PyInstaller & dependencies...")
    try:
        import PyInstaller
    except ImportError:
        log("PyInstaller not found, installing via pip...")
        subprocess.run([py_exe, "-m", "pip", "install", "--upgrade", "pyinstaller"], check=True)

    # Step 2: Clean previous builds
    log("[2/4] Cleaning previous build artifacts...")
    for folder_name in ("build", "dist", "installer_output"):
        p = app_root / folder_name
        if p.exists():
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception as e:
                print(f"Warning cleaning {folder_name}: {e}")

    # Step 3: Run PyInstaller
    log("[3/4] Building AiSummarai.exe with PyInstaller (Please wait 1-3 minutes)...")
    spec_file = app_root / "AiSummarai.spec"
    if not spec_file.exists():
        log_err(f"AiSummarai.spec not found in {app_root}!")
        return 1

    pyinstaller_cmd = [
        py_exe, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file)
    ]
    res = subprocess.run(pyinstaller_cmd)
    if res.returncode != 0:
        log_err(f"PyInstaller build failed with exit code {res.returncode}!")
        return res.returncode

    exe_path = app_root / "dist" / "AiSummarai" / "AiSummarai.exe"
    if not exe_path.exists():
        log_err("AiSummarai.exe was not created in dist/AiSummarai/!")
        return 1

    log_ok(f"Built successfully: {exe_path} ({round(exe_path.stat().st_size / (1024 * 1024), 2)} MB)")

    # Bundle FFmpeg and FFprobe binaries
    bin_dir = app_root / "dist" / "AiSummarai" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_found = False
    for bin_name in ("ffmpeg", "ffprobe"):
        bin_path = shutil.which(bin_name)
        if bin_path and Path(bin_path).exists():
            dest = bin_dir / f"{bin_name}.exe"
            shutil.copy2(bin_path, dest)
            log_ok(f"Bundled {bin_name} from: {bin_path}")
            ffmpeg_found = True

    if not ffmpeg_found:
        print("[!] Note: FFmpeg was not found in system PATH. App will look for it at runtime.")

    # Clean scripts inside dist that might trigger antivirus false-positives
    for bad_file in ("RUN_AISUMMARAI.vbs", "BUILD_INSTALLER.bat", "BUILD_EXE.bat", "main.py"):
        bf = app_root / "dist" / "AiSummarai" / bad_file
        if bf.exists():
            bf.unlink(missing_ok=True)

    # Sync fresh core, ui, and configs into dist/AiSummarai
    log("[3.5/4] Syncing core, ui, and configs into dist/AiSummarai...")
    d_core = app_root / "dist" / "AiSummarai" / "core"
    d_core.mkdir(parents=True, exist_ok=True)
    for cf in (app_root / "core").glob("*.py"):
        shutil.copy2(cf, d_core / cf.name)

    d_ui = app_root / "dist" / "AiSummarai" / "ui"
    d_ui.mkdir(parents=True, exist_ok=True)
    for uf in (app_root / "ui").glob("*.py"):
        shutil.copy2(uf, d_ui / uf.name)

    for cfg_f in ("version.json", "updater_config.json"):
        src_cf = app_root / cfg_f
        if src_cf.exists():
            shutil.copy2(src_cf, app_root / "dist" / "AiSummarai" / cfg_f)

    # Step 4: Build Inno Setup Installer if ISCC.exe is available
    log("[4/4] Building Setup Installer (.exe)...")
    iscc_candidates = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        os.path.expandvars(r"%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"),
    ]
    iscc_exe = None
    for cand in iscc_candidates:
        if Path(cand).exists():
            iscc_exe = cand
            break

    iss_file = app_root / "AiSummarai_Installer.iss"
    installer_built = False
    if iscc_exe and iss_file.exists():
        log(f"Compiling installer using Inno Setup: {iscc_exe}")
        out_dir = app_root / "installer_output"
        out_dir.mkdir(parents=True, exist_ok=True)
        res_iscc = subprocess.run([iscc_exe, str(iss_file)])
        if res_iscc.returncode == 0:
            installers = list(out_dir.glob("AiSummarai_Setup_*.exe"))
            if installers:
                newest = max(installers, key=lambda p: p.stat().st_mtime)
                size_mb = round(newest.stat().st_size / (1024 * 1024), 2)
                log_ok(f"Setup Installer built successfully: {newest.name} ({size_mb} MB)")
                installer_built = True

    # Step 5: Repack update zip for auto-updater
    try:
        if str(app_root) not in sys.path:
            sys.path.insert(0, str(app_root))
        from tools.sync_and_pack import main as pack_main
        log("[5/5] Packaging release update zip...")
        pack_main()
    except Exception as pe:
        print(f"Warning packaging update zip: {pe}")

    print("\n" + "=" * 68, flush=True)
    if installer_built:
        print("  🎉 Build ជោគជ័យ 100%! ឯកសារដំឡើងកម្មវិធីស្ថិតនៅក្នុង៖", flush=True)
        print(f"  {app_root / 'installer_output'}", flush=True)
    else:
        print("  🎉 Build ជោគជ័យ! កម្មវិធី AiSummarai.exe ស្ថិតនៅក្នុង៖", flush=True)
        print(f"  {exe_path}", flush=True)
    print("=" * 68 + "\n", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())

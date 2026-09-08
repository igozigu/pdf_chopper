"""
PyInstaller 단일 .exe 빌드 스크립트 (build_exe.py)
"""

import os
import shutil
import subprocess
import sys


def build():
    print("=" * 60)
    print("PDF Chopper - 단일 .exe 파일 빌드 시작")
    print("=" * 60)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist")
    build_dir = os.path.join(base_dir, "build")

    # PyInstaller 명령어 구성
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--clean",
        "--name",
        "PDF_Chopper",
        "--collect-all",
        "tkinterdnd2",
        "--collect-all",
        "pymupdf",
        "main.py",
    ]

    print(f"실행 명령: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=base_dir)

    if result.returncode != 0:
        print("\n[오류] 빌드 중 오류가 발생했습니다.")
        sys.exit(result.returncode)

    built_exe = os.path.join(dist_dir, "PDF_Chopper.exe")
    target_exe = os.path.join(base_dir, "PDF_Chopper.exe")

    if os.path.exists(built_exe):
        try:
            shutil.copy2(built_exe, target_exe)
            exe_size_mb = os.path.getsize(target_exe) / (1024 * 1024)
            print("\n" + "=" * 60)
            print("[성공] 빌드가 완료되었습니다!")
            print(f"* 실행 파일 위치: {target_exe}")
            print(f"* 파일 크기: {exe_size_mb:.1f} MB")
            print("=" * 60)
        except PermissionError:
            print("\n" + "=" * 60)
            print("[성공] dist 폴더에 빌드가 완료되었습니다!")
            print(f"* 빌드 파일: {built_exe}")
            print(f"* 알림: 기존 {target_exe}가 실행 중입니다. 프로그램을 종료한 뒤 다시 복사하세요.")
            print("=" * 60)
    else:
        print(f"[경고] 생성된 exe를 찾을 수 없습니다: {built_exe}")


if __name__ == "__main__":
    build()

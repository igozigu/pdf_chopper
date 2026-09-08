@echo off
chcp 65001 > nul
echo ========================================================
echo PDF Chopper 단일 실행파일(.exe) 빌드 시작
echo ========================================================
echo.

python build_exe.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [오류] 빌드에 실패했습니다. 위의 오류 메시지를 확인하세요.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================================
echo 빌드가 성공적으로 완료되었습니다!
echo 폴더에 생성된 PDF_Chopper.exe를 실행하세요.
echo ========================================================
pause

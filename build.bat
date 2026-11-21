@echo off
REM ═══════════════════════════════════════════════════════════
REM  Calculater — one-command build script
REM  Run this from the project folder:  build.bat
REM ═══════════════════════════════════════════════════════════

echo [1/4] Installing dependencies...
pip install -r requirements.txt

echo [2/4] Building Calculater.exe with PyInstaller...
pyinstaller ^
  --onefile ^
  --windowed ^
  --name Calculater ^
  --add-data ".env;." ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtWebEngineQuick ^
  --exclude-module PySide6.QtPdf ^
  --exclude-module PySide6.QtPdfWidgets ^
  --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtQml ^
  --clean ^
  --noconfirm ^
  main.py

echo [3/4] Copying .env next to the exe for API key...
copy /Y .env dist\.env 2>nul

echo [4/4] Done!
echo.
echo  Your executable is at:  dist\Calculater.exe
echo.
echo  IMPORTANT: Edit dist\.env and replace 'your_groq_api_key_here'
echo  with your real Groq API key, then run Calculater.exe.
echo.
pause

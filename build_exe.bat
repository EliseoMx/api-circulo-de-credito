@echo off
REM Compila api_circulo.py a un .exe de un solo archivo (dist\ApiCirculo.exe).
REM Requiere haber corrido antes: venv\Scripts\pip install -r requirements.txt pyinstaller

cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo No encuentro venv\Scripts\python.exe. Crea el entorno virtual primero:
    echo   python -m venv venv
    echo   venv\Scripts\pip install -r requirements.txt pyinstaller
    exit /b 1
)

venv\Scripts\python.exe -m PyInstaller --onefile --name ApiCirculo --distpath dist --workpath build --specpath . api_circulo.py

echo.
echo Listo: dist\ApiCirculo.exe
echo Antes de correrlo en otra maquina, copia junto al .exe: el archivo .env
echo (y opcionalmente las carpetas input\ / output\, si no quieres que las cree solas).

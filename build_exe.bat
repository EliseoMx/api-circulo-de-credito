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

REM Deja tambien el .bat de ejemplo junto al .exe, SOLO si dist\ApiCirculo.bat
REM no existe todavia (para no pisar uno que ya hayas llenado con tus
REM credenciales reales).
if not exist dist\ApiCirculo.bat (
    copy /Y ApiCirculo.bat.template dist\ApiCirculo.bat >nul
    echo Cree dist\ApiCirculo.bat a partir de la plantilla. Editalo y pon tus
    echo credenciales reales ahi ^(esa copia nunca se sube a git, dist\ esta en .gitignore^).
) else (
    echo dist\ApiCirculo.bat ya existia, no lo toque.
)

echo.
echo Listo: dist\ApiCirculo.exe y dist\ApiCirculo.bat
echo Edita dist\ApiCirculo.bat con tus credenciales y los datos de la persona,
echo o usa /INPUT_WS="input\*.json" para procesar uno o varios JSON.

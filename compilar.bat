@echo off
rem Gera dist\Vision.exe (arquivo unico, janela propria, sem console e sem Python no destino).
rem Cria um ambiente isolado em .venv-build com PyInstaller e Pillow.
setlocal
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py"
if not exist ".venv-build\Scripts\python.exe" (
  %PY% -m venv .venv-build || goto erro
  ".venv-build\Scripts\python.exe" -m pip install --quiet pyinstaller pillow av || goto erro
)
".venv-build\Scripts\python.exe" gerar_icone.py || goto erro
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --icon "%~dp0icone.ico" --add-data "%~dp0icone.ico;." --add-data "%~dp0espelha-input.jar;." --collect-all av --name Vision --distpath dist --workpath build --specpath build espelha_tela.py || goto erro
echo.
echo Pronto: %~dp0dist\Vision.exe
goto fim
:erro
echo.
echo FALHOU a geracao do exe.
:fim
pause

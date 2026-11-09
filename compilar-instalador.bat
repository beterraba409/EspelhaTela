@echo off
rem Gera dist\Vision-Setup-<versao>.exe com o Inno Setup 6, a partir do dist\Vision.exe.
rem Rode antes o compilar.bat. A versao vem de VERSAO no espelha_tela.py.
setlocal
cd /d "%~dp0"
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 nao encontrado. Instale com: choco install innosetup
  goto erro
)
if not exist "dist\Vision.exe" (
  echo dist\Vision.exe nao existe: rode o compilar.bat antes.
  goto erro
)
for /f "tokens=3" %%V in ('findstr /b /c:"VERSAO = " espelha_tela.py') do set "VERSAO=%%~V"
if not defined VERSAO goto erro
"%ISCC%" /Q /DVersao=%VERSAO% instalador\vision.iss || goto erro
echo.
echo Pronto: %~dp0dist\Vision-Setup-%VERSAO%.exe
goto fim
:erro
echo.
echo FALHOU a geracao do instalador.
:fim
pause

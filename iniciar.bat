@echo off
rem EspelhaTela - duplo clique abre a janela do visualizador (sem console).
rem Opcional: iniciar.bat [--serial XXXX] [--adb caminho]
setlocal
where pythonw >nul 2>nul && (start "" pythonw "%~dp0espelha_tela.py" %* & exit /b 0)
start "" pyw "%~dp0espelha_tela.py" %*

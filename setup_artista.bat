@echo off
rem
rem setup_artista.bat — Configura SamanTools en %%USERPROFILE%%\.nuke con
rem ACTUALIZACION AUTOMATICA via GitHub (repo publico).
rem El artista lo ejecuta UNA sola vez.
rem
rem Uso (en la maquina del artista, Windows):
rem   setup_artista.bat https://github.com/TU_ORG/saman-nuke-tools.git
rem
rem Despues de esto, cada vez que el artista abre Nuke el menu se actualiza solo.
rem
setlocal
set "REPO_URL=%~1"
if "%REPO_URL%"=="" (
  echo Uso: setup_artista.bat https://github.com/TU_ORG/saman-nuke-tools.git
  exit /b 1
)

set "NUKE_DIR=%USERPROFILE%\.nuke"
set "TOOLS_CHECKOUT=%NUKE_DIR%\SamanTools"
set "BOOTSTRAP=%~dp0bootstrap\menu.py"

echo ==^> Preparando SamanTools en %NUKE_DIR% ...
if not exist "%NUKE_DIR%" mkdir "%NUKE_DIR%"

rem 1) Bootstrap menu.py
if not exist "%NUKE_DIR%\menu.py" (
  copy /Y "%BOOTSTRAP%" "%NUKE_DIR%\menu.py" >nul
  echo     menu.py bootstrap instalado.
) else (
  echo     menu.py bootstrap ya presente.
)

rem 2) Checkout git del repo
if not exist "%TOOLS_CHECKOUT%\.git" (
  echo     Clonando el repo (primera vez)...
  git clone --depth 1 "%REPO_URL%" "%TOOLS_CHECKOUT%"
) else (
  echo     Checkout existente, actualizando...
  git -C "%TOOLS_CHECKOUT%" pull --ff-only --quiet
)

rem Inyectar REPO_URL correcto si el template tenia TU_ORG
powershell -NoProfile -Command "$p='%NUKE_DIR%\menu.py'; $c=Get-Content -Raw $p; $c=$c.Replace('https://github.com/TU_ORG/saman-nuke-tools.git','%REPO_URL%'); [IO.File]::WriteAllText($p,$c)" >nul 2>&1

echo.
echo ==^> LISTO. Reinicia Nuke.
echo     A partir de ahora SamanTools se actualiza automaticamente.
endlocal
@echo off
rem
rem Instala saman-nuke-tools en %USERPROFILE%\.nuke (Windows).
rem Uso:
rem   1) clona el repo
rem   2) cd saman-nuke-tools && install.bat
rem Esto copia menu.py y SamanTools\ a tu %USERPROFILE%\.nuke;
rem update = git pull + install.bat
rem
setlocal
set "REPO_DIR=%~dp0"
set "NUKE_DIR=%USERPROFILE%\.nuke"

echo ==^> Instalando saman-nuke-tools en %NUKE_DIR% ...
if not exist "%NUKE_DIR%" mkdir "%NUKE_DIR%"

if exist "%NUKE_DIR%\menu.py" (
  copy /Y "%NUKE_DIR%\menu.py" "%NUKE_DIR%\menu.py.bak.%DATE:~10,4%%DATE:~4,2%%DATE:~7,2%%TIME:~0,2%%TIME:~3,2%" >nul
  echo     (backup de menu.py previo creado)
)

if exist "%NUKE_DIR%\SamanTools" rmdir /S /Q "%NUKE_DIR%\SamanTools"
xcopy /E /I /Y "%REPO_DIR%\SamanTools" "%NUKE_DIR%\SamanTools" >nul
copy /Y "%REPO_DIR%\menu.py" "%NUKE_DIR%\menu.py" >nul

echo ==^> Listo. Reinicia Nuke para que cargue SamanTools.
echo ==^> (Alternativa sin copiar: setea NUKE_PATH=%REPO_DIR%)
endlocal

@echo off
rem ===================================================================
rem  Carene - installation des dependances (Windows)
rem
rem  Double-cliquez ce fichier une fois, sur chaque poste qui lance
rem  Carene depuis les sources (python main.py). Il verifie que Python
rem  est la, installe ou met a jour les paquets listes dans
rem  requirements.txt, puis controle que tout est en place.
rem  Sans accents dans ce fichier : la console Windows les mange.
rem ===================================================================
setlocal
cd /d "%~dp0"
echo.
echo === Carene : installation des dependances ===
echo     dossier : %CD%
echo.

rem --- Python : le lanceur "py" d'abord, sinon "python" dans le PATH
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY goto :nopython
%PY% --version >nul 2>&1 || goto :nopython
for /f "tokens=*" %%v in ('%PY% --version 2^>^&1') do echo     %%v

rem --- pip : present ? sinon on l'installe avec ensurepip
%PY% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo     pip manque : installation par ensurepip...
    %PY% -m ensurepip --upgrade
    if errorlevel 1 goto :echec
)

rem --- les paquets de requirements.txt
echo.
echo --- Installation / mise a jour des paquets (requirements.txt) ---
%PY% -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto :echec

rem --- controle final : le meme que celui du lancement
echo.
echo --- Controle ---
%PY% main.py --dependances
if errorlevel 1 goto :echec

echo.
echo Tout est en place. Lancez Carene avec :   %PY% main.py
echo.
pause
exit /b 0

:nopython
echo.
echo Python est introuvable sur ce poste.
echo Installez Python 3.10 ou plus depuis https://www.python.org/downloads/
echo (cochez "Add python.exe to PATH" a l'installation), puis relancez ce script.
echo.
pause
exit /b 1

:echec
echo.
echo L'installation n'a pas abouti : lisez les messages ci-dessus.
echo Sans acces a Internet, pip ne peut pas telecharger les paquets :
echo faites l'installation depuis un poste connecte, ou demandez le
echo dossier des paquets (pip download) pour une installation hors ligne.
echo.
pause
exit /b 1

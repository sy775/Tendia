@echo off
REM ==========================================================
REM   Tendia — Lanceur complet
REM
REM   1. Lance le pipeline complet (recup BOAMP/TED + DCE + LLM)
REM   2. Demarre le serveur web
REM   3. Ouvre le navigateur sur l'UI
REM ==========================================================

REM Se place dans le dossier du .bat (Python systeme, pas de venv)
cd /d "%~dp0"

REM ----- Etape 1 : Pipeline (recuperation + telechargement + extraction LLM)
echo.
echo =======================================================================
echo   TENDIA — Mise a jour des marches en cours
echo =======================================================================
echo.
echo Cette etape peut prendre 1 a 3 minutes selon le nombre de nouveaux marches.
echo Tu peux la suivre en direct ci-dessous.
echo.

python tendia_pipeline.py

REM ----- Etape 2 : Ouverture du navigateur (avec petit delai)
echo.
echo =======================================================================
echo   Demarrage de l'interface web
echo =======================================================================
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"

REM ----- Etape 3 : Demarrage du serveur Flask
python tendia_ui.py

REM Si le serveur s'arrete (Ctrl+C par exemple), on garde la fenetre ouverte
echo.
echo Tendia arrete. Appuyez sur une touche pour fermer.
pause >nul

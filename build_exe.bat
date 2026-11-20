@echo off
setlocal
cd /d "%~dp0"
title FT8SWX - gerar executavel

echo ============================================================
echo  FT8SWX - empacotando para Windows
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 goto :no_python

echo [1/5] Ambiente isolado (.venv)...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :fail_venv
)
set "PY=.venv\Scripts\python.exe"

echo [2/5] Dependencias...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install --quiet -r requirements.txt pyinstaller
if errorlevel 1 goto :fail_pip

echo [3/5] Biblioteca nativa (FT8)...
if exist "native\ft8shim.dll" goto :native_ok
echo       nao encontrada - instalando compilador portatil (zig)...
"%PY%" -m pip install --quiet ziglang
if errorlevel 1 echo       [aviso] falha ao instalar ziglang, tentando compiladores locais...
"%PY%" build_native.py
if exist "native\ft8shim.dll" goto :native_done
goto :fail_native

:native_ok
echo       OK - usando native\ft8shim.dll

:native_done
if exist "native\portaudio.dll" goto :pa_ok
echo       PortAudio sem WDM-KS (compatibilidade com FlexRadio DAX)...
"%PY%" -m pip install --quiet ziglang
"%PY%" build_portaudio.py
if not exist "native\portaudio.dll" goto :fail_native
:pa_ok
echo [4/5] Empacotando com PyInstaller (pode levar 1-3 min)...
"%PY%" -m PyInstaller --noconfirm --clean ft8swx.spec
if errorlevel 1 goto :fail_pyinstaller

echo [5/5] Gerando o ZIP para distribuir...
"%PY%" -c "import shutil; shutil.make_archive('FT8SWX-windows','zip','dist','FT8SWX')"

echo.
echo ============================================================
echo  PRONTO
echo    Pasta : dist\FT8SWX\FT8SWX.exe
echo    ZIP   : FT8SWX-windows.zip   (^<-- envie este para os amigos^)
echo ============================================================
echo.
pause
exit /b 0

:no_python
echo [ERRO] Python nao encontrado no PATH.
echo Instale o Python 3.10+ em https://www.python.org/downloads/windows/
echo e marque "Add python.exe to PATH".
goto :end

:fail_venv
echo [ERRO] Falha ao criar o ambiente isolado (.venv).
goto :end

:fail_pip
echo [ERRO] Falha ao instalar as dependencias.
echo Verifique a conexao com a internet e tente de novo.
goto :end

:fail_native
echo.
echo [ERRO] A biblioteca nativa (native\ft8shim.dll) nao foi gerada.
echo.
echo Duas causas comuns:
echo   1. Antivirus removeu o arquivo. Restaure em quarentena ou exclua
echo      a pasta do FT8SWX da verificacao, e rode este script de novo.
echo   2. Sem compilador. Instale o compilador portatil manualmente:
echo        .venv\Scripts\python -m pip install ziglang
echo        .venv\Scripts\python build_native.py
goto :end

:fail_pyinstaller
echo.
echo [ERRO] PyInstaller falhou. Veja as mensagens acima.
goto :end

:end
echo.
pause
exit /b 1

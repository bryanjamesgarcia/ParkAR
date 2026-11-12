@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
if not exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
  py -3.12 -m venv "%PROJECT_ROOT%.venv"
  if errorlevel 1 goto error
)
"%PROJECT_ROOT%.venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto pip_error
"%PROJECT_ROOT%.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error
"%PROJECT_ROOT%.venv\Scripts\python.exe" -m pip install -r "%PROJECT_ROOT%requirements.txt"
if errorlevel 1 goto error
if "%DJANGO_SECRET_KEY%"=="" set "DJANGO_SECRET_KEY=local-development-only-change-before-deploy"
set "DJANGO_DEBUG=1"
set "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1"
cd /d "%PROJECT_ROOT%backend"
"%PROJECT_ROOT%.venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 goto error
echo.
echo ParkAR is ready at http://localhost:8000
echo (To create an admin anytime, open another terminal and run: python backend\manage.py bootstrap_admin)
echo.
"%PROJECT_ROOT%.venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
goto end

:pip_error
echo Python created the virtual environment without pip, and ensurepip could not restore it.
echo Reinstall Python 3.12 from python.org and make sure pip is selected, then remove the .venv folder and run this file again.
pause
goto end

:error
echo Setup failed. Review the error above and check Python 3.12 and package access.
pause

:end
endlocal

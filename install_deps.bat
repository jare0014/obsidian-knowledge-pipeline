@echo off
cd /d "%~dp0"
echo 📦 Creating Knowledge Pipeline Virtual Environment (.venv)...
python -m venv .venv
if %errorlevel% neq 0 (
    echo ✗ Failed to create virtual environment. Make sure python is installed and in PATH.
    pause
    exit /b %errorlevel%
)

echo ⚙️ Upgrading pip...
.venv\Scripts\python -m pip install --upgrade pip --quiet

echo ⚙️ Installing Python dependencies...
.venv\Scripts\python -m pip install requests pypdf "notebooklm-py[cookies]" playwright --quiet
if %errorlevel% neq 0 (
    echo ✗ Failed to install dependencies.
    pause
    exit /b %errorlevel%
)

echo 🎭 Installing Playwright browser dependencies...
.venv\Scripts\python -m playwright install chromium
if %errorlevel% neq 0 (
    echo ✗ Playwright browser installation failed.
    pause
    exit /b %errorlevel%
)

echo ✓ Setup Complete! The virtual environment is ready.
echo Reload Obsidian to run the plugin.
pause

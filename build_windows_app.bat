@echo off
cd /d "%~dp0"
".venv\Scripts\pyinstaller.exe" --clean --noconfirm packaging\windows\voice-keyboard-tray.spec
echo.
echo Built app: %CD%\dist\VoiceKeyboard\VoiceKeyboard.exe
pause

@echo off
chcp 65001 >nul
rem BBong Capture 배포용 빌드: exe 폴더(dist\BBongCapture)를 만들고, Inno Setup이 있으면 설치 파일까지 만듭니다.
cd /d "%~dp0"
python -m pip install -r requirements.txt || goto :err
python -m pip install -U pyinstaller pyinstaller-hooks-contrib || goto :err
python installer\make_ico.py || goto :err
python -m PyInstaller --noconfirm --clean --windowed --name BBongCapture ^
  --icon installer\icon.ico ^
  --add-data "icon.png;." --add-data "pop.mp3;." --add-data "bbong.jpg;." --add-data "bbong_buddy.png;." --add-data "stickers;stickers" --add-data "PretendardVariable.ttf;." ^
  main.py || goto :err
echo.
echo [1/2] exe 빌드 완료: dist\BBongCapture\BBongCapture.exe
set ISCC=
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe") do if exist %%P set ISCC=%%~P
if defined ISCC (
  "%ISCC%" installer\BBongCapture.iss || goto :err
  echo [2/2] 설치 파일 완료: dist\BBongCapture-Setup.exe
) else (
  echo [2/2] Inno Setup 6 이 설치되어 있지 않아 설치 파일은 건너뜁니다. https://jrsoftware.org/isdl.php
)
exit /b 0
:err
echo 빌드 실패
exit /b 1

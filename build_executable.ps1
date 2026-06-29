Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Building AdaptiveUIEngine.exe" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Ensure dependencies are installed
Write-Host "`nInstalling build dependencies..." -ForegroundColor Yellow
pip install pyinstaller pystray pillow screeninfo

# Clean and build using spec file
Write-Host "`nRunning PyInstaller..." -ForegroundColor Yellow
python -m PyInstaller --clean main.spec

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "  Build complete!" -ForegroundColor Green
Write-Host "  Output: dist/AdaptiveUIEngine.exe" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

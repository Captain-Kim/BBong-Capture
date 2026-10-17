"""Text recognition via the OCR engine built into Windows 10/11 (Windows.Media.Ocr)."""
import os
import subprocess
import tempfile

_PS = r"""
param($Path)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $t.Wait(-1)
    $t.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
$bytes = [Text.Encoding]::UTF8.GetBytes($res.Text)
[Console]::OpenStandardOutput().Write($bytes, 0, $bytes.Length)
"""


def recognize(qimage) -> str:
    """Returns recognized text ('' if nothing found). Raises RuntimeError on engine failure."""
    tmpdir = tempfile.mkdtemp(prefix="bbc_ocr_")
    img_path = os.path.join(tmpdir, "in.png")
    ps_path = os.path.join(tmpdir, "ocr.ps1")
    img = qimage
    # The Windows OCR engine likes larger text; upscale small selections.
    if img.height() < 300:
        from PyQt5.QtCore import Qt
        f = max(2, 300 // max(1, img.height()))
        img = img.scaled(img.width() * f, img.height() * f, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    img.save(img_path, "PNG")
    with open(ps_path, "w", encoding="utf-8-sig") as f:
        f.write(_PS)
    try:
        cp = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ps_path, img_path],
            capture_output=True, timeout=60, creationflags=0x08000000)
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr.decode("utf-8", "replace").strip()[:300] or "OCR failed")
        return cp.stdout.decode("utf-8", "replace").strip()
    finally:
        for p in (img_path, ps_path):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass

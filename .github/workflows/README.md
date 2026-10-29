# SARBA GUI — Gaming Command Center

**Version:** 1.0.0-test  
**Target:** Windows 10/11 x64  
**Style:** SG red-and-black, cinematic game-launcher layout, glass-like panels, angular typography  
**Frame generation:** Removed by design.

## Included in this build source

- Red-and-black SARBA GUI dashboard with SG icon.
- Game launcher/library: auto-detects some common launchers and lets you add an `.exe` or `.lnk` shortcut; the library never uninstalls a game.
- Live CPU and RAM readings via `psutil`; NVIDIA utilization, temperature, memory, fan RPM/percentage and driver information via `nvidia-smi` when supported.
- Optional always-on-top overlay for FPS, GPU, CPU and RAM.
- FPS capture through the official PresentMon console helper. Select the actual game process (for MSI App Player, start with `HD-Player.exe`) and choose **Start FPS Capture**. FPS remains `N/A` until PresentMon reports frame events; SARBA does not invent an FPS value. Some games/drivers require running the app elevated to capture. The overlay is a normal always-on-top window and works best in borderless/windowed mode; exclusive-fullscreen games can cover third-party windows.
- GPU fan-speed controls through NVIDIA NVAPI where supported by the installed driver/card. Manual control can be rejected by some hardware/driver versions. The app caps the UI range at 35–100%, asks for confirmation, and attempts to restore automatic control when leaving a manual mode or closing the app. Check temperatures and the reported fan readings after applying.
- User TEMP folder cleanup, with an optional startup cleanup that removes files older than 24 hours. Manual cleanup confirms first and skips locked or in-use files. It does not clear Downloads, browser passwords, game data, or Windows system folders.
- Reversible performance shortcuts: Windows Game Mode, graphics settings, and an optional Windows High Performance power plan. No registry hacks or security-service disabling.
- Windows utility shortcuts, system report saving, persistent settings, normal installer/uninstaller, Start-menu shortcut and optional desktop shortcut.

## Important limits

This is the source/build kit, **not a precompiled Windows EXE**. The current execution environment is Linux, and network restrictions prevented installing PySide6 here, so the GUI has not been run in this workspace. Seven source-level unit tests pass, but Windows GUI runtime, setup compilation, FPS overlay against MSI App Player/Free Fire, and fan control on the user's GTX 1660 Super still need on-device verification. Build it on Windows 10/11 x64 or run the included GitHub Actions workflow from a repository containing these files. A successful compile alone does not prove live overlay compatibility on every game.

NVIDIA manual fan control is hardware/driver-dependent. The UI reports failures and does not claim success if NVAPI rejects the request. Do not use manual fan settings without monitoring temperature; the auto-control restore is best-effort.

## Build on Windows

1. Install 64-bit Python 3.10 or newer from python.org. Make sure `python` is on PATH.
2. Install Inno Setup 6 if you also want the conventional setup/uninstall EXE. The standalone app EXE can be built without Inno Setup.
3. Double-click `BUILD_SARBA_GUI.bat` or run `build\build_windows.ps1` from PowerShell.
4. The script installs dependencies, downloads the official PresentMon command-line helper from its GitHub Releases page, runs source tests, and packages `dist\SARBA-GUI.exe`. If Inno Setup is installed, it also creates `dist\SARBA-GUI-Setup.exe`.

The included `.github/workflows/build-windows.yml` uses a Windows runner to do the same, then uploads both EXEs as a workflow artifact. Copy this project to a repository you can write to before running that workflow.

## FPS measurement notes

PresentMon's console application supports filtering capture by process name and writing frame data to CSV. SARBA derives its FPS reading from the most recent captured frame intervals. Reference: [PresentMon console application README](https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md).

## Fan control notes

NVIDIA documents a GPU Cooler interface for retrieving and setting cooler/fan levels, but supported operations depend on hardware and drivers. Reference: [NVIDIA NVAPI GPU Cooler Interface](https://docs.nvidia.com/nvapi/group__gpucooler.html).

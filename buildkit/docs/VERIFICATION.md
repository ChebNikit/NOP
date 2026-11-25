# Verification status (NOP 1.3 build kit)

Honest labels: **verified (Linux sandbox)**, **verified statically**, **not verified**. The evidence column below was gathered on Linux or by static checks. **Update for 1.2:** the author reports that on Windows the kit built the installer, the installer installed, and the application runs and works. Items that were not individually confirmed (Windows 10 LTSC 1809, upgrade over an older version, per-machine install, uninstall, each conversion engine) keep their *not verified* label.

| Area | Status | Evidence |
|---|---|---|
| Application: cache of converter check (0 processes on 2nd start, invalidation when a tool changes) | verified (Linux sandbox) | process spy: 1st start 2 FFmpeg calls, 2nd start 0; cache load ≈1 ms |
| `--nop-warm-capabilities`, `--nop-selftest` | verified (Linux sandbox, also in a frozen build) | exit codes and JSON report; correct failure when libmpv is absent |
| PyInstaller freeze of the app with the generated spec (hidden imports, yt-dlp extractors, EJS, certifi, PyMuPDF, PyQt6 multimedia) | verified (Linux sandbox, PyQt6 6.11.0) | frozen binary imports every package and runs FFmpeg checks |
| Python lock (24 wheels, win_amd64 cp313, SHA-256) | verified statically | hashes computed from the real PyPI files; unit test checks every entry and that each import of the app is covered |
| mpv, FFmpeg, ffprobe, deno, 7zr pins | verified statically | files downloaded, SHA-256 recorded; deno hash equals the vendor's `.sha256sum`; DLL/EXE are x64 PE; libmpv-2.dll (official mpv-player LGPL build) has no import of vulkan-1.dll (PE import table checked) |
| Kit unit tests (downloads, hash mismatch, retries, zip-slip, lock, spec, manifest, template messages, package info page and manifest, art, Inno detection and download URL regression) | verified (Linux sandbox) | 56 tests passed (kit 1.3, source NOP_1_3.py) |
| `stage0.ps1` | verified statically | parses with PowerShell 7.7; version selection logic exercised; NuGet/python.org are not reachable from the sandbox, so the download itself is **not verified** |
| Equalizer APO 1.4.2 embedded in the installer (pin, build stops on failure, `[Files]`/`[Code]` wiring, finish-page message, silent-install skip) | verified statically (unit tests: lock pin, template wiring, offline failure mode); **real download, Inno compile and APO installation not verified** | The SHA-256 and URL were taken from the earlier kit's `component_config.json`; SourceForge is not reachable from the sandbox, so the first Windows build is the first real check of the pin. A mismatch stops the build and prints the expected and actual hash. |
| Conversion engines (LibreOffice, Inkscape, Calibre, Blender): fetching with `winget download`, MSI unpacking, folder layout, real conversions in the self-test | **not verified on Windows** | Layout matches NOP's own search paths (unit test); the self-test conversion code ran on Linux only for LibreOffice (txt→pdf passed); MSI administrative unpacking and the winget route were not run here; the other three engines were not available in the sandbox |
| Inno Setup script (`NOP_Setup.iss.template`) | **verified statically; Windows compile not verified** | GitHub Releases URL for Inno Setup 6.7.4; Authenticode allowlist includes the current publisher; already-installed Inno 6 is accepted when Windows exposes only its major version. Dark styling is preprocessor-gated for 6.6+, `WizardBackColor` for 6.7+, and older compatible 6.x uses the legacy fallback. An actual ISCC compile still needs to be run on Windows. |
| Old Windows 10 1809 LTSC with an old GPU driver | **not verified** (error reproduced by the author with the old libmpv; fix untested) | the earlier shinchiro libmpv build imports `vkGetPhysicalDeviceProperties2` from vulkan-1.dll (PE import table) and failed to load there; the official LGPL build used now does not import vulkan-1.dll. Re-check on that PC after rebuilding |
| libmpv playing real audio/video on Windows | **not verified** | `--nop-selftest` initialises libmpv on the build machine; real playback must be confirmed by a person |
| Windows 10 LTSC 2019 (1809), other Win10, Win11 | **not verified** | Build-time checks run on the build machine only. Qt 6.11 is officially specified for newer Windows 10 builds; 1809 is best effort |
| Install / upgrade / uninstall, associations, per-machine install, winget engines | **not verified** | `--verify-install` automates a silent install-test on a test PC |
| Code signing | not performed | optional via `NOP_SIGN_CMD` |

## Suggested first-run checklist (Windows)

1. `BUILD_NOP_SETUP.bat` → read `dist\BUILD_REPORT.json` (payload self-test must say `ok`).
2. `BUILD_NOP_SETUP.bat --verify-install` on a test machine/VM.
3. Install on a clean Windows 10 LTSC 2019 VM and a Windows 11 VM; run `Check_NOP.bat`; play one video and one audio file; download a clip; convert a video; toggle the equalizer.
4. Start NOP twice and confirm in Process Explorer that the second start launches no `ffmpeg`/`soffice`/`inkscape`.


## Оформление мастера (тема «Классическая»)

Картинки мастера генерируются `build/make_art.py` (проверено на Linux: файлы создаются, размеры верные). На Inno Setup 6.6+ мастер использует встроенную тёмную тему (кнопки, чек-листы, выбор типа установки, заголовок, граница окна и стандартные диалоги); начиная с 6.7+ цвет страницы задаётся `WizardBackColor`. Для более ранних совместимых 6.x сохранено прежнее оформление через `InitializeWizard`. Сам установщик на Windows ещё не компилировался и визуально не проверялся.


Порядок страниц: приветствие NOP 1.3 → штатные страницы выбора типа/компонентов, папки и задач → отдельная страница «Состав установки» → штатное подтверждение и установка. Страница состава создаётся после `wpSelectTasks` как самостоятельная страница мастера, а не как элемент/панель страницы выбора компонентов.

## Выбор конвертеров и папка в меню «Пуск» (добавлено позже)

* Проверено на Linux: модульные тесты (в т. ч. что в шаблоне есть все четыре конвертера с проверкой `Check: EngineSelected`, значки `{group}`, ярлык удаления, все `CustomMessage` на двух языках), расчёт размеров `engine_size_defines`.
* **Не проверено:** компиляция `NOP_Setup.iss` в Inno Setup и работа мастера на Windows (страница «Конвертеры файлов», сворачивание списка, страница папки «Пуск», флаг «не создавать», `/ENGINES=` при тихой установке, запоминание выбора при обновлении, удаление ярлыков). Исходники Inno Setup сверены на предмет используемых функций и событий, но реальный запуск возможен только на Windows: `BUILD_NOP_SETUP.bat --from-step 10`, затем `--verify-install` на тестовом ПК.

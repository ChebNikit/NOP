## NOP 1.1

**Installer:** `NOP_Setup.exe` — Windows 10 (1809+) / Windows 11, x64. Windows 7 and 8 are not supported.
Check the download with `NOP_Setup.exe.sha256` (`certutil -hashfile NOP_Setup.exe SHA256`).

### What's new
- **Download a time range** — cut a clip while downloading (HH:MM:SS, colons are added automatically).
- **Cookies from the browser** as an alternative to `cookies.txt`, with a priority setting.
- **Video bitrate and frame-rate settings** for downloads (auto / manual, kbit/s or Mbit/s).
- **Single instance** — starting NOP again hands the files to the running window; new setting "Opening files": current window / new window.
- **Preset list** in the equalizer scrolls smoothly and can be driven from the keyboard.
- **Faster start** — the converter capability check runs once at install time and is cached; a normal launch no longer starts FFmpeg, LibreOffice and other tools.
- **New installer** (BuildKit 1.1): self-provisioning build with hash-pinned downloads, a self-test of the frozen app (libmpv, FFmpeg, ffprobe, conversions) before the installer is created, a dark wizard in the player's Classic theme, Russian and English.

### Notes
- **Equalizer APO 1.4.2** is included and installed by `NOP_Setup.exe` when it is not already present (for the *Whole device* equalizer mode). Windows asks for administrator permission and the APO wizard asks you to choose your audio device; a silent install skips it.
- The installer has not been signed, so Windows SmartScreen may show a warning on first run.
- Full source and build kit: [`buildkit/`](https://github.com/ChebNikit/NOP/tree/main/buildkit).

---

## NOP 1.1 (по-русски)

**Установщик:** `NOP_Setup.exe` — Windows 10 (1809+) / Windows 11, x64. Windows 7 и 8 не поддерживаются.
Проверка загрузки: `NOP_Setup.exe.sha256` (`certutil -hashfile NOP_Setup.exe SHA256`).

### Что нового
- **Скачивание фрагмента по времени** (ЧЧ:ММ:СС, двоеточия подставляются сами).
- **Cookies из браузера** как альтернатива `cookies.txt`, с настройкой приоритета.
- **Настройки битрейта и частоты кадров видео** при скачивании (авто / вручную, кбит/с или Мбит/с).
- **Один экземпляр программы** — повторный запуск передаёт файлы в уже открытое окно; новая настройка «Открытие файлов»: в текущем окне / в новом.
- **Список пресетов эквалайзера** плавно прокручивается и управляется с клавиатуры.
- **Быстрый запуск** — проверка конвертеров выполняется один раз при установке и кэшируется; обычный запуск больше не стартует FFmpeg, LibreOffice и другие программы.
- **Новый установщик** (BuildKit 1.1): сборка без предварительной установки чего-либо, закреплённые по хэшу загрузки, самопроверка собранной программы (libmpv, FFmpeg, ffprobe, конвертации) до создания установщика, тёмный мастер в классической теме плеера, русский и английский.

### Примечания
- **Equalizer APO 1.4.2** входит в установщик и ставится им, если APO ещё нет (режим эквалайзера «Всё устройство»). Windows запросит права администратора, а мастер APO попросит выбрать устройство звука; при тихой установке APO пропускается.
- Установщик не подписан, поэтому Windows SmartScreen может показать предупреждение при первом запуске.
- Исходники и набор для сборки: [`buildkit/`](https://github.com/ChebNikit/NOP/tree/main/buildkit).

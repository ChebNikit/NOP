## NOP 1.2

**Installer:** `NOP_Setup.exe` — Windows 10 (1809+) / Windows 11, x64. Windows 7 and 8 are not supported.
Check the download with `NOP_Setup.exe.sha256` (`certutil -hashfile NOP_Setup.exe SHA256`).

### What's new
- **Video mode** in Settings → Playback: Auto, Quality, Performance and Smooth motion. In Auto, 4K and HDR video use lighter processing, so 4K movies no longer drop frames on laptop GPUs.
- **Playback:** larger read buffer for high-bitrate 4K files, mpv is polled less often, unused built-in scripts are disabled.
- **Fixed** a crash when sorting the file list by the "Type" column.
- **Downloads:** YouTube, Rutube and VK Video are one entry ("YouTube \ Rutube \ VK Video"); the site is detected from the link (channel/profile, playlist, single video). New "Other links" entry (any site supported by yt-dlp); "Video download" is now "Direct video link". Extra explanatory texts removed from the Spotify settings.
- **Log file** `nop.log` (errors, library versions, video playback statistics); `crash.log` now separates launches.
- **Transcode panel redesigned after HandBrake:** tabs Summary, Video, Size, Filters, Audio, Subtitles, More.
  - Video: AV1 (SVT-AV1), constant/variable frame rate, two-pass, tune, profile, level, 10-bit, extra encoder options, hardware decoding.
  - Size and filters: custom size, crop and auto-crop, rotate/flip, deinterlace, detelecine, denoise, sharpen, deblock, black-and-white.
  - Audio: "All" / "None" buttons; per-track codec, bitrate, channels, sample rate, gain, title and default flag. Audio is copied without re-encoding by default.
  - Subtitles: see which tracks the file has; keep, set default or burn in; add external .srt/.ass/.vtt with offset and encoding.
  - More: clip range, chapters and metadata, file title, MP4 web optimisation.
  - Queue: add folders, reorder, remove selected/finished, context menu, per-file progress. Custom presets can be saved and deleted.
- **Drag and drop** from the file manager into the transcode and conversion queues, "Play also from" (folders only) and the cookies.txt field.
- **Track list:** the play button starts the selected track; the playing track is highlighted with an icon.
- Help and English translation updated.

### Notes
- **Equalizer APO 1.4.2** is included and installed by `NOP_Setup.exe` when it is not already present (for the *Whole device* equalizer mode). Windows asks for administrator permission and the APO wizard asks you to choose your audio device; a silent install skips it.
- The installer has not been signed, so Windows SmartScreen may show a warning on first run.
- Full source and build kit: [`buildkit/`](https://github.com/ChebNikit/NOP/tree/main/buildkit).

---

## NOP 1.2 (по-русски)

**Установщик:** `NOP_Setup.exe` — Windows 10 (1809+) / Windows 11, x64. Windows 7 и 8 не поддерживаются.
Проверка загрузки: `NOP_Setup.exe.sha256` (`certutil -hashfile NOP_Setup.exe SHA256`).

### Что нового
- **Режим видео** в настройках («Воспроизведение»): Авто, Качество, Производительность и Плавное движение. В режиме «Авто» для 4K и HDR включается облегчённая обработка, поэтому 4K-фильмы на ноутбучных видеокартах больше не теряют кадры.
- **Воспроизведение:** увеличен буфер чтения для 4K-файлов с высоким битрейтом, mpv реже опрашивается, отключены неиспользуемые встроенные скрипты.
- **Исправлен** вылет при сортировке списка файлов по колонке «Тип».
- **Загрузки:** YouTube, Rutube и VK Video объединены в один пункт («YouTube \ Rutube \ VK Video»), площадка определяется по ссылке (канал или профиль, плейлист, одно видео). Новый пункт «Другие ссылки» (любой сайт, который поддерживает yt-dlp); «Загрузка видео» переименована в «Прямая ссылка на видео». Из настроек Spotify убраны лишние пояснительные тексты.
- **Журнал работы** `nop.log` (ошибки, версии библиотек, статистика воспроизведения видео); в `crash.log` добавлены разделители запусков.
- **Панель перекодирования переделана по образцу HandBrake:** вкладки «Сводка», «Видео», «Размер», «Фильтры», «Звук», «Субтитры», «Ещё».
  - Видео: AV1 (SVT-AV1), постоянная и переменная частота кадров, двухпроходное кодирование, tune, профиль, уровень, 10 бит, дополнительные параметры кодировщика, аппаратное декодирование.
  - Размер и фильтры: свой размер, обрезка и автообрезка, поворот и отражение, деинтерлейс, детелесин, шумоподавление, резкость, деблокинг, чёрно-белое изображение.
  - Звук: кнопки «Все» и «Ни одной»; у каждой дорожки свои кодек, битрейт, каналы, частота, усиление, название и «по умолчанию». Звук по умолчанию копируется без перекодирования.
  - Субтитры: видно, какие дорожки есть в файле; можно сохранить, сделать «по умолчанию» или вшить; внешний .srt/.ass/.vtt со сдвигом и кодировкой.
  - Ещё: фрагмент видео, главы и метаданные, название файла, оптимизация MP4 для веба.
  - Очередь: добавление папок, порядок, удаление выбранных и обработанных, меню по правой кнопке, процент по каждому файлу. Свои пресеты можно сохранять и удалять.
- **Перетаскивание** из проводника в очереди перекодирования и конвертации, в «Воспроизведение также из» (только папки) и в поле cookies.txt.
- **Список треков:** кнопка воспроизведения запускает выбранный трек, играющий трек выделен цветом и значком.
- Справка и английский перевод обновлены.

### Примечания
- **Equalizer APO 1.4.2** входит в установщик и ставится им, если APO ещё нет (режим эквалайзера «Всё устройство»). Windows запросит права администратора, а мастер APO попросит выбрать устройство звука; при тихой установке APO пропускается.
- Установщик не подписан, поэтому Windows SmartScreen может показать предупреждение при первом запуске.
- Исходники и набор для сборки: [`buildkit/`](https://github.com/ChebNikit/NOP/tree/main/buildkit).

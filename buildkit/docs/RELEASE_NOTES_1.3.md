## NOP 1.3

Установщик: NOP_Setup.exe — Windows 10 (1809+) / Windows 11, x64.  
Проверка загрузки: certutil -hashfile NOP_Setup.exe SHA256

### Что изменилось

**Воспроизведение**
- «Повтор трека» работает и для треков, которых нет в списке.
- Случайный порядок идёт кругами: каждый трек играет один раз за круг, поэтому одни треки больше не выпадают слишком часто, а другие не пропадают. «Предыдущий трек» возвращает к тому, что играло перед этим.
- Окно «Свойства» для mp3 больше не лагает: обложка и очень длинные теги (например, тексты песен) показываются кратко, окно строится за один проход.
- Полноэкранный режим: убраны тёмные прямоугольники по бокам от кнопок управления, углы панели скруглены без острых тёмных уголков.

**Загрузки**
- Панель настройки скрывает то, что не влияет на результат: в режиме «Только видео» нет настроек звука, в режиме «Только аудио» нет настроек видео.
- Для «Только аудио» добавлен выбор формата: как в источнике, MP3, WAV, FLAC, M4A / AAC, OGG Vorbis, Opus. Формат, качество и частота дискретизации применяются за один проход FFmpeg.
- Двойной щелчок по скачанному файлу в панели «Очередь и прогресс» открывает его в списке треков и запускает.
- Исправлено сжатие строк в панели загрузки при переключении режима, если NOP был закрыт в режиме «Только аудио».

**Проводник и файлы**
- Исправлено обрезание текста при вводе имени новой папки и при переименовании.
- Удаление в проводнике и удаление трека переносят файл в корзину, а не стирают его насовсем.
- Подтверждение удаления и контекстное меню проводника (переименовать, удалить, показать скрытые файлы, создать папку) в стиле NOP.

**Оформление**
- Единый стиль окон подтверждения и ввода: шапка в цвете темы, ниже один цвет, иконка NOP, только кнопки «Свернуть» и «Закрыть», размер по содержимому. Применён к удалению, замене файла, сохранению и удалению пресетов (эквалайзер, цветокоррекция, перекодирование), добавлению и удалению частоты в эквалайзере и коротким уведомлениям.
- Удаление пресета в эквалайзере, цветокоррекции и перекодировании теперь спрашивает подтверждение.
- Выпадающие списки: выделение в цвет темы (полупрозрачная полоса) вместо системного синего; выделение текста в полях усиления эквалайзера тоже в цвет темы.
- Обводка при наведении на списки выбора больше не пропадает после открытия и закрытия списка и после щелчка по пустому месту окна.

**Установщик**
- Конвертеры выбираются по одному. В «Полной» и «Выборочной» установке после выбора типа открывается страница «Конвертеры файлов» с раскрывающимся разделом «Конвертация файлов»: LibreOffice (документы, таблицы, презентации), Inkscape (векторная графика), Calibre (электронные книги), Blender (3D-модели). Рядом с каждой программой указан размер. Выбор запоминается и предлагается снова при обновлении. Для тихой установки: `NOP_Setup.exe /SILENT /ENGINES=libreoffice,blender` (`all` — все, `none` — ни одной).
- Папка в меню «Пуск»: на отдельной странице можно изменить её название или отказаться от неё совсем. В папке: NOP, «Удалить NOP», «NOP - проверка установки», «NOP на GitHub». Одиночный ярлык NOP, который создавали прежние установщики, при обновлении удаляется.
- Чистое обновление: папки `_internal`, `mpv` и `licenses` перед копированием заменяются целиком, поэтому файлы прежней версии не могут подхватиться новой. Конвертеры, настройки в `%APPDATA%\YamiFM` и всё вне папки программы не затрагиваются.

**Прочее**
- Версия 1.3 в окне и справке, английский перевод новых сообщений.

---

## NOP 1.3 (English)

Installer: NOP_Setup.exe — Windows 10 (1809+) / Windows 11, x64.  
Verify the download: certutil -hashfile NOP_Setup.exe SHA256

### What's changed

**Playback**
- "Repeat track" now works for tracks that are not in the track list.
- Shuffle plays in rounds: every track is played once per round, so some tracks no longer come up too often while others are skipped. "Previous track" goes back to what was playing before.
- The Properties window for mp3 files no longer lags: cover art and very long tags (such as lyrics) are shown in short form, and the window is built in one pass.
- Fullscreen mode: removed the dark rectangles beside the control buttons; the panel corners are rounded without sharp dark corners.

**Downloads**
- The settings panel hides what does not affect the result: no audio settings in "Video only", no video settings in "Audio only".
- "Audio only" gets a format choice: as in source, MP3, WAV, FLAC, M4A / AAC, OGG Vorbis, Opus. Format, quality and sample rate are applied in a single FFmpeg pass.
- Double-clicking a finished download in the "Queue and progress" panel opens it in the track list and starts playing it.
- Fixed squeezed rows in the download panel when switching mode if NOP was closed in "Audio only" mode.

**File picker and files**
- Fixed clipped text when typing a new folder name or renaming.
- Deleting in the file picker and deleting a track now move the file to the Recycle Bin instead of erasing it for good.
- The delete confirmation and the file picker context menu (rename, delete, show hidden files, new folder) use the NOP style.

**Appearance**
- One common style for confirmation and input windows: a header in the theme color, one color below it, the NOP icon, only Minimize and Close buttons, size fitted to the content. Used for delete, replace file, saving and deleting presets (equalizer, color correction, transcoding), adding and removing a frequency in the equalizer, and short notices.
- Deleting a preset in the equalizer, color correction and transcoding now asks for confirmation.
- Drop-down lists: the highlight uses the theme color (a semi-transparent bar) instead of the system blue; text selection in the equalizer gain fields also uses the theme color.
- The hover outline on drop-down boxes no longer disappears after a list is opened and closed or after clicking an empty spot in the window.

**Installer**
- Converters are chosen one by one. With the "Full" and "Custom" setup types, a "File converters" page follows the type page, with an expandable "File conversion" section: LibreOffice (documents, spreadsheets, presentations), Inkscape (vector graphics), Calibre (e-books), Blender (3D models). Each program shows its size. The choice is remembered and offered again on update. For a silent install: `NOP_Setup.exe /SILENT /ENGINES=libreoffice,blender` (`all` — everything, `none` — nothing).
- Start Menu folder: a separate page lets you rename it or skip it entirely. The folder holds NOP, "Uninstall NOP", "NOP - installation check" and "NOP on GitHub". The single NOP shortcut created by earlier installers is removed on update.
- Clean update: the `_internal`, `mpv` and `licenses` folders are replaced as a whole before copying, so no file of the previous version can be picked up by the new one. Converters, settings in `%APPDATA%\YamiFM` and anything outside the program folder are left alone.

**Other**
- Version 1.3 in the window and Help; English translation of the new messages.

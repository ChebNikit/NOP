"""Functional checks using the real compiled Window, MpvPlayer and ConverterWorker.

The report explicitly separates automation from manual acceptance. It is never
a substitute for clean-VM installation or listening/visual inspection.
"""
from __future__ import annotations
import datetime
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import zipfile


def make_fixtures(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'документ.txt').write_text('NOP offline conversion test. Проверка конвертации.\n', 'utf-8')
    (folder / 'таблица.csv').write_text('Name,Value\nNOP,42\n', 'utf-8')
    (folder / 'субтитры.srt').write_text('1\n00:00:00,000 --> 00:00:01,500\nNOP test\n', 'utf-8')
    (folder / 'вектор.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#e5bddf"/></svg>', 'utf-8')
    (folder / 'модель.obj').write_text('o NOP\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n', 'ascii')
    with zipfile.ZipFile(folder / 'книга.epub', 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr('OEBPS/content.opf', '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">nop-test</dc:identifier><dc:title>NOP</dc:title><dc:language>en</dc:language></metadata><manifest><item id="page" href="page.xhtml" media-type="application/xhtml+xml"/><item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine toc="toc"><itemref idref="page"/></spine></package>')
        z.writestr('OEBPS/page.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>NOP</title></head><body><h1>NOP offline test</h1></body></html>')
        z.writestr('OEBPS/toc.ncx', '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="nop-test"/></head><docTitle><text>NOP</text></docTitle><navMap><navPoint id="p" playOrder="1"><navLabel><text>NOP</text></navLabel><content src="page.xhtml"/></navPoint></navMap></ncx>')
    with zipfile.ZipFile(folder / 'презентация.odp', 'w') as z:
        z.writestr('mimetype', 'application/vnd.oasis.opendocument.presentation')
        z.writestr('META-INF/manifest.xml', '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.presentation"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
        z.writestr('content.xml', '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" office:version="1.2"><office:body><office:presentation><draw:page draw:name="NOP"><draw:frame svg:x="1cm" svg:y="1cm" svg:width="15cm" svg:height="5cm"><draw:text-box><text:p>NOP offline test</text:p></draw:text-box></draw:frame></draw:page></office:presentation></office:body></office:document-content>')


def run_app_checks(ns, report):
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Functional checks must run inside Windows NOP.exe')
    if not os.environ.get('NOP_VALIDATION_PROFILE'):
        raise RuntimeError('Refusing to run functional checks in the normal user profile')
    if os.environ.get('NOP_CONVERTER_AUDIT') == '1':
        from converter_validation import run_converter_checks
        return run_converter_checks(ns, report)
    app = ns['QApplication'].instance()
    root = Path(sys.executable).resolve().parent
    report = Path(report).resolve()
    result = {'ok': False, 'status': 'проверено на Windows/ВМ',
        'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'windows': {'platform': platform.platform(), 'build': sys.getwindowsversion().build,
                    'machine': platform.machine()}, 'checks': [],
        'manual_checks': [
            'Install on clean LTSC 2019 build 17763 without Python, FFmpeg, Edge or WebView2',
            'Listen to audio; visually inspect real video, all themes, DPI, fullscreen and color correction',
            'Track order, repeat, shuffle, playlist editing, drag selection and every file-dialog button',
            'Download a single file, playlist and channel on YouTube, TikTok and Instagram; Spotify authorization and matching',
            'Equalizer APO device binding, UAC denial, test signal, enable/disable/revert and reboot',
            'GPU encoder availability on NVIDIA, Intel and AMD hardware; damaged/missing DLLs and access-denied folders',
            'Settings and playback position after a full process restart',
            'Upgrade, reinstall, uninstall, preservation of personal media and settings',
            'Every supported export format and each per-track option; long jobs, ETA and interruption while encoding',
        ]}
    win = None

    def write():
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')

    def wait_for(condition, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.02)
        raise RuntimeError('Timed out waiting for the requested application state')

    def checkpoint(name, function):
        result['stage'] = name
        write()
        try:
            detail = function()
            result['checks'].append({'name': name, 'ok': True, 'status': 'проверено на Windows/ВМ', 'detail': str(detail)})
        except Exception as error:
            result['checks'].append({'name': name, 'ok': False, 'status': 'проверено на Windows/ВМ',
                'detail': ns['redact_diagnostic'](error), 'trace': ns['redact_diagnostic'](traceback.format_exc())})
        write()

    def media_command(args):
        process = subprocess.run([str(root / 'ffmpeg.exe'), '-hide_banner', '-v', 'error', '-y', *map(str, args)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if process.returncode:
            raise RuntimeError(process.stdout.decode('utf-8', 'replace')[-3000:])

    def probe(path):
        p = subprocess.run([str(root / 'ffprobe.exe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if p.returncode:
            raise RuntimeError(p.stderr.decode('utf-8', 'replace'))
        return json.loads(p.stdout)

    def convert(category, extension, source, folder, options=None, expect_failure=False):
        worker = ns['ConverterWorker']([source], category, extension, folder, video_options=options)
        events = []
        worker.job_status.connect(lambda row, text: events.append(str(text)))
        worker.start()
        try:
            wait_for(lambda: worker.isFinished(), timeout=120)
        except Exception:
            worker.request_stop()
            wait_for(lambda: worker.isFinished(), timeout=15)
            raise
        worker.wait(2000)
        app.processEvents()
        row = worker._row_results.get(0, {})
        if expect_failure:
            if worker.fail_count != 1 or row.get('state') != 'error':
                raise RuntimeError('Damaged input did not produce an error: ' + repr(row))
            return row
        if worker.ok_count != 1 or worker.fail_count or row.get('state') != 'done':
            raise RuntimeError('ConverterWorker failed: ' + repr(row))
        if not events:
            raise RuntimeError('ConverterWorker emitted no status updates')
        path = Path(row['path'])
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError('Converter produced no nonempty output')
        return path

    write()
    with tempfile.TemporaryDirectory(prefix='NOP проверка ') as temp:
        work = Path(temp)
        inputs, outputs = work / 'исходники с пробелами', work / 'результаты с пробелами'
        outputs.mkdir()
        try:
            make_fixtures(inputs)
            media_command(['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=15', '-f', 'lavfi', '-i',
                'sine=frequency=440:sample_rate=48000', '-t', '8', '-c:v', 'libx264', '-preset', 'ultrafast',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', inputs / 'видео NOP.mp4'])
            media_command(['-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000', '-t', '2', inputs / 'звук.wav'])
            image = ns['QImage'](64, 64, ns['QImage'].Format.Format_RGB32)
            image.fill(ns['QColor']('#e5bddf'))
            if not image.save(str(inputs / 'картинка.png')):
                raise RuntimeError('Qt could not create the PNG test input')
            (inputs / 'повреждённый.mp4').write_bytes(b'NOP deliberately invalid media')
            def capture_command(args, timeout=15, **options):
                process = subprocess.run(list(map(str, args)), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if process.returncode:
                    raise RuntimeError(process.stdout.decode('utf-8', 'replace')[-3000:])
                return process.stdout.decode('utf-8', 'replace')
            capabilities = ns['conversion_ffmpeg_capabilities'](capture_command)
            result['media_export_capabilities'] = []
            for category, formats in ns['CONVERSION_FFMPEG_PROFILES'].items():
                for extension, profile in formats.items():
                    reason = ''
                    try:
                        ns['conversion_require_codecs'](capabilities, *profile)
                    except RuntimeError as error:
                        reason = str(error)
                    result['media_export_capabilities'].append({'category': category, 'extension': extension,
                        'encoders_and_muxer_available': not bool(reason), 'reason': reason,
                        'scope': 'Engine capability query only; does not prove conversion of every input'})
            win = ns['Window']()
            win.show()
            wait_for(win.isVisible)

            def panels():
                keys = ['profile', 'controls', 'seek', 'tracks', 'size', 'equalizer', 'color',
                        'downloads', 'converter', 'transcode', 'download_info', 'settings', 'about']
                for key in keys:
                    win.set_panel_visible(key, True, save=False)
                    app.processEvents()
                    attr, widgets, _, _ = win._panel_spec(key)
                    if not getattr(win, attr) or any(w.isHidden() for w in widgets):
                        raise RuntimeError('Panel did not open: ' + key)
                    win.set_panel_visible(key, False, save=False)
                    app.processEvents()
                return '13 panel show/hide operations; visual layout and individual buttons still require manual tests'
            checkpoint('Panel open/close', panels)

            def mpv():
                win.player.force = 'mpv'
                win.play_file(inputs / 'видео NOP.mp4')
                try:
                    wait_for(lambda: win.player.active == 'mpv' and win.player.position() > 300
                             and win.player.duration() > 7000, timeout=20)
                except RuntimeError as error:
                    raise RuntimeError('mpv playback did not start: ' + win.player.mpv.load_error) from error
                win.player.pause()
                wait_for(lambda: win.player.mpv._get_flag('pause') is True)
                before = win.player.position()
                deadline = time.monotonic() + 0.3
                while time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.02)
                if abs(win.player.position() - before) > 150:
                    raise RuntimeError('Playback continued during pause')
                win.player.setPosition(4000)
                wait_for(lambda: abs(win.player.position() - 4000) < 600)
                if not win.player.set_playback_rate(1.5):
                    raise RuntimeError('Changing mpv playback speed failed')
                if abs((win.player.mpv._get_double('speed') or 0) - 1.5) > 0.01:
                    raise RuntimeError('mpv speed property did not change')
                win.player.set_volume(0.3)
                if abs((win.player.mpv._get_double('volume') or 0) - 30) > 0.5:
                    raise RuntimeError('mpv volume property did not change')
                win.player.set_playback_rate(1.0)
                win.player.play()
                wait_for(lambda: win.player.position() > 4200)
                win.player.pause()
                return 'Video decoded and clock advanced; pause, seek, resume, speed and volume properties verified. Audible sound needs a listener.'
            checkpoint('Real mpv playback and controls', mpv)

            def eq():
                if win.player.active != 'mpv':
                    raise RuntimeError('mpv unavailable')
                win.player.set_equalizer(True, [1] * 10, ns['EQ_PRESET_FREQUENCIES'])
                if 'equalizer' not in (win.player.mpv._get_string('af') or ''):
                    raise RuntimeError('mpv equalizer filter was not installed')
                win.player.set_equalizer(False, [0] * 10, ns['EQ_PRESET_FREQUENCIES'])
                return 'Local mpv filter enabled and disabled; APO requires separate device acceptance'
            checkpoint('Local equalizer filter', eq)

            def color():
                if win.player.active != 'mpv':
                    raise RuntimeError('mpv unavailable')
                params = dict(ns['COLOR_NEUTRAL'])
                params.update(ns['COLOR_PRESETS']['cinematic'][1])
                win.player.set_color(params)
                wait_for(lambda: bool(win.player.mpv._lut_path), timeout=30)
                value = win.player.mpv._get_string('options/target-lut') or ''
                if not value or win.player.mpv.load_error:
                    raise RuntimeError('GPU color LUT was not applied: ' + win.player.mpv.load_error)
                win.player.set_color(None)
                win.player.stop()
                win.play_file(inputs / 'звук.wav')
                wait_for(lambda: win.player.active == 'mpv' and win.player.position() > 100)
                win.player.stop()
                return 'Cinematic LUT generated and accepted by mpv; second audio file loaded. Visual correctness requires inspection.'
            checkpoint('Color LUT and file switching', color)

            cases = [
                ('Видео', 'webm', 'видео NOP.mp4'), ('Аудио', 'mp3', 'звук.wav'),
                ('Аудио', 'flac', 'звук.wav'), ('Аудио', 'opus', 'звук.wav'),
                ('Изображения', 'webp', 'картинка.png'), ('Субтитры', 'ass', 'субтитры.srt'),
                ('Документы', 'pdf', 'документ.txt'), ('Таблицы', 'xlsx', 'таблица.csv'),
                ('Презентации', 'pdf', 'презентация.odp'), ('Электронные книги', 'txt', 'книга.epub'),
                ('Векторная графика', 'png', 'вектор.svg'), ('3D-модели', 'glb', 'модель.obj'),
                ('Архивы', 'tar.gz', 'документ.txt')]
            for category, extension, filename in cases:
                def one(category=category, extension=extension, filename=filename):
                    dest = convert(category, extension, inputs / filename, outputs)
                    if category in ('Видео', 'Аудио', 'Изображения', 'Субтитры'):
                        if not probe(dest).get('streams'):
                            raise RuntimeError('ffprobe found no output streams')
                    if extension == 'pdf' and not dest.read_bytes().startswith(b'%PDF-'):
                        raise RuntimeError('Invalid PDF output')
                    if extension == 'xlsx':
                        with zipfile.ZipFile(dest) as z:
                            if 'xl/workbook.xml' not in z.namelist():
                                raise RuntimeError('Invalid XLSX output')
                    if extension == 'glb' and dest.read_bytes()[:4] != b'glTF':
                        raise RuntimeError('Invalid GLB output')
                    if extension == 'tar.gz':
                        with tarfile.open(dest) as z:
                            data = z.extractfile('документ.txt').read()
                            if data != (inputs / 'документ.txt').read_bytes():
                                raise RuntimeError('Archive round-trip differs from input')
                    return 'Real ConverterWorker output validated: ' + dest.name
                checkpoint('Conversion: ' + category + ' -> ' + extension, one)

            def transcode():
                options = {'encoder': 'CPU', 'video_codec': 'h264', 'resolution': '720p', 'no_upscale': True,
                           'quality_value': 26, 'preset': 'ultrafast', 'subtitle_mode': 'Без субтитров', 'audio_mode': 'Все дорожки'}
                dest = convert('Видео', 'mkv', inputs / 'видео NOP.mp4', outputs, options)
                info = probe(dest)
                video = next(s for s in info['streams'] if s['codec_type'] == 'video')
                if video['codec_name'] != 'h264' or video['width'] != 320 or video['height'] != 180:
                    raise RuntimeError('Transcode output codec/dimensions incorrect')
                return 'H.264 Matroska created through real worker; original small dimensions retained'
            checkpoint('Transcoding preset and resulting streams', transcode)
            checkpoint('Damaged media error path', lambda: convert('Видео', 'mkv', inputs / 'повреждённый.mp4', outputs, expect_failure=True))

            def cancel():
                folder = outputs / 'отмена'
                folder.mkdir()
                options = {'encoder': 'CPU', 'video_codec': 'h264', 'resolution': '2160p (4K)',
                           'no_upscale': False, 'quality_value': 22, 'preset': 'veryslow',
                           'subtitle_mode': 'Без субтитров', 'audio_mode': 'Без аудио'}
                worker = ns['ConverterWorker']([inputs / 'видео NOP.mp4'], 'Видео', 'mkv', folder, video_options=options)
                worker.start()
                try:
                    wait_for(lambda: getattr(worker, '_engine_pid_file', None) is not None
                             and worker._engine_pid_file.is_file(), timeout=20)
                finally:
                    worker.request_stop()
                    wait_for(lambda: worker.isFinished(), timeout=20)
                    worker.wait(2000)
                if not worker._completion_result[2] or any(folder.iterdir()):
                    raise RuntimeError('Cancelled task published an output or left temporary files')
                return 'CPU encoder child started, was cancelled and published no output'
            checkpoint('Active conversion cancellation', cancel)

            def settings():
                win.volume.setValue(37)
                win.save_settings()
                cfg = json.loads(Path(ns['CONFIG_PATH']).read_text('utf-8'))
                if cfg.get('volume') != 37:
                    raise RuntimeError('Saved volume does not match the UI value')
                loaded = ns['load_config']()
                if loaded.get('volume') != 37:
                    raise RuntimeError('Settings could not be reloaded')
                return 'Settings written and read in the isolated validation profile; a full process restart remains manual'
            checkpoint('Settings write/read', settings)
        except Exception as error:
            result['checks'].append({'name': 'Harness preparation', 'ok': False, 'status': 'проверено на Windows/ВМ',
                'detail': ns['redact_diagnostic'](error), 'trace': ns['redact_diagnostic'](traceback.format_exc())})
        finally:
            if win is not None:
                win.close()
                try:
                    wait_for(lambda: not win.isVisible(), timeout=20)
                except Exception as error:
                    result['checks'].append({'name': 'Application shutdown', 'ok': False, 'detail': str(error)})
            result['ok'] = bool(result['checks']) and all(row['ok'] for row in result['checks'])
            result['stage'] = 'finished'
            write()
    return 0 if result['ok'] else 1

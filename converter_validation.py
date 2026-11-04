"""Actual frozen ConverterWorker exports used to accept a smaller runtime.

Every configured external-engine target is attempted. Unsupported exports and
incomplete read-back checks are recorded separately, never called successful.
The mandatory basic conversions must pass even on the complete baseline.
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import sys
import tempfile
import time
import traceback
import zipfile

CATEGORIES = {'Документы': 'libreoffice', 'Таблицы': 'libreoffice', 'Презентации': 'libreoffice',
              '3D-модели': 'blender', 'Векторная графика': 'inkscape', 'Электронные книги': 'calibre'}
MANDATORY = {('Документы', 'pdf'), ('Таблицы', 'xlsx'), ('Презентации', 'pdf'),
             ('3D-модели', 'glb'), ('Векторная графика', 'png'), ('Электронные книги', 'txt')}
TOKEN = 'NOPCONVERT42'


def json_value(value):
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (set, tuple, list)):
        return [json_value(item) for item in sorted(value)] if isinstance(value, set) else [json_value(item) for item in value]
    return value


def pdf_signature(path):
    import fitz
    with fitz.open(path) as document:
        if not document.page_count:
            raise RuntimeError('Empty PDF')
        return {'kind': 'pdf', 'pages': [{'width': round(page.rect.width, 3), 'height': round(page.rect.height, 3),
                'text': ' '.join(page.get_text().split()),
                'pixels': hashlib.sha256(page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False).samples).hexdigest()}
                for page in document]}


def glb_signature(path):
    with path.open('rb') as stream:
        header = stream.read(20)
        if len(header) != 20:
            raise RuntimeError('Truncated GLB')
        magic, version, length, json_length, chunk_type = struct.unpack('<4sIIII', header)
        if magic != b'glTF' or version != 2 or length != path.stat().st_size or chunk_type != 0x4E4F534A:
            raise RuntimeError('Invalid GLB container')
        document = json.loads(stream.read(json_length))
    meshes = []
    for mesh in document.get('meshes', []):
        for primitive in mesh.get('primitives', []):
            accessor = document['accessors'][primitive['attributes']['POSITION']]
            meshes.append({'positions': accessor['count'], 'minimum': accessor.get('min'), 'maximum': accessor.get('max'),
                           'mode': primitive.get('mode', 4)})
    if not meshes:
        raise RuntimeError('GLB has no mesh positions')
    return {'kind': 'model', 'meshes': meshes}


def image_signature(ns, path):
    image = ns['QImage'](str(path))
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise RuntimeError('Image decoder rejected the output')
    image = image.convertToFormat(ns['QImage'].Format.Format_RGBA8888)
    pixels = image.constBits()
    pixels.setsize(image.sizeInBytes())
    return {'kind': 'image', 'width': image.width(), 'height': image.height(),
            'pixels': hashlib.sha256(bytes(pixels)).hexdigest()}


def check_zip(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise RuntimeError('Invalid output ZIP container')


def run_converter_checks(ns, report):
    if os.name != 'nt' or not getattr(sys, 'frozen', False) or not os.environ.get('NOP_VALIDATION_PROFILE'):
        raise RuntimeError('Converter acceptance requires the real isolated Windows NOP.exe')
    report = Path(report)
    profile = Path(os.environ['NOP_VALIDATION_PROFILE'])
    os.environ['CALIBRE_CONFIG_DIRECTORY'] = str(profile / 'calibre')
    os.environ['CALIBRE_CACHE_DIRECTORY'] = str(profile / 'calibre-cache')
    os.environ['INKSCAPE_PROFILE_DIR'] = str(profile / 'inkscape')
    app = ns['QApplication'].instance()
    result = {'ok': False, 'complete': False, 'scope': 'frozen Windows ConverterWorker',
              'status': 'проверено на Windows/ВМ', 'capabilities': {}, 'cases': [], 'checks': [], 'manual_checks': [],
              'windows': {'platform': platform.platform(), 'build': sys.getwindowsversion().build, 'machine': platform.machine()},
              'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def write():
        report.parent.mkdir(parents=True, exist_ok=True)
        # The controller tolerates an in-progress JSON read. Avoid rename while
        # a Windows reader holds a handle without FILE_SHARE_DELETE.
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')

    def wait(thread, seconds):
        deadline = time.monotonic() + seconds
        while not thread.isFinished() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        if not thread.isFinished():
            thread.request_stop()
            deadline = time.monotonic() + 20
            while not thread.isFinished() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.02)
            if not thread.isFinished():
                # Keep the live QObject referenced until the controller kills this process.
                ns.setdefault('_nop_validation_threads', []).append(thread)
                raise RuntimeError('Conversion did not stop after its timeout')
            raise RuntimeError('Conversion exceeded its timeout')
        thread.wait(2000)
        app.processEvents()

    serial = 0
    with tempfile.TemporaryDirectory(prefix='NOP conversion я (1) ') as temporary:
        work = Path(temporary)
        inputs = work / 'исходники с пробелами'
        outputs = work / 'результаты с пробелами'
        outputs.mkdir()

        def convert(category, suffix, source):
            nonlocal serial
            serial += 1
            folder = outputs / str(serial)
            folder.mkdir()
            worker = ns['ConverterWorker']([source], category, suffix, folder)
            events = []
            worker.job_status.connect(lambda row, text: events.append(str(text)))
            worker.start()
            wait(worker, 180)
            row = worker._row_results.get(0, {})
            if worker.ok_count != 1 or worker.fail_count or row.get('state') != 'done':
                raise RuntimeError('ConverterWorker: ' + repr(row))
            path = Path(row['path'])
            if not path.is_file() or not path.stat().st_size or not events:
                raise RuntimeError('No nonempty output or no status events')
            return path

        try:
            from nop_validation import make_fixtures
            make_fixtures(inputs)
            (inputs / 'документ.txt').write_text(TOKEN + ' Проверка конвертации.\n', 'utf-8-sig')
            (inputs / 'таблица.csv').write_text('Name,Value\n' + TOKEN + ',42\n', 'utf-8')
            (inputs / 'книга.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>NOP</title></head><body><p>' + TOKEN + ' Проверка конвертации.</p></body></html>', 'utf-8')
            # Replace text in the small, valid EPUB/ODP fixtures without copying an archive over itself.
            for name in ('книга.epub', 'презентация.odp'):
                path = inputs / name
                with zipfile.ZipFile(path) as original:
                    entries = [(info, original.read(info.filename).replace(b'NOP offline test', (TOKEN + ' Проверка конвертации.').encode('utf-8'))) for info in original.infolist()]
                with zipfile.ZipFile(path, 'w') as archive:
                    for info, data in entries:
                        archive.writestr(info, data)
            (inputs / 'вектор.svgz').write_bytes(gzip.compress((inputs / 'вектор.svg').read_bytes(), mtime=0))
            (inputs / 'модель.ply').write_text('ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n', 'ascii')
            probe = ns['ConversionCapabilityProbe'](None)
            responses = []
            probe.ready.connect(responses.append)
            probe.start()
            wait(probe, 180)
            if len(responses) != 1:
                raise RuntimeError('No converter-capability result')
            capability = responses[0]
            result['capabilities'] = {engine: json_value(capability.get(key)) for engine, key in
                                      (('libreoffice', 'office'), ('blender', 'model'), ('inkscape', 'vector'), ('calibre', 'ebook'))}
            result['capability_errors'] = json_value(capability.get('errors', {}))
            write()
            sources = {'Документы': inputs / 'документ.txt', 'Таблицы': inputs / 'таблица.csv',
                       'Презентации': inputs / 'презентация.odp', '3D-модели': inputs / 'модель.obj',
                       'Векторная графика': inputs / 'вектор.svg', 'Электронные книги': inputs / 'книга.epub'}
            alternates = {}

            def source_for(category, suffix):
                source = sources[category]
                if source.suffix.casefold() != '.' + suffix.casefold():
                    return source
                if category == '3D-модели':
                    return inputs / 'модель.ply'
                if category == 'Векторная графика':
                    return inputs / 'вектор.svgz'
                if category == 'Электронные книги':
                    return inputs / 'книга.html'
                if category not in alternates:
                    other = {'Документы': 'docx', 'Таблицы': 'xlsx', 'Презентации': 'pptx'}[category]
                    alternates[category] = convert(category, other, source)
                return alternates[category]

            def validate(category, path):
                check_zip(path)
                suffix = path.suffix.casefold()
                if category in ('Документы', 'Таблицы', 'Презентации'):
                    pdf = path if suffix == '.pdf' else convert(category, 'pdf', path)
                    signature = pdf_signature(pdf)
                    if TOKEN not in ' '.join(page['text'] for page in signature['pages']):
                        raise RuntimeError('Office output lost test document text')
                    if category == 'Документы' and 'Проверка' not in ' '.join(page['text'] for page in signature['pages']):
                        raise RuntimeError('Office output lost Cyrillic test document text')
                    return signature
                if category == 'Электронные книги':
                    text = path if suffix == '.txt' else convert(category, 'txt', path)
                    content = text.read_text('utf-8-sig')
                    if TOKEN not in content:
                        raise RuntimeError('E-book output lost test document text')
                    return {'kind': 'ebook', 'text': ' '.join(content.split())}
                if category == '3D-модели':
                    return glb_signature(path if suffix == '.glb' else convert(category, 'glb', path))
                if suffix in ('.png', '.jpg', '.jpeg', '.webp'):
                    return image_signature(ns, path)
                if suffix == '.pdf':
                    return pdf_signature(path)
                return image_signature(ns, convert(category, 'png', path))

            for category, engine in CATEGORIES.items():
                for suffix, label in ns['CONVERSION_FORMATS'][category]:
                    row = {'id': category + ' -> ' + suffix, 'engine': engine, 'category': category, 'extension': suffix,
                           'mandatory': (category, suffix) in MANDATORY, 'export_ok': False, 'ok': False,
                           'status': 'проверено на Windows/ВМ'}
                    result['stage'] = row['id']
                    write()
                    try:
                        dest = convert(category, suffix, source_for(category, suffix))
                        row['export_ok'] = True
                        row['output_bytes'] = dest.stat().st_size
                        row['signature'] = validate(category, dest)
                        row['ok'] = True
                    except Exception as error:
                        row['detail'] = ns['redact_diagnostic'](error)
                    result['cases'].append(row)
                    write()
            required = [row for row in result['cases'] if row['mandatory']]
            result['ok'] = len(required) == len(MANDATORY) and all(row['ok'] for row in required)
            result['complete'] = True
            result['stage'] = 'finished'
            result['note'] = 'All target exports attempted on fixed fixtures; baseline failures and read-back failures remain explicit. This does not prove arbitrary real-world documents or clean-OS installation.'
        except Exception as error:
            result['error'] = ns['redact_diagnostic'](error)
            result['trace'] = ns['redact_diagnostic'](traceback.format_exc())
        finally:
            write()
    return 0 if result['ok'] else 1

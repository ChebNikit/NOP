"""Exercise the uploaded converter logic with real Linux FFmpeg, without claiming Windows validation."""
import ast,base64,collections,copy,ctypes,datetime,hashlib,html,http.cookiejar,json,math,mimetypes,os,queue,random,re,secrets,shutil,signal,socket,stat,struct,subprocess,sys,tarfile,tempfile,threading,time,traceback,urllib.error,urllib.parse,urllib.request,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
WORK=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else Path(tempfile.mkdtemp(prefix='nop-linux-converter-'))
WORK.mkdir(parents=True,exist_ok=True)
if sys.platform!='linux':raise SystemExit('This harness is Linux-only and does not certify Windows')
class Signal:
 def __init__(self,*a):self.events=[]
 def emit(self,*a):self.events.append(a)
 def connect(self,*a):pass
class QThread:
 def __init__(self,*a):self.interrupted=False
 @staticmethod
 def currentThread():return QThread()
 def isInterruptionRequested(self):return self.interrupted
 def requestInterruption(self):self.interrupted=True
ns=dict(globals(),APP_DIR=WORK,FROZEN=False,DATA_DIR=WORK/'profile',__file__=str(ROOT/'NOP_1.0.py'),pyqtSignal=Signal,
        conversion_text=lambda ru,en:ru,ui_text=lambda ru,en:ru,redact_diagnostic=lambda x:str(x)[:5000])
source=ast.parse((ROOT/'NOP_1.0.py').read_text('utf-8'))
def nodes_names(n):
 if isinstance(n,(ast.FunctionDef,ast.ClassDef)):return [n.name]
 if isinstance(n,ast.Assign):return [t.id for t in n.targets if isinstance(t,ast.Name)]
 if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name):return [n.target.id]
 return []
byname={name:n for n in source.body for name in nodes_names(n)}
chosen=set()
def choose(name):
 if name in ns or name not in byname:return
 n=byname[name]
 if n.lineno in chosen:return
 chosen.add(n.lineno)
 for sub in ast.walk(n):
  if isinstance(sub,ast.Name) and isinstance(sub.ctx,ast.Load):choose(sub.id)
for name in ('ConverterWorker','CONVERSION_FFMPEG_PROFILES','CONVERSION_FORMATS'):choose(name)
selected=[n for n in source.body if getattr(n,'lineno',None) in chosen]
exec(compile(ast.Module(body=selected,type_ignores=[]),str(ROOT/'NOP_1.0.py'),'exec'),ns)
print('Loaded source nodes:',len(selected),flush=True)
def run_ff(args):
 subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*map(str,args)],check=True,timeout=30)
inputs=WORK/'исходники с пробелами';out=WORK/'результаты с пробелами';inputs.mkdir(exist_ok=True);out.mkdir(exist_ok=True)
run_ff(['-f','lavfi','-i','testsrc2=size=320x180:rate=15','-f','lavfi','-i','sine=frequency=330:sample_rate=48000','-t','2','-c:v','libx264','-preset','ultrafast','-c:a','aac',inputs/'видео.mp4'])
run_ff(['-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1',inputs/'звук.wav'])
(inputs/'субтитры.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nNOP test\n','utf-8')
(inputs/'исходник.txt').write_text('Проверка NOP\n','utf-8')
(inputs/'повреждённый.mp4').write_bytes(b'bad media')
cases=[('Видео','webm','видео.mp4',None),('Видео','mkv','видео.mp4',{'encoder':'CPU','video_codec':'h264','resolution':'720p','no_upscale':True,'quality_value':26,'preset':'ultrafast','subtitle_mode':'Без субтитров','audio_mode':'Все дорожки'}),('Аудио','mp3','звук.wav',None),('Аудио','flac','звук.wav',None),('Аудио','opus','звук.wav',None),('Субтитры','ass','субтитры.srt',None),('Архивы','tar.gz','исходник.txt',None),('Видео','mkv','повреждённый.mp4',None)]
results=[]
for category,ext,name,options in cases:
 worker=ns['ConverterWorker']([inputs/name],category,ext,out,video_options=options);worker.run();row=worker._row_results.get(0,{})
 expected=name.startswith('повреждённый')
 passed=(row.get('state')=='error' and worker.fail_count==1) if expected else row.get('state')=='done' and worker.ok_count==1
 if passed and not expected:
  dest=Path(row['path'])
  if category=='Архивы':
   with tarfile.open(dest) as z:passed=z.extractfile(name).read()==(inputs/name).read_bytes()
  else:
   proc=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(dest)],capture_output=True,timeout=20)
   info=json.loads(proc.stdout) if proc.returncode==0 else {};passed=bool(info.get('streams'))
   if options:passed=passed and next(s for s in info['streams'] if s['codec_type']=='video')['width']==320
 result={'name':category+' -> '+ext+' / '+name,'host':'Linux','windows_status':'не проверено','local_passed':passed,'row':row,'events':worker.job_detail.events[-2:]}
 results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
(WORK/'results.json').write_text(json.dumps({'scope':'Real source converter logic with a QThread/signal adapter on Linux; not Qt GUI or Windows EXE tests','ffmpeg':subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0],'cases':results},ensure_ascii=False,indent=2),'utf-8')
raise SystemExit(0 if all(r['local_passed'] for r in results) else 1)

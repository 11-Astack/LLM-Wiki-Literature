"""Bounded local records and Windows single-writer storage primitives."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile

class Rejected(ValueError):
    pass

def require(condition, code):
    if not condition:
        raise Rejected(code)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def digest(path):
    no_reparse(Path(path))
    return sha(Path(path).read_bytes())

def unique_pairs(pairs):
    result = {}
    for key,value in pairs:
        require(key not in result,'DUPLICATE_JSON_KEY')
        result[key]=value
    return result

def encode(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')

def loads(data):
    require(isinstance(data,bytes) and len(data)<=32*1024*1024 and not data.startswith(b'\xef\xbb\xbf'),'JSON_BYTES_INVALID')
    return json.loads(data.decode('utf-8'),object_pairs_hook=unique_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(Rejected('NONFINITE_JSON')))

def read_json(path):
    no_reparse(Path(path))
    return loads(Path(path).read_bytes())

def no_reparse(path):
    path=Path(path)
    require(not str(path).startswith(('\\\\','//')),'UNC_UNSUPPORTED')
    for current in (path,*path.parents):
        if os.path.lexists(current):
            info=current.lstat()
            require(not current.is_symlink() and not getattr(info,'st_file_attributes',0)&0x400,'REPARSE_PATH')
            if current.is_file(): require(info.st_nlink==1,'HARDLINK_PATH')

def valid_part(part):
    require(isinstance(part,str) and bool(part) and part not in ('.','..') and not part.endswith((' ','.')),'INVALID_PATH_PART')
    require(not any(ord(c)<32 or c in '<>:"\\|?*/' for c in part),'INVALID_PATH_CHAR')
    require(not re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',part,re.I),'RESERVED_PATH')

def safe(root, relative, must_exist=True):
    require(isinstance(relative,str) and relative and '\\' not in relative,'RELATIVE_PATH_REQUIRED')
    win=PureWindowsPath(relative)
    require(not win.drive and not win.is_absolute(),'ABSOLUTE_PATH_REJECTED')
    for part in relative.split('/'): valid_part(part)
    root=Path(root).absolute()
    no_reparse(root)
    path=root.joinpath(*relative.split('/'))
    no_reparse(path)
    require(path.resolve().is_relative_to(root.resolve()),'PATH_ESCAPE')
    if must_exist: require(path.is_file(),'FILE_MISSING')
    return path

def absolute(path, must_exist=True):
    path=Path(path).absolute()
    for part in path.parts:
        if part!=path.anchor: valid_part(part)
    no_reparse(path)
    if must_exist: require(path.exists(),'PATH_MISSING')
    return path

def _stage(path,data):
    no_reparse(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    no_reparse(path.parent)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',suffix='.tmp',dir=path.parent)
    temporary=Path(name)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    require(temporary.read_bytes()==data,'STAGING_READBACK_FAILED')
    return temporary

def put(path,data):
    path=absolute(path,False)
    require(isinstance(data,bytes),'BYTES_REQUIRED')
    if path.exists():
        require(path.read_bytes()==data,'IMMUTABLE_TARGET_CHANGED')
        return
    temporary=_stage(path,data)
    try:
        require(os.name=='nt','WINDOWS_REQUIRED')
        try: os.rename(temporary,path)
        except FileExistsError: require(path.read_bytes()==data,'IMMUTABLE_TARGET_CHANGED')
    finally:
        if temporary.exists(): temporary.unlink()
    require(path.read_bytes()==data,'WRITE_READBACK_FAILED')

def write_json_new(path,value):
    put(Path(path),encode(value))

def cas(path,old_bytes,new_bytes):
    path=absolute(path,False)
    temporary=_stage(path,new_bytes)
    try:
        require((path.read_bytes() if path.exists() else None)==old_bytes,'CAS_CONFLICT')
        os.replace(temporary,path)
        require(path.read_bytes()==new_bytes,'CAS_READBACK_FAILED')
    finally:
        if temporary.exists(): temporary.unlink()

@contextmanager
def writer(root):
    import msvcrt
    root=absolute(root)
    path=safe(root,'.system/writer.lock',False)
    path.parent.mkdir(exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0,2)==0: stream.write(b'\0');stream.flush()
        stream.seek(0)
        try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: raise Rejected('WRITER_BUSY') from None
        try: yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def ref(root,path):
    path=absolute(path)
    relative=path.relative_to(absolute(root)).as_posix()
    data=safe(root,relative).read_bytes()
    return {'path':relative,'sha256':sha(data),'bytes':len(data)}

def check_ref(root,item):
    require(isinstance(item,dict) and set(item)=={'path','sha256','bytes'},'REFERENCE_SCHEMA')
    require(isinstance(item['sha256'],str) and re.fullmatch('[0-9a-f]{64}',item['sha256']) is not None,'REFERENCE_HASH')
    require(type(item['bytes']) is int and item['bytes']>=0,'REFERENCE_SIZE')
    data=safe(root,item['path']).read_bytes()
    require(len(data)==item['bytes'] and sha(data)==item['sha256'],'REFERENCE_DRIFT')
    return data

def utcnow():
    return datetime.now(timezone.utc)

def parse_time(value):
    require(isinstance(value,str),'TIME_SCHEMA')
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(result.tzinfo is not None and result.utcoffset()==timedelta(0),'UTC_REQUIRED')
    return result

"""Small explicit trust boundaries; same-user OS tampering is outside this model."""
import hashlib
import json
import re
from pathlib import Path, PureWindowsPath

class Rejected(ValueError):
    pass

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejected('DUPLICATE_JSON_KEY')
        result[key] = value
    return result

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique_pairs)

def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')

def safe_child(root, relative):
    """Reject Windows aliases, UNC/ADS, traversal and links before I/O."""
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise Rejected('INVALID_RELATIVE_PATH')
    win = PureWindowsPath(relative)
    if win.is_absolute() or win.drive or ':' in relative:
        raise Rejected('ABSOLUTE_OR_ADS_PATH')
    parts = relative.split('/')
    for part in parts:
        if not part or part in ('.', '..') or part.endswith((' ', '.')) or any(ord(c) < 32 for c in part):
            raise Rejected('INVALID_PATH_PART')
        if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I):
            raise Rejected('WINDOWS_RESERVED_PATH')
        if any(c in part for c in '<>"|?*'):
            raise Rejected('INVALID_PATH_CHAR')
    root = Path(root)
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
            raise Rejected('REPARSE_ROOT')
    root = root.resolve()
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or (current.exists() and getattr(current.lstat(), 'st_file_attributes', 0) & 0x400):
            raise Rejected('REPARSE_PATH')
    current.resolve().relative_to(root)
    return current

"""Best-effort diagnostics that must never replace the original failure."""
import json
from pathlib import Path
import sys
import traceback


def cleanup(callback):
    original=sys.exc_info()[1]
    try:return callback()
    except Exception as secondary:
        if original is None:raise
        original.add_note('清理阶段另有异常（不覆盖原始错误）：'+traceback.format_exc())


def write(path, data):
    try:
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix(path.suffix+'.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)
        return True
    except Exception:
        print('诊断文件写入失败（原始异常保留）：'+traceback.format_exc(),file=sys.stderr)
        return False

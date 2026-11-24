#!/bin/zsh
set -eu
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
port="${STUDIO_PORT:-18772}"
url="http://127.0.0.1:$port"
if curl --noproxy '*' -fsS --max-time 1 "$url/api/identity" 2>/dev/null | grep -q jingliu-native-canvas; then
  open "$url/"
  exit 0
fi
for py in "${JINGLIU_PYTHON:-python3.12}" python3.13 python3.11 python3.10 python3; do
  if command -v "$py" >/dev/null && "$py" -c 'import sys; sys.exit(sys.version_info < (3,10))'; then break; fi
done
if ! "$py" -c 'import sys; sys.exit(sys.version_info < (3,10))' 2>/dev/null; then
  print '请先安装 Python 3.10 或以上版本，再打开本文件。https://www.python.org/downloads/macos/'
  exit 1
fi
runtime="${JINGLIU_DATA:-$HOME/Library/Application Support/Jingliu Canvas Studio}/runtime-$("$py" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ ! -x "$runtime/bin/python" ]]; then "$py" -m venv "$runtime"; fi
if [[ ! -f "$runtime/.requirements" ]] || ! cmp -s workbench/requirements.txt "$runtime/.requirements"; then
  "$runtime/bin/python" -m pip install --disable-pip-version-check -r workbench/requirements.txt
  cp workbench/requirements.txt "$runtime/.requirements"
fi
export PATH="$runtime/bin:$PATH"
"$runtime/bin/python" -B workbench/media_probe.py || print "FFprobe 未安装。视频导入、裁剪或抽帧前请安装 FFmpeg（含 ffprobe），再重新启动镜流。"
"$runtime/bin/python" -B workbench/studio_server.py &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for attempt in {1..60}; do
  kill -0 "$server_pid" 2>/dev/null || { wait "$server_pid"; exit 1; }
  if curl --noproxy '*' -fsS --max-time 1 "$url/api/identity" 2>/dev/null | grep -q jingliu-native-canvas; then
    if [[ "${JINGLIU_OPEN_BROWSER:-1}" == 1 ]]; then open "$url/"; fi
    break
  fi
  sleep .25
done
wait "$server_pid"

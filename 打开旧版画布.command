#!/bin/zsh
cd -- "${0:A:h}" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if curl -fsS --max-time 1 --noproxy '*' http://127.0.0.1:18771/api/identity 2>/dev/null | grep -q 'jingliu-canvas-v1'; then
  open 'http://127.0.0.1:18771/'
  exit
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3,9))' >/dev/null 2>&1; then
  print "请先安装 Python 3.9 或更新版本：https://www.python.org/downloads/macos/"
  read "?按回车退出"
  exit 1
fi
python3 -B classic.py || { print "启动失败。若默认端口已占用，可运行 python3 classic.py --port 18772"; read "?按回车退出"; }

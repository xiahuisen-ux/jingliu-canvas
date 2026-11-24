"""CLI entry point for the same edition as the macOS launcher."""
import argparse
import os
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=int(os.environ.get('STUDIO_PORT','18772')))
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('端口应为 1 至 65535')
    env={**os.environ,'STUDIO_PORT':str(args.port)}
    if args.no_browser:env['JINGLIU_OPEN_BROWSER']='0'
    launcher=Path(__file__).resolve().with_name('启动镜流.command')
    os.execve(launcher,[str(launcher)],env)

if __name__=='__main__':main()

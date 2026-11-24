import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT=Path(__file__).resolve().parent


def download(row):
    dest=ROOT/row['destination'];dest.parent.mkdir(parents=True,exist_ok=True)
    expected=row.get('expected_sha256')
    if dest.exists() and expected and hashlib.file_digest(dest.open('rb'),'sha256').hexdigest()==expected:return row
    temp=dest.with_suffix(dest.suffix+'.part')
    size=row.get('size',0)
    if size>100_000_000:
        parts=dest.parent/(dest.name+'.parts');parts.mkdir(exist_ok=True)
        chunk=32*1024*1024
        def get_range(start):
            end=min(size-1,start+chunk-1);part=parts/str(start)
            if part.exists() and part.stat().st_size==end-start+1:return part
            url=row['url']+'?download=true&range='+str(start)
            subprocess.run(['curl','-fSL','--retry','5','--retry-delay','2','--connect-timeout','20',
                            '--max-time','300','-H',f'Range: bytes={start}-{end}',url,'-o',str(part)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if part.stat().st_size!=end-start+1:raise RuntimeError('Range size mismatch: '+str(part))
            print(dest.name,end+1,'/',size,flush=True);return part
        starts=list(range(0,size,chunk))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(get_range,starts))
        with temp.open('wb') as stream:
            for start in starts:
                with (parts/str(start)).open('rb') as f:shutil.copyfileobj(f,stream)
        shutil.rmtree(parts)
    else:
        subprocess.run(['curl','-fSL','--retry','4','--connect-timeout','20','--max-time','300',row['url'],'-o',str(temp)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    with temp.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if expected and digest!=expected:raise RuntimeError('SHA256 mismatch: '+dest.name)
    if row.get('expected_sha256_prefix') and not digest.startswith(row['expected_sha256_prefix']):raise RuntimeError('SHA256 prefix mismatch: '+dest.name)
    if size and temp.stat().st_size!=size:raise RuntimeError('Size mismatch: '+dest.name)
    temp.replace(dest);print('Verified',dest.name,digest,flush=True)
    return {**row,'sha256':digest,'bytes':dest.stat().st_size}


if __name__=='__main__':
    rows=json.loads((ROOT/'downloads.json').read_text())
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(download,rows):results.append(result)
    (ROOT/'verified-models.json').write_text(json.dumps(results,indent=2))

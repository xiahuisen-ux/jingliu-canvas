import {build} from 'esbuild';
import fs from 'node:fs/promises';
await fs.mkdir('../studio/canvas-dist',{recursive:true});
await build({entryPoints:['src/main.jsx'],bundle:true,minify:true,sourcemap:false,outfile:'../studio/canvas-dist/app.js',loader:{'.svg':'dataurl'},define:{'process.env.NODE_ENV':'"production"'},legalComments:'eof'});
const notices=[];
for (const p of ['@xyflow/react','@xyflow/system','react','react-dom','esbuild']) {
  for (const file of ['LICENSE','LICENSE.md','LICENSE.txt']) {
    try {notices.push(`${p}\n${await fs.readFile('node_modules/'+p+'/'+file,'utf8')}`);break;}catch{}
  }
}
await fs.writeFile('../studio/canvas-dist/LICENSES.txt',notices.join('\n\n'));

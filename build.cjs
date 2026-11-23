const {buildSync}=require('esbuild');
buildSync({entryPoints:['src/main.jsx'],outfile:'web/app.js',bundle:true,minify:true,legalComments:'eof',define:{'process.env.NODE_ENV':'"production"'},target:['safari15','chrome100']});

#!/usr/bin/env node
// Export the app's ORIGINAL authored cards as a normalized comparison bank.
// Requires Node.js only. Runs a limited, static BANK literal in VM (never external input).
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const match=html.match(/\bconst BANK = ([\s\S]+?);\s+const EVENTS = /);
if(!match)throw new Error('Cannot find BANK in index.html');
const bank=vm.runInNewContext('(' + match[1] + ')',Object.create(null),{timeout:750});
const cards=[];
for(const [type,levels] of Object.entries(bank)){
  for(const [level,entries] of Object.entries(levels)){
    entries.forEach((entry,i)=>{
      const obj=typeof entry==='string'?{text:entry}:entry;
      cards.push({id:`base-${type}-${level}-${i}`,type,level:Number(level),text:obj.text,touch:!!obj.touch,source:'original-app',license:'Original authored content'});
    });
  }
}
const target=path.join(root,'data','base-question-bank.json');
fs.mkdirSync(path.dirname(target),{recursive:true});
fs.writeFileSync(target,JSON.stringify({version:1,cards},null,2)+'\n','utf8');
console.log(`Exported ${cards.length} authored cards to ${path.relative(root,target)}`);

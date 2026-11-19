import { mkdir, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
await mkdir(resolve(root,'www'),{recursive:true});
await copyFile(resolve(root,'../anna-app/index.html'),resolve(root,'www/index.html'));
console.log('Copied standalone JARVIS mobile-web preview into Android www/');

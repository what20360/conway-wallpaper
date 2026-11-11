import { readFile, writeFile } from 'node:fs/promises';

const editorUrl = new URL('../dist/index.html', import.meta.url);
const source = await readFile(editorUrl, 'utf8');
const marker = "const wallpaperMode=new URLSearchParams(location.search).get('wallpaper')==='1';";
if (!source.includes(marker)) throw new Error('Missing wallpaper mode declaration in dist/index.html');
await writeFile(new URL('../dist/wallpaper.html', import.meta.url), source.replace(marker, 'const wallpaperMode=true;'));
await writeFile(new URL('../project.json', import.meta.url), JSON.stringify({
  file: 'dist/wallpaper.html',
  title: '生命场 · 256',
  type: 'web',
  description: '16:9 满屏像素壁纸，256 个可写预设与256 个固定随机种子，仅保留被替换预设。',
  general: { properties: {} }
}, null, 2) + '\n');
console.log('Updated dist/wallpaper.html and project.json');

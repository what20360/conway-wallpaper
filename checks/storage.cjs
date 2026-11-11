const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const script=fs.readFileSync('dist/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1],lines=script.split('\n');
const W=256,H=180,L=W*H;
const names=['randomCells','packBits','unpackBits','putVar','readVar','sparseBytes','rleBytes','decodePayload','crc32','compress','decompress','encodePreset','decodePreset','encodeBank','decodeBank','sameCells','count'];
const scope={W,H,L,Uint8Array,Uint32Array,DataView,Blob,Response,CompressionStream,DecompressionStream,window:{CompressionStream,DecompressionStream},custom:{},backups:[]};vm.createContext(scope);
vm.runInContext([lines.find(l=>l.startsWith('const CRC_TABLE=')),...names.map(n=>lines.find(l=>l.startsWith('function '+n+'(')||l.startsWith('async function '+n+'(')))].join('\n'),scope);
const same=(a,b)=>assert.deepEqual(Array.from(a),Array.from(b));
(async()=>{
 assert.equal(scope.crc32(Buffer.from('123456789')),0xcbf43926);
 const hashes=new Set;for(let seed=0;seed<256;seed++){const a=scope.randomCells(seed);same(a,scope.randomCells(seed));hashes.add(crypto.createHash('sha256').update(a).digest('hex'));}assert.equal(hashes.size,256);assert.throws(()=>scope.randomCells(256));
 const empty=new Uint8Array(L),single=new Uint8Array(L);single[0]=1;
 const glider=new Uint8Array(L);for(const [x,y]of [[1,0],[2,1],[0,2],[1,2],[2,2]])glider[(y+88)*W+x+126]=1;
 const dense=scope.randomCells(42),full=new Uint8Array(L).fill(1),edge=new Uint8Array(L);edge[0]=edge[L-1]=1;
 const sizes={};for(const [name,cells]of Object.entries({empty,single,glider,dense,full,edge})){for(const codec of [0,1,2]){const payload=codec===0?scope.packBits(cells):codec===1?scope.sparseBytes(cells):scope.rleBytes(cells);same(scope.decodePayload(payload,codec),cells);}const file=await scope.encodePreset(cells,255,123);sizes[name]=file.length;const back=await scope.decodePreset(file);assert.equal(back.index,255);assert.equal(back.timestamp,123);same(back.cells,cells);assert.ok(file.length<=5778);const corrupt=file.slice();corrupt[corrupt.length-1]^=1;await assert.rejects(()=>scope.decodePreset(corrupt));}
 assert.equal(sizes.empty,18);assert.ok(sizes.glider<40);assert.ok(sizes.dense<5778);
 await assert.rejects(()=>scope.decodePreset(new Uint8Array(17)));
 scope.custom={1:await scope.encodePreset(glider,1,100),255:await scope.encodePreset(dense,255,200)};scope.backups=[{file:await scope.encodePreset(empty,1,0),replacedAt:123000}];
 const bank=await scope.encodeBank(),back=await scope.decodeBank(bank);assert.deepEqual(Object.keys(back.custom),['1','255']);assert.equal(back.backups.length,1);assert.equal(back.backups[0].replacedAt,123000);same((await scope.decodePreset(back.custom[255])).cells,dense);await assert.rejects(()=>scope.decodeBank(bank.subarray(0,-1)));
 const saved=scope.window;scope.window={};const plain=await scope.encodePreset(dense,7,0);scope.window=saved;same((await scope.decodePreset(plain)).cells,dense);
 // Saving and merging preserve only replaced presets, including atomic rollback.
 scope.state={cells:empty.slice(),mode:'preset',preset:1};scope.PATTERNS={glider:[[1,0],[2,1],[0,2],[1,2],[2,2]]};scope.decodedCache=new Map;scope.busy=false;scope.dirty=false;scope.page='bank';scope.backupIndex=0;scope.custom={};scope.backups=[];scope.notify=()=>{};scope.endStroke=()=>{};scope.refreshPreview=()=>{};scope.persistBank=async()=>{};
 vm.runInContext(['defaultCells','slotCells','savePreset','mergeBank'].map(n=>lines.find(l=>l.startsWith('function '+n+'(')||l.startsWith('async function '+n+'('))).join('\n'),scope);
 scope.state.cells=scope.defaultCells(1);await scope.savePreset();assert.equal(scope.backups.length,0);assert.equal(Object.keys(scope.custom).length,0);
 scope.state.cells[0]=1;await scope.savePreset();assert.equal(scope.backups.length,1);assert.equal(scope.count((await scope.decodePreset(scope.backups[0].file)).cells),5);
 await scope.savePreset();assert.equal(scope.backups.length,1);
 scope.state.cells.fill(0);assert.equal(scope.backups.length,1);await scope.savePreset();assert.equal(scope.backups.length,2);assert.equal(scope.custom[1].length,18);
 scope.persistBank=async()=>{throw Error('quota');};scope.state.cells[1]=1;await scope.savePreset();assert.equal(scope.backups.length,2);assert.equal(scope.custom[1].length,18);
 scope.persistBank=async()=>{};scope.custom={};scope.backups=[];await scope.mergeBank({custom:{8:await scope.encodePreset(empty,8,0)},backups:[]});assert.ok(scope.custom[8]);assert.equal(scope.backups.length,0);
 const fixtureDir=process.env.CONWAY_FIXTURE_DIR;if(fixtureDir){const path=require('node:path');fs.mkdirSync(fixtureDir,{recursive:true});fs.writeFileSync(path.join(fixtureDir,'glider-255.life'),await scope.encodePreset(glider,255,0));fs.writeFileSync(path.join(fixtureDir,'bank.lifebank'),bank);}
 console.log('PASS: 256 unique/reproducible seeds; all three codecs; compact round trips; corruption and truncation rejection; full bank round trip; uncompressed fallback.');console.log(JSON.stringify({bytes:sizes,bankBytes:bank.length}));
})().catch(e=>{console.error(e);process.exitCode=1;});

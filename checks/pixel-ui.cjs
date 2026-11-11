const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const script=fs.readFileSync('dist/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];new vm.Script(script);
assert.ok(!/\.(fillText|strokeText|drawImage)\(/.test(script));
assert.ok(!/function (record|snapshot|validateArchive|togglePower)\(/.test(script),'no interaction history or power feature');
assert.ok(!/state\.(power|events)/.test(script));
const glyphs=JSON.parse(script.match(/const GLYPHS=(.*);/)[1]);assert.ok(Object.keys(glyphs).every(c=>c.charCodeAt(0)<128));
const scope={innerWidth:1920,innerHeight:1080,devicePixelRatio:1,screenW:0,screenH:0,dpr:1,W:256,H:180,canvas:{},layout:{},bounds:{},dirty:false};vm.createContext(scope);vm.runInContext(script.split('\n').find(l=>l.startsWith('function resize(')),scope);
for(const [w,h]of [[1280,720],[1600,900],[1920,1080],[2560,1440],[3840,2160]]){scope.innerWidth=w;scope.innerHeight=h;scope.resize();assert.ok(Math.abs(scope.layout.sideX-w*.8)<1e-8);assert.ok(Math.abs(scope.bounds.x)<1e-8);assert.ok(Math.abs(scope.bounds.y)<1e-8);assert.ok(Math.abs(scope.bounds.s*256-w*.8)<1e-8);assert.ok(Math.abs(scope.bounds.s*180-h)<1e-8);assert.ok(Math.abs(scope.layout.y)<1e-8);assert.ok(scope.layout.safeBottom>=96);assert.ok(scope.layout.safeBottom>=h*.12);assert.ok(scope.layout.y+857*scope.layout.u<=h-scope.layout.safeBottom,'bottom controls stay above reserved blank area');}
const dateGlyphs=JSON.parse(script.match(/const DATE_GLYPHS=(.*);/)[1]);for(const digit of '0123456789'){assert.equal(dateGlyphs[digit].w,7);assert.equal(dateGlyphs[digit].r.length,11);}
console.log('PASS: cell-only marks; no visible Chinese glyphs; no power/edit logs; five 16:9 sizes exactly fill game + information areas.');

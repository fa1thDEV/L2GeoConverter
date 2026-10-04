#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Viewer HTML page (embedded by the server)."""

HTML_PAGE = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>L2 Geodata Viewer</title>
<style>
:root{--bg:#14161a;--panel:#1d2026;--line:#2a2e36;--ink:#e6e8ee;--mut:#9aa3b2;--acc:#5ac8e0}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,'Segoe UI',Roboto,sans-serif;display:flex;height:100vh;overflow:hidden}
#side{width:250px;background:var(--panel);border-right:1px solid var(--line);overflow-y:auto;padding:10px}
#side h1{font-size:15px;color:var(--acc);margin-bottom:8px}
#side .set{font-size:11px;color:var(--mut);margin-bottom:10px;word-break:break-all}
.rgn{padding:4px 8px;border-radius:6px;cursor:pointer;display:flex;justify-content:space-between;font-variant-numeric:tabular-nums}
.rgn:hover{background:#262a32}.rgn.on{background:#2b3a45;color:var(--acc)}
.rgn .sz{color:var(--mut);font-size:11px}.rgn .stub{color:#e0b45a;font-size:11px}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#bar{padding:8px 14px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;min-height:46px}
#bar b{color:var(--acc);font-size:15px}
select{background:#262a32;color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font-size:12px;cursor:pointer}
select:focus{outline:none;border-color:var(--acc)}
#layer-box{display:inline-flex}
.lbl{color:var(--mut);font-size:13px}
#wrap{flex:1;display:flex;overflow:hidden}
#cv-box{flex:1;overflow:auto;display:flex;align-items:flex-start;justify-content:center;padding:14px;position:relative}
.mapctl{position:absolute;top:22px;right:22px;display:flex;flex-direction:column;gap:6px;z-index:5}
.mapctl button{width:34px;height:34px;background:rgba(29,32,38,.92);color:var(--ink);border:1px solid var(--line);border-radius:8px;cursor:pointer;font-size:16px;line-height:1;transition:color .15s,border-color .15s}
.mapctl button:hover{border-color:var(--acc);color:var(--acc)}
.mapctl button:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
#zoom{width:34px;text-align:center;font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums}
#help-pop{position:absolute;top:22px;right:64px;background:#0d0f12;border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:12px;color:var(--mut);display:none;z-index:6;line-height:1.8;white-space:nowrap}
#help-pop b{color:var(--ink);font-weight:500}
#toast{position:absolute;top:22px;left:50%;transform:translateX(-50%);background:rgba(13,15,18,.95);border:1px solid var(--line);border-radius:8px;padding:8px 14px;font-size:12.5px;color:var(--ink);z-index:6;display:none;max-width:80%;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,.4)}
canvas{image-rendering:pixelated;border:1px solid var(--line);border-radius:4px;cursor:crosshair}
#insp{width:330px;border-left:1px solid var(--line);background:var(--panel);overflow-y:auto;padding:12px}
#insp h2{font-size:13px;color:var(--acc);margin:8px 0 6px}
#insp .kv{display:flex;justify-content:space-between;font-size:12px;padding:2px 0;font-variant-numeric:tabular-nums}
#insp .kv span:first-child{color:var(--mut)}
#cells{display:grid;grid-template-columns:repeat(8,1fr);gap:2px;margin:8px 0}
#cells div{aspect-ratio:1;border-radius:3px;cursor:pointer;border:1px solid transparent;position:relative}
#cells div:hover{border-color:var(--acc)}#cells div.sel{border-color:#fff}
#cells div .ml{position:absolute;right:1px;top:0;font-size:9px;color:rgba(0,0,0,.65);font-weight:700}
.layer{background:#262a32;border-radius:6px;padding:6px 8px;margin:4px 0;font-size:12px;display:flex;justify-content:space-between;align-items:center}
.nswe{display:inline-flex;gap:3px}.nswe i{font-style:normal;width:16px;height:16px;border-radius:3px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;background:#33404a;color:#7fd18a}
.nswe i.x{background:#4a3333;color:#d17f7f;text-decoration:line-through}
#legend{padding:7px 14px;border-top:1px solid var(--line);display:flex;gap:10px;align-items:center;font-size:11px;color:var(--mut);min-height:30px;flex-wrap:wrap}
#grad{width:180px;height:10px;border-radius:5px}
#stats{margin-left:auto;font-variant-numeric:tabular-nums}
.mut{color:var(--mut)}
.spn{padding:3px 8px;border-radius:6px;cursor:pointer;font-size:11px;border-left:3px solid transparent;margin:2px 0}
.spn:hover{background:#262a32}.spn.on{background:#2b3a45}
.spn .nm{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.spn .dt{color:var(--mut);font-variant-numeric:tabular-nums}
#spawns{max-height:42vh;overflow-y:auto;margin-top:8px;border-top:1px solid var(--line);padding-top:8px}
#spawns h2{font-size:12px;color:var(--acc);margin-bottom:6px}
#filt{width:100%;margin:4px 0 6px;background:#262a32;color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 6px;font-size:11px}
#cv3{display:none;width:1024px;height:1024px;background:#0d0f12;border:1px solid var(--line);border-radius:4px;cursor:grab}
.modebtn.on{border-color:var(--acc);color:var(--acc)}
.spbadge{background:#3a2a1a;color:#e0b45a;font-size:10px;border-radius:8px;padding:0 5px;margin-left:4px}
.skey{display:flex;flex-wrap:wrap;gap:3px 8px;font-size:10px;color:var(--mut);margin:4px 0 6px}
.skey i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:3px;vertical-align:middle}
.zgap{margin:8px 0;font-size:11px;font-variant-numeric:tabular-nums}
.zgap .row{display:flex;justify-content:space-between;padding:1px 0}
#tip{position:fixed;pointer-events:none;background:#0d0f12;border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px;display:none;z-index:9;font-variant-numeric:tabular-nums}
</style></head><body>
<div id="side"><h1>⛰ Geodata Viewer</h1><div class="set" id="setname"></div><div id="list"></div>
  <div id="spawns" style="display:none">
    <h2>Failed spawns</h2>
    <select id="filt" aria-label="Spawn filter">
      <option value="review">review (fix)</option>
      <option value="near_z">near_z — widen Z</option>
      <option value="hole">hole — move XY</option>
      <option value="wrong_floor">wrong_floor</option>
      <option value="no_geo_hit">no_geo_hit</option>
      <option value="skip">skip (ignore)</option>
      <option value="all">all</option>
    </select>
    <div class="skey">
      <span><i style="background:#e0b45a"></i>near Z</span>
      <span><i style="background:#e05a5a"></i>hole</span>
      <span><i style="background:#e07a3a"></i>floor</span>
      <span><i style="background:#5ac8e0"></i>no hit</span>
    </div>
    <div id="splist"></div>
  </div>
</div>
<div id="main">
  <div id="bar"><b id="title">pick a region</b>
    <span id="layer-box" style="display:none;align-items:center;gap:6px">
      <label for="slice-sel" class="lbl">Layer:</label>
      <select id="slice-sel" aria-label="Layer select"></select></span>
    <span id="mode-box" style="display:none;align-items:center;gap:6px">
      <button class="mapctl modebtn on" id="btn2d" type="button" style="position:static;width:auto;padding:0 10px;height:28px;font-size:12px">2D</button>
      <button class="mapctl modebtn" id="btn3d" type="button" style="position:static;width:auto;padding:0 10px;height:28px;font-size:12px">3D</button>
      <button class="mapctl modebtn" id="btnunr" type="button" style="position:static;width:auto;padding:0 10px;height:28px;font-size:12px;display:none" title="Overlay UNR collision meshes + BSP interiors">UNR</button>
      <button class="mapctl modebtn" id="btndiff" type="button" style="position:static;width:auto;padding:0 10px;height:28px;font-size:12px;display:none" title="UNR collision floors vs geo layers (magenta = UNR-only, orange = geo-only)">Δ</button>
    </span></div>
  <div id="wrap">
    <div id="cv-box"><canvas id="cv" width="1024" height="1024" style="display:none"></canvas>
      <canvas id="cv3" width="1024" height="1024"></canvas>
      <div class="mapctl" id="mapctl" style="display:none">
        <button id="z-in" aria-label="Zoom in">+</button>
        <button id="z-out" aria-label="Zoom out">−</button>
        <button id="z-reset" aria-label="Show the whole region">⌂</button>
        <div id="zoom">×1</div>
        <button id="dl-btn" aria-label="Download region PNG" title="Download region PNG (2048×2048, current layer)">⬇</button>
        <button id="help-btn" aria-label="Map controls">?</button>
      </div>
      <div id="toast"></div>
      <div id="help-pop">
        <b>wheel</b> — zoom to cursor<br>
        <b>drag</b> — pan<br>
        <b>click the map</b> — open a block<br>
        <b>click a cell</b> — layers and walkability<br>
        <span style="color:#e05a5a">━</span> closed directions (zoom ≥8)<br>
        <span>▪</span> white dot — multi-layer block<br>
        <b>⬇</b> — download region PNG (current layer)<br>
        <b>Layer</b> — 1 = surface; 2+ = floors below (cave is a small island)<br>
        <b>pins</b> — failed NPC territories (color = bucket)<br>
        <b>3D drag</b> — orbit · <b>wheel</b> — zoom<br>
        <span style="color:#fff">○</span> script Z · colored ● geo Z<br>
        <b>UNR</b> — collision meshes (teal) + BSP interiors (purple)<br>
        <span style="color:#c97ae8">purple under the surface = real underground geo</span><br>
        <b>Δ</b> — UNR vs geo: <span style="color:#e05a5a">magenta</span> UNR floor missing in geo,
        <span style="color:#e0b45a">orange</span> geo layer missing in UNR
      </div>
    </div>
    <div id="insp"><h2>Inspector</h2><div id="insp-body" class="mut">Pick a block on the map.</div></div>
  </div>
  <div id="legend"><span id="leg-name">height:</span><canvas id="grad" width="180" height="10"></canvas>
    <span id="lo"></span>–<span id="hi"></span>
    <span id="leg-note"></span>
    <span id="stats"></span></div>
</div>
<div id="tip"></div>
<script>
const STOPS=[[0,[26,35,64]],[.125,[35,72,107]],[.25,[46,109,117]],[.375,[61,143,111]],
 [.5,[106,174,106]],[.625,[168,192,122]],[.75,[211,201,154]],[.875,[236,227,200]],[1,[255,255,255]]];
function elev(h,lo,hi){ // palette normalized to the region height range
 const t=hi<=lo?0.5:Math.max(0,Math.min(1,(h-lo)/(hi-lo)));
 for(let i=1;i<STOPS.length;i++){const[t1,c1]=STOPS[i],[t0,c0]=STOPS[i-1];
  if(t<=t1){const f=(t-t0)/(t1-t0);return c0.map((a,j)=>Math.round(a+(c1[j]-a)*f));}}
 return STOPS.at(-1)[1];}
let cur=null,sum=null,selBlock=null;
const $=id=>document.getElementById(id);
const REVIEW=new Set(['near_z','hole','wrong_floor','no_geo_hit']);
const BUCKET_COL={near_z:'#e0b45a',hole:'#e05a5a',wrong_floor:'#e07a3a',no_geo_hit:'#5ac8e0',
 skip_old_ti:'#6a7380',skip_sky:'#9a7ad4',skip_broken:'#6a7380',skip_stub:'#6a7380'};
let SPAWNS=[], selSpawn=null, MODE3=false, SHOW_UNR=false, HAS_CLIENT=false, UNR=null, UNR_LOAD=null;
let SHOW_DIFF=false, DIFF=null, DIFF_LOAD=null;
fetch('/api/meta').then(r=>r.json()).then(m=>{
 $('setname').textContent=m.primary;
 HAS_CLIENT=!!m.client;
 if(HAS_CLIENT){$('btnunr').style.display='';$('btndiff').style.display='';}
});
let REGION_ROWS=null;
fetch('/api/regions').then(r=>r.json()).then(rs=>{REGION_ROWS=rs;renderRegionList();});
function renderRegionList(){
 if(!REGION_ROWS)return;
 const n={};
 SPAWNS.forEach(s=>{if(REVIEW.has(s.bucket))n[s.region]=(n[s.region]||0)+1;});
 $('list').innerHTML=REGION_ROWS.map(r=>{
  const badge=n[r.name]?`<span class="spbadge">${n[r.name]}</span>`:'';
  return `<div class="rgn${cur===r.name?' on':''}" data-n="${r.name}"><span>${r.name}</span>`+
   `<span><span class="${r.stub?'stub':'sz'}">${r.stub?'stub':(r.size/1048576).toFixed(1)+'M'}</span>${badge}</span></div>`;
 }).join('');
 document.querySelectorAll('.rgn').forEach(el=>el.onclick=()=>load(el.dataset.n));}
const grad=$('grad').getContext('2d');
function drawLegend(lo,hi){
 for(let x=0;x<180;x++){const[r,g,b]=elev(lo+x/180*(hi-lo),lo,hi);
  grad.fillStyle=`rgb(${r},${g},${b})`;grad.fillRect(x,0,1,10);}
 $('leg-name').textContent='surface height:';
 $('lo').textContent=lo;$('hi').textContent=hi;$('leg-note').textContent='';}
function drawSliceLegend(lo,hi,n){
 drawLegend(lo,hi);
 $('leg-name').textContent=`height (layer ${n} from top):`;
 $('leg-note').textContent='dark blocks — no such layer';}
drawLegend(-16384,16384);
let SL=-1,sliceGrid=null; // current region slice (-1 = surface)
async function load(name){
 document.querySelectorAll('.rgn').forEach(e=>e.classList.toggle('on',e.dataset.n===name));
 $('title').textContent=name;$('stats').textContent='loading…';
 sum=await fetch('/api/region/'+name).then(r=>r.json());cur=name;selBlock=null;
 Z=1;OX=0;OY=0;clearNswe();
 buildLayerSelect();
 await setLayer(-1);
 $('insp-body').innerHTML='<span class="mut">Pick a block on the map.</span>';
 $('mapctl').style.display='';
 $('mode-box').style.display='inline-flex';
 listSpawns();
 if(SHOW_UNR) ensureUnr();
 if(SHOW_DIFF) ensureDiff();
 $('stats').textContent=`flat ${sum.nf} · complex ${sum.nc} · multi ${sum.nm} · h ∈ [${sum.gmin}, ${sum.gmax}]`;}
function buildLayerSelect(){
 const maxL=sum.lm.reduce((a,b)=>a>b?a:b,0);
 const sel=$('slice-sel');
 sel.innerHTML='<option value="-1">1 — surface</option>';
 for(let i=1;i<maxL;i++){
  const nb=sum.lm.filter(v=>v>i).length;
  sel.insertAdjacentHTML('beforeend',`<option value="${i}">${i+1}${i===1?' — below surface':''} · ${nb} blocks</option>`);}
 sel.value='-1';sel.disabled=false;
 $('layer-box').style.display=maxL>1?'inline-flex':'none';
 sel.onchange=()=>setLayer(+sel.value);}
function sliceStats(g){
 let n=0,zmin=null,zmax=null,x0=256,y0=256,x1=-1,y1=-1;
 if(!g||!g.hmax)return {n:0};
 for(let bx=0;bx<256;bx++)for(let by=0;by<256;by++){
  const h=g.hmax[bx*256+by]; if(h==null)continue;
  n++; zmin=zmin==null?h:Math.min(zmin,h); zmax=Math.max(zmax,h);
  if(bx<x0)x0=bx; if(bx>x1)x1=bx; if(by<y0)y0=by; if(by>y1)y1=by;}
 return {n,zmin,zmax,x0,y0,x1,y1};}
function fitSlice(st){
 if(!st||!st.n)return;
 const pad=8, x0=Math.max(0,st.x0-pad), y0=Math.max(0,st.y0-pad);
 const x1=Math.min(255,st.x1+pad), y1=Math.min(255,st.y1+pad);
 const w=(x1-x0+1)*4, hgt=(y1-y0+1)*4;
 Z=1; while(Z<32 && Z*2<=Math.min(1024/w,1024/hgt)) Z*=2;
 OX=x0*4-(1024/Z-w)/2; OY=y0*4-(1024/Z-hgt)/2;}
async function setLayer(li){
 SL=li;clearNswe();
 if(SL>=0){
  sliceGrid=await fetch(`/api/region/${cur}?layer=${SL}`).then(r=>r.json());
  const st=sliceStats(sliceGrid); sliceGrid._st=st;
  drawSliceLegend(sum.gmin,sum.gmax,SL+1);
  if(!st.n) toast(`<b>Layer ${SL+1}</b>: no geodata cells at this depth on this square.`);
  else{
   toast(`<b>Layer ${SL+1}</b>: ${st.n.toLocaleString()} / 65,536 blocks · Z ${st.zmin} … ${st.zmax}. Dark = no floor here.`,8000);
   if(!MODE3 && st.n<12000) fitSlice(st);}
 }else{
  sliceGrid=null;
  drawLegend(sum.gsmin,sum.gmax);
 }
 draw();}
let toastTimer=null;
function toast(html,ms){const t=$('toast');t.innerHTML=html;t.style.display='block';
 clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.style.display='none',ms||6000);
 t.onclick=()=>t.style.display='none';}
const cv=$('cv'),ctx=cv.getContext('2d');
const base=document.createElement('canvas');base.width=1024;base.height=1024;
const bctx=base.getContext('2d');
let Z=1,OX=0,OY=0; // zoom and viewport offset (in base pixels)
function renderBase(){if(!sum)return;
 const img=bctx.createImageData(1024,1024);
 for(let bx=0;bx<256;bx++)for(let by=0;by<256;by++){
  const i=bx*256+by;let col;
  if(SL>=0&&sliceGrid){const h=sliceGrid.hmax[i];
   col=h==null?[26,29,35]:elev(h,sum.gmin,sum.gmax);}
  else{col=elev(sum.hmax[i],sum.gsmin,sum.gmax);if(sum.t[i]===2)col=col.map(v=>Math.max(0,v-18));}
  for(let dy=0;dy<4;dy++)for(let dx=0;dx<4;dx++){
   const p=((by*4+dy)*1024+bx*4+dx)*4;
   img.data[p]=col[0];img.data[p+1]=col[1];img.data[p+2]=col[2];img.data[p+3]=255;}
 }
 bctx.putImageData(img,0,0);}
function clampView(){const vw=1024/Z;OX=Math.max(0,Math.min(1024-vw,OX));OY=Math.max(0,Math.min(1024-vw,OY));}
function draw(){if(!sum)return;
 if(MODE3){rebuild3d();return;}
 cv.style.display='';
 renderBase();blit();}
let nsweCache={},nsweTimer=null,nsweBusy=false;
function clearNswe(){nsweCache={};}
function blit(){clampView();
 ctx.imageSmoothingEnabled=false;
 ctx.clearRect(0,0,1024,1024);
 ctx.drawImage(base,OX,OY,1024/Z,1024/Z,0,0,1024,1024);
 { // multi-layer block marks: fixed size at any zoom
  ctx.fillStyle='rgba(255,255,255,.85)';
  const bx0=Math.max(0,Math.floor(OX/4)),by0=Math.max(0,Math.floor(OY/4));
  const bx1=Math.min(255,Math.ceil((OX+1024/Z)/4)),by1=Math.min(255,Math.ceil((OY+1024/Z)/4));
  for(let bx=bx0;bx<=bx1;bx++)for(let by=by0;by<=by1;by++)
   if(sum.t[bx*256+by]===2)ctx.fillRect((bx*4-OX)*Z,(by*4-OY)*Z,2,2);}
 if(Z>=8)drawNswe();
 if(SHOW_DIFF&&DIFF&&DIFF.region===cur){
  const bx0=Math.max(0,Math.floor(OX/4)),by0=Math.max(0,Math.floor(OY/4));
  const bx1=Math.min(255,Math.ceil((OX+1024/Z)/4)),by1=Math.min(255,Math.ceil((OY+1024/Z)/4));
  for(const b of DIFF.b){
   if(b.bx<bx0||b.bx>bx1||b.by<by0||b.by>by1)continue;
   const x=(b.bx*4-OX)*Z,y=(b.by*4-OY)*Z,s=Math.max(2,4*Z);
   if(b.miss){ctx.fillStyle='rgba(224,90,90,.50)';ctx.fillRect(x,y,s,s);}
   if(b.extra){ctx.fillStyle='rgba(224,180,60,.50)';ctx.fillRect(x+s*0.15,y+s*0.15,s*0.7,s*0.7);}
  }}
 if(selBlock){ctx.strokeStyle='#fff';ctx.lineWidth=Math.max(1,Z/2);
  ctx.strokeRect((selBlock[0]*4-OX)*Z-.5,(selBlock[1]*4-OY)*Z-.5,4*Z+1,4*Z+1);}
 drawSpawns2d();
 $('zoom').textContent='×'+Z;}
function drawNswe(){ // red edges = closed directions
 const bx0=Math.max(0,Math.floor(OX/4)),by0=Math.max(0,Math.floor(OY/4));
 const bx1=Math.min(255,Math.ceil((OX+1024/Z)/4)),by1=Math.min(255,Math.ceil((OY+1024/Z)/4));
 const missing=[];
 ctx.strokeStyle='rgba(255,80,80,.9)';ctx.lineWidth=Math.max(1,Z/16);
 for(let bx=bx0;bx<=bx1;bx++)for(let by=by0;by<=by1;by++){
  const key=bx+'_'+by,vals=nsweCache[key];
  if(vals===undefined){missing.push(key);continue;}
  for(let cx=0;cx<8;cx++)for(let cy=0;cy<8;cy++){
   const v=vals[cx*8+cy];
   if(v===null||v===15)continue;
   const x=((bx*4+cx*.5)-OX)*Z,y=((by*4+cy*.5)-OY)*Z,s=.5*Z;
   ctx.beginPath();
   if(!(v&8)){ctx.moveTo(x,y);ctx.lineTo(x+s,y);}         // N closed → top
   if(!(v&4)){ctx.moveTo(x,y+s);ctx.lineTo(x+s,y+s);}     // S → bottom
   if(!(v&2)){ctx.moveTo(x,y);ctx.lineTo(x,y+s);}         // W → left
   if(!(v&1)){ctx.moveTo(x+s,y);ctx.lineTo(x+s,y+s);}     // E → right
   ctx.stroke();}}
 if(missing.length&&!nsweBusy){
  clearTimeout(nsweTimer);
  nsweTimer=setTimeout(async()=>{
   nsweBusy=true;
   try{const r=await fetch(`/api/nswe/${cur}?bx0=${bx0}&by0=${by0}&bx1=${bx1}&by1=${by1}&layer=${SL}`).then(x=>x.json());
    Object.assign(nsweCache,r.b);}finally{nsweBusy=false;}
   blit();},150);}}
function toBlock(e){const r=cv.getBoundingClientRect();
 const px=OX+(e.clientX-r.left)/r.width*1024/Z,py=OY+(e.clientY-r.top)/r.height*1024/Z;
 return [Math.floor(px/4),Math.floor(py/4)];}
function zoomAt(sx,sy,dir){ // dir: +1 zoom in, -1 zoom out
 const px=OX+sx/Z,py=OY+sy/Z;
 Z=dir>0?Math.min(32,Z*2):Math.max(1,Z/2);
 OX=px-sx/Z;OY=py-sy/Z;blit();}
cv.addEventListener('wheel',e=>{if(!sum)return;e.preventDefault();
 const r=cv.getBoundingClientRect();
 zoomAt((e.clientX-r.left)/r.width*1024,(e.clientY-r.top)/r.height*1024,e.deltaY<0?1:-1);},{passive:false});
$('z-in').onclick=()=>{if(MODE3){dist=Math.max(.4,dist*0.89);draw3d();}else if(sum)zoomAt(512,512,1);};
$('z-out').onclick=()=>{if(MODE3){dist=Math.min(6,dist*1.12);draw3d();}else if(sum)zoomAt(512,512,-1);};
$('z-reset').onclick=()=>{if(MODE3){yaw=.7;pitch=.55;dist=2.4;draw3d();}else if(sum){Z=1;OX=0;OY=0;blit();}};
$('dl-btn').onclick=()=>{if(!cur)return;
 toast('Rendering PNG 2048×2048… the file will download in a few seconds.',4000);
 const a=document.createElement('a');
 a.href=`/api/render/${cur}?layer=${SL}`;a.download='';
 document.body.appendChild(a);a.click();a.remove();};
$('help-btn').onclick=()=>{const p=$('help-pop');p.style.display=p.style.display==='none'||!p.style.display?'block':'none';};
document.addEventListener('click',e=>{if(!e.target.closest('#help-btn,#help-pop'))$('help-pop').style.display='none';});
let dragging=false,moved=0,lx=0,ly=0;
cv.onmousedown=e=>{dragging=true;moved=0;lx=e.clientX;ly=e.clientY;};
window.addEventListener('mouseup',()=>dragging=false);
const tip=$('tip');
cv.onmousemove=e=>{if(!sum)return;
 if(dragging){const r=cv.getBoundingClientRect();
  const dx=(e.clientX-lx)/r.width*1024/Z,dy=(e.clientY-ly)/r.height*1024/Z;
  OX-=dx;OY-=dy;moved+=Math.abs(e.clientX-lx)+Math.abs(e.clientY-ly);
  lx=e.clientX;ly=e.clientY;blit();tip.style.display='none';return;}
 const [bx,by]=toBlock(e);
 if(bx<0||by<0||bx>255||by>255){tip.style.display='none';return;}
 const i=bx*256+by,[rx,ry]=cur.split('_').map(Number);
 const wx=(rx-20)*32768+bx*128,wy=(ry-18)*32768+by*128;
 const hit=spawnAt(bx,by);
 if(hit){
  tip.innerHTML=`<b>${hit.name}</b><br>${hit.bucket} · geoZ ${hit.geo_z??'no hit'}<br>npcpos Z ${hit.zmin??'?'} … ${hit.zmax??'?'} · Δ ${hit.delta??'—'}`;
  tip.style.display='block';tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';return;}
 const T=['flat','complex','multi'][sum.t[i]];
 let extra=SL>=0&&sliceGrid?`<br>slice layer ${SL+1}: `+(sliceGrid.hmax[i]===null?'none':'h='+sliceGrid.hmax[i]):'';
 if(SHOW_DIFF&&DIFF&&DIFF.region===cur){
  const hit=DIFF.b.find(b=>b.bx===bx&&b.by===by);
  if(hit) extra+=`<br>Δ UNR-only ${hit.miss} · geo-only ${hit.extra}`;
 }
 tip.innerHTML=`block ${bx},${by} · ${T}<br>world ≈ ${wx}, ${wy}<br>h ∈ [${sum.hmin[i]}, ${sum.hmax[i]}] · layers ≤ ${sum.lm[i]}${extra}`;
 tip.style.display='block';tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';};
cv.onmouseleave=()=>{tip.style.display='none';dragging=false;};
cv.onclick=async e=>{if(!sum||moved>4)return;
 const [bx,by]=toBlock(e);
 if(bx<0||by<0||bx>255||by>255)return;
 const hit=spawnAt(bx,by);
 if(hit){selectSpawn(hit.name);return;}
 selBlock=[bx,by];blit();
 const d=await fetch(`/api/block/${cur}/${bx}/${by}`).then(r=>r.json());
 showBlock(bx,by,d);};
function showBlock(bx,by,d){
 const[rx,ry]=cur.split('_').map(Number);
 const wx=(rx-20)*32768+bx*128,wy=(ry-18)*32768+by*128;
 // each cell’s layers sorted top to bottom
 const cellsSorted=d.cells.map(c=>[...c].sort((a,b)=>b[0]-a[0]));
 const maxL=Math.max(...cellsSorted.map(c=>c.length));
 let html=`<h2>Block ${bx},${by}</h2>
  <div class="kv"><span>world coords</span><span>${wx} … ${wx+128}, ${wy} … ${wy+128}</span></div>
  <div class="kv"><span>type</span><span>${['flat','complex','multilayer'][d.type]}</span></div>
  <h2>Cells 8×8</h2>`;
 if(maxL>1){
  html+=`<div id="lsel" style="margin:4px 0"><select id="lsel-sel">
   <option value="-1">surface</option>`;
  for(let i=0;i<maxL;i++)html+=`<option value="${i}">layer ${i+1}${i===0?' (top)':''}</option>`;
  html+=`</select></div><div class="mut" style="font-size:11px;margin:2px 0 6px">slice: cells without that layer dim out</div>`;}
 html+=`<div id="cells"></div><div id="layers" class="mut">Click a cell → layers.</div>`;
 $('insp-body').innerHTML=html;
 function paintCells(li){ // li=-1: top layer of each cell; else N-th from the top
  let h='';
  for(let cy=0;cy<8;cy++)for(let cx=0;cx<8;cx++){
   const cell=cellsSorted[cx*8+cy];
   const layer=li<0?cell[0]:cell[li];
   let style,body='';
   if(layer===undefined){style='background:#22262d;opacity:.35';}
   else{const[r,g,b]=elev(layer[0],sum.gmin,sum.gmax);style=`background:rgb(${r},${g},${b})`;
    if(li<0&&cell.length>1)body=`<span class="ml">${cell.length}</span>`;}
   h+=`<div data-c="${cx*8+cy}" style="${style}" title="cell ${cx},${cy}${layer!==undefined?' · h='+layer[0]:' · no layer'}">${body}</div>`;}
  $('cells').innerHTML=h;
  bindCells();}
 if(maxL>1)$('lsel-sel').onchange=e=>paintCells(+e.target.value);
 paintCells(-1);
 function bindCells(){document.querySelectorAll('#cells div').forEach(el=>el.onclick=()=>{
  document.querySelectorAll('#cells div').forEach(x=>x.classList.remove('sel'));
  el.classList.add('sel');
  const ci=+el.dataset.c,cell=cellsSorted[ci];
  const cx=Math.floor(ci/8),cy=ci%8;
  let h=`<h2>Cell ${cx},${cy} · world ${wx+cx*16}, ${wy+cy*16}</h2>`;
  h+=cell.map((l,i)=>layerHtml(l,i,cell.length)).join('');
  if(cell.length>1)h+=`<div class="mut" style="font-size:11px;margin:6px 0">`+
   `Layers are walkable-surface levels at one map point vertically: `+
   `a bridge over ground, building floors, a dungeon under the surface. The character stands `+
   `on the layer nearest their Z; NSWE shows which directions they can step from it.</div>`;
  if(HAS_CLIENT) h+=`<div class="mut" id="unrcmp" style="margin-top:8px">UNR vs geo…</div>`;
  $('layers').innerHTML=h;
  if(HAS_CLIENT){
   const gx=bx*8+cx, gy=by*8+cy;
   fetch(`/api/mismatch/cell/${cur}/${gx}/${gy}`).then(r=>r.json()).then(d=>{
    const el=$('unrcmp'); if(!el)return;
    if(d.err){el.textContent=d.err;return;}
    const fmt=zs=>zs&&zs.length?zs.join(', '):'—';
    el.innerHTML=`<h2>UNR vs geo</h2>
      <div class="kv"><span>UNR floors</span><span>${fmt(d.unr)}</span></div>
      <div class="kv"><span>geo layers</span><span>${fmt(d.geo)}</span></div>
      <div class="kv"><span>UNR only</span><span style="color:#e05a5a">${fmt(d.miss)}</span></div>
      <div class="kv"><span>geo only</span><span style="color:#e0b45a">${fmt(d.extra)}</span></div>`;
   }).catch(e=>{const el=$('unrcmp'); if(el)el.textContent=String(e);});
  }
  });}}
function layerHtml([hh,nswe],idx,total){
 const dir=[['N',8],['S',4],['W',2],['E',1]];
 const tag=total>1?`<span class="mut" style="font-size:10px">layer ${idx+1}${idx===0?' (top)':idx===total-1?' (bottom)':''}</span> `:'';
 return `<div class="layer"><span>${tag}h = <b>${hh}</b></span><span class="nswe">`+
  dir.map(([n,b])=>`<i class="${nswe&b?'':'x'}" title="${n}: ${nswe&b?'pass open':'blocked'}">${n}</i>`).join('')+`</span></div>`;}

fetch('/api/spawns').then(r=>r.json()).then(j=>{
 SPAWNS=j.spawns||[];
 if(SPAWNS.length){$('spawns').style.display='';listSpawns();renderRegionList();}
});
function bucketOk(b,filt){
 if(filt==='all')return true;
 if(filt==='review')return REVIEW.has(b);
 if(filt==='skip')return String(b).startsWith('skip');
 return b===filt;}
function listSpawns(){
 const filt=$('filt').value;
 const pool=SPAWNS.filter(s=>bucketOk(s.bucket,filt)&&(!cur||s.region===cur));
 $('splist').innerHTML=pool.map(s=>{
  const col=BUCKET_COL[s.bucket]||'#9aa3b2';
  const dz=s.delta==null?'':(s.side==='above'?' +'+s.delta:' −'+s.delta);
  return `<div class="spn${selSpawn&&selSpawn.name===s.name?' on':''}" data-n="${s.name}" style="border-left-color:${col}">
   <span class="nm">${s.name}</span>
   <span class="dt">${s.region} · ${s.bucket}${dz} · geoZ ${s.geo_z??'?'}</span></div>`;}).join('')
  ||`<div class="mut" style="font-size:11px">${cur?'none in this region for this filter':'pick a region, or click a spawn'}</div>`;
 document.querySelectorAll('#splist .spn').forEach(el=>el.onclick=()=>selectSpawn(el.dataset.n));
}
$('filt').onchange=()=>{listSpawns();renderRegionList();if(sum){if(MODE3)draw3d();else blit();}};
function regionSpawns(){const filt=$('filt').value;return SPAWNS.filter(s=>s.region===cur&&bucketOk(s.bucket,filt));}
function worldToBase(wx,wy){
 const[rx,ry]=cur.split('_').map(Number);
 return [((wx-(rx-20)*32768)/128)*4, ((wy-(ry-18)*32768)/128)*4];}
function drawSpawns2d(){
 if(!cur||!sum)return;
 const list=regionSpawns();
 for(const s of list){
  const col=BUCKET_COL[s.bucket]||'#fff';
  if(s.poly&&s.poly.length>1){
   ctx.beginPath();ctx.strokeStyle=col;ctx.globalAlpha=.5;ctx.lineWidth=Math.max(1,Z/4);
   s.poly.forEach((p,i)=>{const[x,y]=worldToBase(p[0],p[1]);const px=(x-OX)*Z,py=(y-OY)*Z;
    i?ctx.lineTo(px,py):ctx.moveTo(px,py);});
   ctx.closePath();ctx.stroke();ctx.globalAlpha=1;}
  const[x,y]=worldToBase(s.wx,s.wy);
  const px=(x-OX)*Z,py=(y-OY)*Z,r=Math.max(4,3*Z/2);
  ctx.beginPath();ctx.fillStyle=col;ctx.strokeStyle='#0d0f12';ctx.lineWidth=1.5;
  ctx.arc(px,py,r,0,Math.PI*2);ctx.fill();ctx.stroke();
  if(selSpawn&&selSpawn.name===s.name){ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(px,py,r+4,0,Math.PI*2);ctx.stroke();}}
}
function spawnAt(bx,by){
 const list=regionSpawns();
 let best=null,bd=99;
 for(const s of list){const d=Math.abs(s.bx-bx)+Math.abs(s.by-by);if(d<bd&&d<=2){bd=d;best=s;}}
 return best;}
async function selectSpawn(name){
 const s=SPAWNS.find(x=>x.name===name);if(!s)return;
 selSpawn=s;
 if(cur!==s.region)await load(s.region);
 selSpawn=s;selBlock=[s.bx,s.by];
 Z=Math.max(Z,8);
 const[x,y]=worldToBase(s.wx,s.wy);
 OX=x-512/Z;OY=y-512/Z;
 listSpawns();
 if(MODE3){draw3d();showSpawnInsp(s);return;}
 blit();
 const d=await fetch(`/api/block/${cur}/${s.bx}/${s.by}`).then(r=>r.json());
 showBlock(s.bx,s.by,d);
 showSpawnInsp(s,true);
}
function showSpawnInsp(s,append){
 const col=BUCKET_COL[s.bucket]||'#e6e8ee';
 const win=s.zmin==null?'?':`${s.zmin} … ${s.zmax}`;
 const pad=16;
 let hint='Inspect in 3D: colored pin = geo Z, white pin = npcpos Z.';
 if(s.action==='widen_z'&&s.side==='above'&&s.geo_z!=null)
  hint=`Geo is ${s.delta} above the npcpos slab. Raise Zmax from ${s.zmax} to ${s.geo_z+pad} (or shift the whole window up by ${s.delta+pad}).`;
 else if(s.action==='widen_z'&&s.side==='below'&&s.geo_z!=null)
  hint=`Geo is ${s.delta} below the npcpos slab. Lower Zmin from ${s.zmin} to ${s.geo_z-pad} (or shift the whole window down by ${s.delta+pad}).`;
 else if(s.action==='move_xy')
  hint='Centroid sits on ocean / empty geo (~−4640). Nudge the polygon XY onto the nearby walkable mesh — do not just raise Z.';
 else if(s.action==='check_floor')
  hint='Script Z and geo Z are different floors (often dungeon vs surface). Do not blindly widen Z — pick the correct layer or move XY.';
 else if(s.action==='ignore')
  hint='Leave it: leftover Talking Island names, flyer/sky territory, or a broken Z in the script.';
 const box=`<h2 style="color:${col}">Spawn ${s.name}</h2>
  <div class="kv"><span>region</span><span>${s.region}</span></div>
  <div class="kv"><span>world XY</span><span>${s.wx}, ${s.wy}</span></div>
  <div class="kv"><span>geo Z (centroid)</span><span>${s.geo_z??'no hit'}</span></div>
  <div class="kv"><span>npcpos Z window</span><span>${win}</span></div>
  <div class="kv"><span>miss</span><span>${s.side} ${s.delta??''}</span></div>
  <div class="kv"><span>bucket / action</span><span>${s.bucket} → ${s.action}</span></div>
  <div class="zgap mut">${hint}</div>`;
 if(append) $('insp-body').insertAdjacentHTML('afterbegin', box);
 else $('insp-body').innerHTML=box;
}

$('btn2d').onclick=()=>setMode3(false);
$('btn3d').onclick=()=>setMode3(true);
$('btnunr').onclick=()=>toggleUnr();
$('btndiff').onclick=()=>toggleDiff();
function setMode3(on){
 MODE3=!!on;
 $('btn2d').classList.toggle('on',!MODE3);
 $('btn3d').classList.toggle('on',MODE3);
 $('cv').style.display=MODE3?'none':(sum?'':'none');
 $('cv3').style.display=MODE3?'block':'none';
 if(MODE3){if(SHOW_UNR)ensureUnr();rebuild3d();}
 else if(sum){ $('cv').style.display='';blit();}}
async function toggleUnr(){
 if(!HAS_CLIENT){toast('No client Maps folder — start the viewer with --client',5000);return;}
 if(!cur){toast('Pick a region first.',3000);return;}
 if(!MODE3) setMode3(true);
 SHOW_UNR=!SHOW_UNR;
 $('btnunr').classList.toggle('on',SHOW_UNR);
 if(SHOW_UNR) await ensureUnr();
 if(SHOW_UNR&&UNR&&UNR.region===cur)
  $('leg-note').textContent='teal mesh · purple BSP/interior · red blocking · ghost = geo';
 else $('leg-note').textContent='';
 rebuild3d();}
async function toggleDiff(){
 if(!HAS_CLIENT){toast('No client Maps folder — start the viewer with --client',5000);return;}
 if(!cur){toast('Pick a region first.',3000);return;}
 SHOW_DIFF=!SHOW_DIFF;
 $('btndiff').classList.toggle('on',SHOW_DIFF);
 if(SHOW_DIFF){
  if(MODE3) setMode3(false);
  await ensureDiff();
  $('leg-note').textContent='Δ magenta = UNR floor missing in geo · orange = geo layer missing in UNR';
 }else $('leg-note').textContent='';
 blit();}
async function ensureDiff(){
 if(!cur||!HAS_CLIENT)return;
 if(DIFF&&DIFF.region===cur)return;
 if(DIFF_LOAD===cur)return;
 const want=cur; DIFF_LOAD=want;
 toast('Comparing UNR collision to geo… first pass parses this square and its neighbors.',120000);
 try{
  const d=await fetch('/api/mismatch/'+want).then(r=>r.json());
  if(d.err) throw new Error(d.err);
  DIFF={region:want,...d};
  toast(`Δ ${d.nblocks.toLocaleString()} blocks · ${d.nmiss} UNR-only floors · ${d.nextra} geo-only layers`,8000);
  if(SHOW_DIFF&&cur===want) blit();
 }catch(e){
  if(DIFF_LOAD===want){SHOW_DIFF=false;$('btndiff').classList.remove('on');}
  toast('Δ: '+e.message,8000);
 }finally{if(DIFF_LOAD===want)DIFF_LOAD=null;}
}
async function ensureUnr(){
 if(!cur||!HAS_CLIENT)return;
 if(UNR&&UNR.region===cur)return;
 if(UNR_LOAD===cur)return;
 const want=cur; UNR_LOAD=want;
 toast('Loading UNR collision meshes… first load of a square can take a while.',120000);
 try{
  const r=await fetch('/api/unr/'+want);
  if(!r.ok){let msg=r.statusText;try{msg=(await r.json()).err||msg;}catch(e){} throw new Error(msg);}
  const buf=await r.arrayBuffer();
  const dv=new DataView(buf);
  const mag=String.fromCharCode(dv.getUint8(0),dv.getUint8(1),dv.getUint8(2),dv.getUint8(3));
  if(mag!=='L2U1') throw new Error('bad UNR payload');
  const ntri=dv.getUint32(4,true), zmin=dv.getFloat32(8,true), zmax=dv.getFloat32(12,true);
  const nmesh=dv.getUint32(16,true), nbsp=dv.getUint32(20,true), nblk=dv.getUint32(24,true);
  const skipped=dv.getUint32(28,true);
  UNR={region:want,ntri,zmin,zmax,nmesh,nbsp,nblk,skipped,
       xyz:new Float32Array(buf,32,ntri*9), kinds:new Uint8Array(buf,32+ntri*9*4,ntri)};
  toast(`UNR ${nmesh.toLocaleString()} mesh + ${nbsp.toLocaleString()} BSP`
   +(nblk?` + ${nblk} blocking`:'')+(skipped?` (${skipped} skipped)`:''),6000);
  if(SHOW_UNR&&cur===want&&MODE3)rebuild3d();
 }catch(e){
  if(UNR_LOAD===want){SHOW_UNR=false;$('btnunr').classList.remove('on');}
  toast('UNR: '+e.message,8000);
 }finally{if(UNR_LOAD===want)UNR_LOAD=null;}
}

let gl=null, PROG=null, MESH=null, yaw=.7, pitch=.55, dist=2.4, drag3=false, lx3=0, ly3=0;
function heightRange(){
 let lo=sum.gsmin, hi=sum.gmax;
 for(const s of regionSpawns()){
  if(s.geo_z!=null){lo=Math.min(lo,s.geo_z);hi=Math.max(hi,s.geo_z);}
  if(s.zmin!=null){lo=Math.min(lo,s.zmin);hi=Math.max(hi,s.zmax);}
 }
 if(SHOW_UNR&&UNR&&UNR.region===cur&&UNR.ntri){
  lo=Math.min(lo,UNR.zmin); hi=Math.max(hi,UNR.zmax);}
 if(SL>=0&&sliceGrid&&sliceGrid._st&&sliceGrid._st.n){
  lo=Math.min(lo,sliceGrid._st.zmin); hi=Math.max(hi,sliceGrid._st.zmax);}
 return [lo, Math.max(lo+1,hi)];
}
const UNR_COL=[[.45,.78,.85],[.82,.48,.92],[.90,.32,.32]];
function packUnr(lo,span){
 if(!UNR||UNR.region!==cur||!UNR.ntri)return null;
 const n=UNR.ntri*3, pos=new Float32Array(n*3), col=new Float32Array(n*3), w=UNR.xyz;
 const[rx,ry]=cur.split('_').map(Number);
 const west=(rx-20)*32768, north=(ry-18)*32768;
 for(let i=0;i<n;i++){
  const wx=w[i*3], wy=w[i*3+1], wz=w[i*3+2], k=i*3;
  pos[k]=((wx-west)/32768)*2-1;
  pos[k+1]=((wz-lo)/span)*0.55;
  pos[k+2]=((wy-north)/32768)*2-1;
  const c=UNR_COL[UNR.kinds[(i/3)|0]||0];
  col[k]=c[0];col[k+1]=c[1];col[k+2]=c[2];}
 return {pos,col,n};}
function buildHf(hsrc, lo, span, skipNull){
 const N=256;
 const pos=new Float32Array(N*N*3), col=new Float32Array(N*N*3);
 const miss=new Uint8Array(N*N);
 for(let by=0;by<N;by++)for(let bx=0;bx<N;bx++){
  const i=bx*N+by, h=hsrc[i], k=i*3, missing=h==null;
  miss[i]=missing?1:0;
  const hv=missing?lo:h;
  pos[k]=(bx/N)*2-1; pos[k+1]=((hv-lo)/span)*0.55; pos[k+2]=(by/N)*2-1;
  if(missing){col[k]=.08;col[k+1]=.09;col[k+2]=.10;}
  else{const[r,g,b]=elev(h,sum.gmin,sum.gmax); col[k]=r/255;col[k+1]=g/255;col[k+2]=b/255;}}
 const idx=[];
 for(let by=0;by<N-1;by++)for(let bx=0;bx<N-1;bx++){
  const a=bx*N+by,b=a+1,c=a+N,d=c+1;
  if(skipNull&&(miss[a]||miss[b]||miss[c]||miss[d])) continue;
  idx.push(a,c,b,b,c,d);}
 return {pos,col,idx:new Uint16Array(idx),n:idx.length};}
function rebuild3d(){
 const c=$('cv3');
 if(!gl){
  gl=c.getContext('webgl')||c.getContext('experimental-webgl');
  if(!gl){toast('WebGL unavailable — stay in 2D.',4000);setMode3(false);return;}
 }
 if(!sum||!MODE3)return;
 const [lo,hi]=heightRange(), span=hi-lo;
 const sliceOn=SL>=0&&sliceGrid&&sliceGrid.hmax;
 const main=buildHf(sliceOn?sliceGrid.hmax:sum.hmax, lo, span, !!sliceOn);
 const surf=sliceOn?buildHf(sum.hmax, lo, span, false):null;
 MESH={pos:main.pos,col:main.col,idx:main.idx,n:main.n,lo,span,surf,
       unr:SHOW_UNR?packUnr(lo,span):null};
 if(!gl._b){gl._b=gl.createBuffer();gl._bc=gl.createBuffer();gl._bi=gl.createBuffer();}
 gl.bindBuffer(gl.ARRAY_BUFFER,gl._b); gl.bufferData(gl.ARRAY_BUFFER,MESH.pos,gl.STATIC_DRAW);
 gl.bindBuffer(gl.ARRAY_BUFFER,gl._bc); gl.bufferData(gl.ARRAY_BUFFER,MESH.col,gl.STATIC_DRAW);
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,gl._bi); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,MESH.idx,gl.STATIC_DRAW);
 if(MESH.surf){
  if(!gl._sP){gl._sP=gl.createBuffer();gl._sC=gl.createBuffer();gl._sI=gl.createBuffer();}
  gl.bindBuffer(gl.ARRAY_BUFFER,gl._sP); gl.bufferData(gl.ARRAY_BUFFER,MESH.surf.pos,gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER,gl._sC); gl.bufferData(gl.ARRAY_BUFFER,MESH.surf.col,gl.STATIC_DRAW);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,gl._sI); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,MESH.surf.idx,gl.STATIC_DRAW);}
 if(MESH.unr){
  if(!gl._unrP){gl._unrP=gl.createBuffer();gl._unrC=gl.createBuffer();}
  gl.bindBuffer(gl.ARRAY_BUFFER,gl._unrP); gl.bufferData(gl.ARRAY_BUFFER,MESH.unr.pos,gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER,gl._unrC); gl.bufferData(gl.ARRAY_BUFFER,MESH.unr.col,gl.STATIC_DRAW);}
 draw3d();}
function n3(x,y,z){const l=Math.hypot(x,y,z)||1;return [x/l,y/l,z/l];}
function lookAt(ex,ey,ez,tx,ty,tz){
 let [zx,zy,zz]=n3(ex-tx,ey-ty,ez-tz);
 let [xx,xy,xz]=n3(zz, 0, -zx);
 if(Math.hypot(xx,xy,xz)<1e-5) [xx,xy,xz]=[1,0,0];
 const yx=zy*xz-zz*xy, yy=zz*xx-zx*xz, yz=zx*xy-zy*xx;
 const m=new Float32Array(16);
 m[0]=xx;m[1]=yx;m[2]=zx;
 m[4]=xy;m[5]=yy;m[6]=zy;
 m[8]=xz;m[9]=yz;m[10]=zz;
 m[12]=-(xx*ex+xy*ey+xz*ez);
 m[13]=-(yx*ex+yy*ey+yz*ez);
 m[14]=-(zx*ex+zy*ey+zz*ez); m[15]=1;
 return m;}
function persp(fov,asp,n,f){
 const t=1/Math.tan(fov/2), m=new Float32Array(16);
 m[0]=t/asp; m[5]=t; m[10]=(f+n)/(n-f); m[11]=-1; m[14]=(2*f*n)/(n-f);
 return m;}
function mul4(a,b){
 const o=new Float32Array(16);
 for(let c=0;c<4;c++)for(let r=0;r<4;r++)
  o[c*4+r]=a[r]*b[c*4]+a[4+r]*b[c*4+1]+a[8+r]*b[c*4+2]+a[12+r]*b[c*4+3];
 return o;}
function compile(vs,fs){
 function sh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);
  if(!gl.getShaderParameter(o,gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(o));
  return o;}
 const p=gl.createProgram();gl.attachShader(p,sh(gl.VERTEX_SHADER,vs));gl.attachShader(p,sh(gl.FRAGMENT_SHADER,fs));
 gl.linkProgram(p);
 if(!gl.getProgramParameter(p,gl.LINK_STATUS)) console.error(gl.getProgramInfoLog(p));
 return p;}
function hexRgb(hex){return [parseInt(hex.slice(1,3),16)/255,parseInt(hex.slice(3,5),16)/255,parseInt(hex.slice(5,7),16)/255];}
function worldToMesh(wx,wy,h,lo,span){
 const[rx,ry]=cur.split('_').map(Number);
 return [((wx-(rx-20)*32768)/32768)*2-1, ((h-lo)/span)*0.55, ((wy-(ry-18)*32768)/32768)*2-1];}
function draw3d(){
 if(!gl||!sum||!MESH||!MODE3)return;
 const vs=`attribute vec3 a; attribute vec3 c; uniform mat4 u; uniform float ps; varying vec3 v;
  void main(){v=c; gl_Position=u*vec4(a,1.0); gl_PointSize=ps;}`;
 const fs=`precision mediump float; varying vec3 v; uniform float ua; void main(){gl_FragColor=vec4(v,ua);}`;
 if(!PROG) PROG=compile(vs,fs);
 const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
 const ex=sy*cp*dist, ey=sp*dist+0.18, ez=cy*cp*dist;
 const u=mul4(persp(1.05,1,.08,20), lookAt(ex,ey,ez, 0,0.18,0));
 gl.viewport(0,0,1024,1024); gl.enable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE);
 gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
 gl.clearColor(.05,.06,.08,1); gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
 gl.useProgram(PROG);
 const locA=gl.getAttribLocation(PROG,'a'), locC=gl.getAttribLocation(PROG,'c');
 const uLoc=gl.getUniformLocation(PROG,'u'), psLoc=gl.getUniformLocation(PROG,'ps');
 const uaLoc=gl.getUniformLocation(PROG,'ua');
 if(!gl._b){gl._b=gl.createBuffer();gl._bc=gl.createBuffer();gl._bi=gl.createBuffer();}
 const b=gl._b, bc=gl._bc, bi=gl._bi;
 gl.bindBuffer(gl.ARRAY_BUFFER,b); gl.bufferData(gl.ARRAY_BUFFER,MESH.pos,gl.STREAM_DRAW);
 gl.enableVertexAttribArray(locA); gl.vertexAttribPointer(locA,3,gl.FLOAT,false,0,0);
 gl.bindBuffer(gl.ARRAY_BUFFER,bc); gl.bufferData(gl.ARRAY_BUFFER,MESH.col,gl.STREAM_DRAW);
 gl.enableVertexAttribArray(locC); gl.vertexAttribPointer(locC,3,gl.FLOAT,false,0,0);
 gl.uniformMatrix4fv(uLoc,false,u); gl.uniform1f(psLoc,8);
 if(MESH.surf){
  gl.depthMask(false);
  gl.bindBuffer(gl.ARRAY_BUFFER,gl._sP); gl.vertexAttribPointer(locA,3,gl.FLOAT,false,0,0); gl.enableVertexAttribArray(locA);
  gl.bindBuffer(gl.ARRAY_BUFFER,gl._sC); gl.vertexAttribPointer(locC,3,gl.FLOAT,false,0,0); gl.enableVertexAttribArray(locC);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,gl._sI);
  gl.uniform1f(uaLoc,0.14);
  gl.drawElements(gl.TRIANGLES,MESH.surf.n,gl.UNSIGNED_SHORT,0);
  gl.depthMask(true);}
 gl.bindBuffer(gl.ARRAY_BUFFER,b); gl.bufferData(gl.ARRAY_BUFFER,MESH.pos,gl.STREAM_DRAW);
 gl.enableVertexAttribArray(locA); gl.vertexAttribPointer(locA,3,gl.FLOAT,false,0,0);
 gl.bindBuffer(gl.ARRAY_BUFFER,bc); gl.bufferData(gl.ARRAY_BUFFER,MESH.col,gl.STREAM_DRAW);
 gl.enableVertexAttribArray(locC); gl.vertexAttribPointer(locC,3,gl.FLOAT,false,0,0);
 gl.uniform1f(uaLoc, SHOW_UNR&&MESH.unr?0.22:(MESH.surf?0.92:1.0));
 if(SHOW_UNR&&MESH.unr&&!MESH.surf) gl.depthMask(false);
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,bi);
 if(MESH.n) gl.drawElements(gl.TRIANGLES,MESH.n,gl.UNSIGNED_SHORT,0);
 gl.depthMask(true);
 if(SHOW_UNR&&MESH.unr){
  gl.bindBuffer(gl.ARRAY_BUFFER,gl._unrP); gl.vertexAttribPointer(locA,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,gl._unrC); gl.vertexAttribPointer(locC,3,gl.FLOAT,false,0,0);
  gl.uniform1f(uaLoc,0.62);
  gl.drawArrays(gl.TRIANGLES,0,MESH.unr.n);
  gl.bindBuffer(gl.ARRAY_BUFFER,b); gl.vertexAttribPointer(locA,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,bc); gl.vertexAttribPointer(locC,3,gl.FLOAT,false,0,0);}
 gl.uniform1f(uaLoc,1.0);

 const pins=regionSpawns(), {lo,span}=MESH;
 const geo=[], scr=[], lines=[], gcol=[], scol=[], lcol=[];
 for(const s of pins){
  const hex=BUCKET_COL[s.bucket]||'#ffffff';
  const rgb=hexRgb(hex);
  const mid=(s.zmin!=null&&s.zmax!=null)?(s.zmin+s.zmax)/2:null;
  if(s.geo_z!=null){
   const p=worldToMesh(s.wx,s.wy,s.geo_z,lo,span);
   geo.push(...p); gcol.push(...rgb);
   if(mid!=null){const q=worldToMesh(s.wx,s.wy,mid,lo,span); lines.push(...q,...p); lcol.push(...rgb,...rgb);}}
  if(mid!=null){const q=worldToMesh(s.wx,s.wy,mid,lo,span); scr.push(...q); scol.push(1,1,1);}
  if(selSpawn&&selSpawn.name===s.name&&s.poly&&s.poly.length>1){
   const h=s.geo_z!=null?s.geo_z:(mid!=null?mid:lo);
   for(let i=0;i<s.poly.length;i++){
    const pa=s.poly[i], pb=s.poly[(i+1)%s.poly.length];
    const qa=worldToMesh(pa[0],pa[1],h,lo,span), qb=worldToMesh(pb[0],pb[1],h,lo,span);
    lines.push(...qa,...qb); lcol.push(...rgb,...rgb);}}}
 function drawArr(arr,cols,mode,ps){
  if(!arr.length)return;
  gl.bindBuffer(gl.ARRAY_BUFFER,b); gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(arr),gl.STREAM_DRAW);
  gl.vertexAttribPointer(locA,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,bc); gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(cols),gl.STREAM_DRAW);
  gl.vertexAttribPointer(locC,3,gl.FLOAT,false,0,0);
  gl.uniform1f(psLoc,ps); gl.drawArrays(mode,0,arr.length/3);}
 gl.disable(gl.DEPTH_TEST);
 drawArr(lines,lcol,gl.LINES,1);
 drawArr(scr,scol,gl.POINTS,9);
 drawArr(geo,gcol,gl.POINTS,14);
 if(selSpawn&&selSpawn.region===cur){
  const s=selSpawn, mid=(s.zmin!=null&&s.zmax!=null)?(s.zmin+s.zmax)/2:s.geo_z;
  const h=s.geo_z!=null?s.geo_z:mid;
  if(h!=null){const p=worldToMesh(s.wx,s.wy,h,lo,span);
   drawArr(p,[1,1,1],gl.POINTS,20);}}
}
$('cv3').addEventListener('mousedown',e=>{drag3=true;lx3=e.clientX;ly3=e.clientY;$('cv3').style.cursor='grabbing';});
window.addEventListener('mouseup',()=>{drag3=false;$('cv3').style.cursor='grab';});
$('cv3').addEventListener('mousemove',e=>{if(!drag3||!MODE3)return;
 yaw+=(e.clientX-lx3)*0.01; pitch=Math.max(.08,Math.min(1.45,pitch+(e.clientY-ly3)*0.01));
 lx3=e.clientX;ly3=e.clientY;draw3d();});
$('cv3').addEventListener('wheel',e=>{if(!MODE3)return;e.preventDefault();
 dist=Math.max(.4,Math.min(6,dist*(e.deltaY>0?1.12:.89)));draw3d();},{passive:false});
</script></body></html>'''

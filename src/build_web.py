#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 public/index.html —— 本地服务与 GitHub Pages 共用的**同一张**页面。

以前两份页面各写各的（server.py 里的 PAGE_TEMPLATE 是本机动态版，
public/index.html 是手写的 Pages 静态版），所以两边长得不一样。
现在只有这一个模板：
  * HTML 完全一致，运行时用 location 判断自己挂在哪；
  * 去探测同源 /health：通了就是本机解析服务（显示 Cookie 状态 + 扫码登录 + 直连配置地址），
    不通就是 GitHub Pages（只显示静态索引 + gh-proxy 配置地址）。
"""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(ROOT, "public")

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>4K动漫 · 夸克接口</title>
<style>
:root{--bg:#0f1017;--card:#191b26;--line:#282b3a;--fg:#e9e9f2;--dim:#8b90a8;--acc:#7cc0ff;--ok:#5ad07a;--warn:#ffb454}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:5;background:rgba(15,16,23,.94);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:14px 18px}
h1{margin:0;font-size:17px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.meta{margin-top:6px;color:var(--dim);font-size:12px}
.bar{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input{flex:1;min-width:170px;background:var(--card);border:1px solid var(--line);color:var(--fg);padding:8px 12px;border-radius:9px;outline:none}
input:focus{border-color:var(--acc)}
button,.btn{background:var(--card);border:1px solid var(--line);color:var(--fg);padding:8px 13px;border-radius:9px;cursor:pointer;font-size:13px;text-decoration:none;display:inline-block}
button:hover,.btn:hover{border-color:var(--acc);color:var(--acc)}
nav{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
.chip{background:var(--card);border:1px solid var(--line);color:var(--dim);padding:3px 10px;border-radius:99px;font-size:12px;cursor:pointer}
.chip.on{border-color:var(--acc);color:var(--acc)}
.tag{font-size:12px;padding:3px 10px;border-radius:99px;border:1px solid var(--line);color:var(--dim)}
.tag.ok{color:var(--ok);border-color:rgba(90,208,122,.4)}
.tag.warn{color:var(--warn);border-color:rgba(255,180,84,.4)}
h2{margin:26px 18px 10px;font-size:15px;color:var(--acc);display:flex;gap:8px;align-items:baseline}
h2 small{color:var(--dim);font-weight:400;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(136px,1fr));gap:14px;padding:0 18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;overflow:hidden;transition:.15s;display:flex;flex-direction:column}
.card:hover{transform:translateY(-3px);border-color:var(--acc)}
.card img{width:100%;aspect-ratio:2/3;object-fit:cover;background:#232636;display:block}
.card .t{padding:8px 9px 3px;font-size:12.5px;line-height:1.35;min-height:34px}
.card .m{padding:0 9px 9px;color:var(--dim);font-size:11px;display:flex;justify-content:space-between;gap:6px}
.card a{color:var(--acc);text-decoration:none;font-size:11px}
#status{padding:40px 18px;text-align:center;color:var(--dim)}
footer{padding:24px 18px 40px;color:var(--dim);font-size:12px;border-top:1px solid var(--line);margin-top:30px}
footer h3{margin:0 0 8px;font-size:13px;color:var(--fg)}
.cfg{display:flex;gap:8px;align-items:center;margin:6px 0;flex-wrap:wrap}
code{background:var(--card);padding:3px 7px;border-radius:6px;border:1px solid var(--line);font-size:11.5px;word-break:break-all}
.copy{font-size:11px;padding:2px 8px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--dim);cursor:pointer}
.copy:hover{color:var(--acc);border-color:var(--acc)}
</style>
</head>
<body>
<header>
  <h1>🎬 4K动漫 · 夸克接口
    <span class="tag" id="mode">检测环境…</span>
    <span class="tag" id="ck"></span>
  </h1>
  <div class="meta" id="meta">加载中…</div>
  <div class="bar">
    <input id="q" placeholder="搜索番名，例如：孤独摇滚">
    <button id="clear">重置</button>
    <a class="btn" id="login" style="display:none" href="login">📱 扫码登录夸克</a>
    <button id="reload">🔄 刷新数据</button>
  </div>
  <nav id="nav"></nav>
</header>
<div id="status">正在加载数据…</div>
<main id="main"></main>
<footer>
  <h3>怎么用</h3>
  ① 下面第一条地址是 <b>饭太硬配置 + 4k动漫线路</b>，直接粘进「影视仓/电视 TVBox」的设置 → 配置地址即可；
  A 那条用 jar 里饭太硬自己的夸克解析（和玩偶哥哥同一条路），B 那条用我们自己的解析；
  两条都在影视仓里跑，<b>不需要</b>任何服务端解析。<br>
  <h3 style="margin-top:14px">配置地址</h3>
  <div class="cfg"><span>配置 A（饭太硬自己的夸克解析，推荐）</span><code id="cfgA"></code><span class="copy" data-t="cfgA">复制</span></div>
  <div class="cfg"><span>配置 B（我们自己的夸克解析）</span><code id="cfgB"></code><span class="copy" data-t="cfgB">复制</span></div>
  <div class="cfg"><span>旧方案（type 1 苹果CMS，需要本机 server.py）</span><code id="cfgC"></code><span class="copy" data-t="cfgC">复制</span></div>
  <div class="cfg" id="localRow" style="display:none"><span>本机直连配置</span><code id="cfgL"></code><span class="copy" data-t="cfgL">复制</span></div>
  <div class="cfg"><span>本页数据源</span><code id="cfgData"></code></div>
  <p id="hint" style="margin-top:12px"></p>
  <p>数据来自在线表格自动同步；本页只做索引，播放请在影视仓里打开 4k动漫 线路，
     或到 <a href="https://pan.quark.cn" target="_blank" rel="noreferrer" style="color:var(--acc)">夸克网盘</a> 打开对应分享。</p>
</footer>
<script>
const DIR = location.origin + location.pathname.replace(/[^/]*$/, '');
const GH  = 'https://gh-proxy.com/https://raw.githubusercontent.com/huime180/4k_anime/main/config/';
const CFG_A = GH + '4k_anime_with_fty.json';       // 配置 A：csp_Anime4KGuard（饭太硬自己的夸克解析）
const CFG_B = GH + '4k_anime_own.json';            // 配置 B：csp_Quark4K（我们自己的解析）
const CFG_C = GH + '4k_anime_with_fty_cms.json';   // 旧方案：type 1，需要本机 server.py
const state = { anime:null, meta:{}, cat:null, kw:'', live:false };

function normalizeName(s){
  s = String(s||'');
  s = s.replace(/[\[\(（【][^\]\)）】]*[\]\)）】]/g,'');
  s = s.replace(/^\s*\d{1,4}\s*[.\-_、 ]\s*/,'');
  s = s.replace(/\b(s\d{1,2}|season\s*\d{1,2})\b/gi,'');
  s = s.replace(/第\s*\d{1,3}\s*[期季部]/g,'');
  s = s.replace(/[\s\-_~·・:：,，。.、!！?？/\\|+&]+/g,'');
  return s.toLowerCase();
}
function picOf(it){
  const m = state.meta[normalizeName(it.name)] || {};
  return m.image || ('cover/' + it.id + '.png');
}
function esc(s){ return String(s).replace(/[&<>"]/g,d=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[d])); }

function card(it){
  const m = state.meta[normalizeName(it.name)] || {};
  const score = m.score ? ('★ ' + m.score) : '';
  return `<div class="card">
    <img loading="lazy" src="${esc(picOf(it))}" alt="" onerror="this.src='cover/${esc(it.id)}.png'">
    <div class="t">${esc(it.name)}</div>
    <div class="m"><span>${esc(it.resolution)} · ${esc(it.drive_name)}</span><span>${score}</span></div>
    <div class="m"><a href="${esc(it.share_url)}" target="_blank" rel="noreferrer">打开网盘</a><span>${esc(it.model)}</span></div>
  </div>`;
}
function render(){
  const main = document.getElementById('main');
  const status = document.getElementById('status');
  const kw = state.kw.trim().toLowerCase();
  let html = '', shown = 0;
  for (const cat of state.anime.categories){
    if (state.cat && cat.name !== state.cat) continue;
    let blocks = '';
    for (const g of cat.groups){
      const items = g.items.map(id => state.anime.items.find(x=>x.id===id)).filter(Boolean)
        .filter(it => !kw || it.name.toLowerCase().includes(kw));
      if (!items.length) continue;
      shown += items.length;
      blocks += (g.name ? `<h2>${esc(g.name)} <small>${items.length} 部</small></h2>` : '')
        + `<div class="grid">` + items.map(card).join('') + `</div>`;
    }
    if (blocks) html += `<h2>${esc(cat.name)} <small>${cat.count} 部</small></h2>` + blocks;
  }
  main.innerHTML = html;
  status.style.display = shown ? 'none' : 'block';
  status.textContent = shown ? '' : (kw ? '没有匹配的番剧' : '暂无数据');
}
function renderNav(){
  const nav = document.getElementById('nav');
  const cats = [{name:'', count:state.anime.total, label:'全部'}]
    .concat(state.anime.categories.map(c=>({name:c.name,count:c.count,label:c.name})));
  nav.innerHTML = cats.map(c=>`<span class="chip ${(state.cat||'')===c.name?'on':''}" data-cat="${esc(c.name)}">${esc(c.label)} (${c.count})</span>`).join('');
  nav.querySelectorAll('.chip').forEach(el=>el.onclick=()=>{ state.cat = el.dataset.cat || null; renderNav(); render(); });
}
async function env(){
  try{
    const r = await fetch('health', {cache:'no-store'});
    if (r.ok){
      const j = await r.json();
      if (j && j.ok !== false){
        state.live = true;
        document.getElementById('mode').textContent = '本机解析服务 · 在线';
        document.getElementById('mode').className = 'tag ok';
        const ck = document.getElementById('ck');
        if (j.cookie){ ck.textContent = '夸克 Cookie 已配置 ✅'; ck.className = 'tag ok'; }
        else { ck.innerHTML = '夸克 Cookie 未配置 ⚠️ <a href="login" style="color:var(--warn)">点此扫码登录</a>'; ck.className = 'tag warn'; }
        document.getElementById('login').style.display = 'inline-block';
        document.getElementById('cfgL').textContent = DIR + '4k_anime.json';
        document.getElementById('localRow').style.display = 'flex';
        document.getElementById('hint').textContent = '本页由本机解析服务提供（可选）；A/B 两条线路的解析都在影视仓里跑。';
        return;
      }
    }
  }catch(e){}
  document.getElementById('mode').textContent = 'GitHub Pages · 静态索引';
  document.getElementById('mode').className = 'tag';
  document.getElementById('hint').textContent = '当前是 GitHub Pages 上的静态索引：能浏览、能复制配置地址，'
    + '配置 A/B 的解析都在影视仓里完成，不需要服务端；这里只是索引 + 数据。';
}
(async function(){
  document.getElementById('cfgA').textContent = CFG_A;
  document.getElementById('cfgB').textContent = CFG_B;
  document.getElementById('cfgC').textContent = CFG_C;
  document.getElementById('cfgData').textContent = DIR + 'anime.json';
  document.querySelectorAll('.copy').forEach(el=>el.onclick=()=>{
    const t = document.getElementById(el.dataset.t).textContent;
    (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject())
      .then(()=>{ el.textContent='已复制'; setTimeout(()=>el.textContent='复制',1200); })
      .catch(()=>{ el.textContent='请长按选择'; });
  });
  document.getElementById('clear').onclick = ()=>{ state.kw=''; state.cat=null; document.getElementById('q').value=''; renderNav(); render(); };
  document.getElementById('q').oninput = e => { state.kw = e.target.value; render(); };
  document.getElementById('reload').onclick = ()=>location.reload();
  await env();
  try{
    const bust = '?t=' + Date.now();
    const [anime, meta] = await Promise.all([
      fetch('anime.json' + bust).then(r=>r.json()),
      fetch('meta.json').then(r=>r.json()).catch(()=>({})),
    ]);
    state.anime = anime; state.meta = meta || {};
    const withCover = anime.items.filter(it => (state.meta[normalizeName(it.name)]||{}).image).length;
    document.getElementById('meta').innerHTML =
      `共 <b>${anime.total}</b> 部 ｜ 已有封面 <b>${withCover}</b> ｜ 夸克 <b>${(anime.stat||{})['夸克']||0}</b> ｜ 同步于 ${new Date(anime.synced_at).toLocaleString('zh-CN')}`;
    renderNav(); render();
  }catch(e){
    document.getElementById('status').textContent = '数据加载失败：' + e;
  }
})();
</script>
</body>
</html>
"""


def main():
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    out = os.path.join(PUBLIC_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(HTML)
    print("✅ 生成 %s（%d 字节）—— 本机与 Pages 共用同一张页面" % (out, len(HTML.encode("utf-8"))))


if __name__ == "__main__":
    main()

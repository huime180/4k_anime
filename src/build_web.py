#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 public/index.html —— 纯静态索引页（部署在 GitHub Pages）

这个站点**不含任何解析功能**：没有服务端、没有 CMS 接口、没有扫码登录，
只做两件事：浏览表格里的番剧（封面/评分/年份/地区）+ 复制配置地址。
解析和取流都在影视仓里完成（配置里的 4k动漫 线路转发给 jar 里饭太硬原生的夸克解析）。
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
<title>4K动漫 · 线路与数据索引</title>
<style>
:root{--bg:#0f1017;--card:#191b26;--line:#282b3a;--fg:#e9e9f2;--dim:#8b90a8;--acc:#7cc0ff;--ok:#5ad07a;--warn:#ffb454}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:5;background:rgba(15,16,23,.94);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:14px 18px}
h1{margin:0;font-size:17px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
.site{color:var(--acc);text-decoration:none;font-size:12.5px;border:1px solid var(--line);padding:3px 10px;border-radius:99px;white-space:nowrap}
.site:hover{border-color:var(--acc)}
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
  <div class="top">
    <h1>4K动漫 · 线路与数据索引
      <span class="tag" id="mode">静态页面</span>
    </h1>
    <a class="site" id="site" href="https://huime180.github.io/4k_anime/">huime180.github.io/4k_anime</a>
  </div>
  <div class="meta" id="meta">加载中…</div>
  <div class="bar">
    <input id="q" placeholder="按番名检索">
    <button id="clear">清空条件</button>
    <button id="reload">重新载入</button>
  </div>
  <nav id="nav"></nav>
</header>
<div id="status">正在加载数据…</div>
<main id="main"></main>
<footer>
  <h3>使用说明</h3>
  <p>一、复制下方「配置地址」，粘贴到影视仓 / TVBox 的「配置地址」中。<br>
     二、进入线路 <b>4K动漫A┃夸克解析</b>（<code>csp_Anime4KGuard</code>）浏览与播放。</p>
  <p>该线路的目录数据取自本站静态文件；详情与播放由软件内部完成，本站不承担解析，亦无需部署服务端。
     夸克会话在影视仓「我的云盘 ┃ 配置」中登录。</p>
  <h3 style="margin-top:14px">配置地址</h3>
  <div class="cfg"><span>配置</span><code id="cfgA"></code><span class="copy" data-t="cfgA">复制</span></div>
  <div class="cfg"><span>本站数据文件</span><code id="cfgData"></code></div>
  <p id="hint" style="margin-top:12px"></p>
  <h3 style="margin-top:14px">数据来源</h3>
  <p>条目数据来自在线表格，每周一自动同步；封面与简介取自 Bangumi。
     本页仅提供索引与数据文件；播放请在影视仓内进行，或通过条目中的网盘链接打开对应分享
     （<a href="https://pan.quark.cn" target="_blank" rel="noreferrer" style="color:var(--acc)">夸克网盘</a>）。</p>
</footer>
<script>
const DIR = location.origin + location.pathname.replace(/[^/]*$/, '');
const GH  = 'https://gh-proxy.com/https://raw.githubusercontent.com/huime180/4k_anime/main/config/';
const CFG_A = GH + '4k_anime_with_fty.json';       // 唯一的配置：csp_Anime4KGuard（转发给 jar 里饭太硬的夸克解析）
const state = { anime:null, meta:{}, cat:null, kw:'' };

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
    <div class="m"><span>${esc(it.vod_year||'')} ${esc(it.vod_area||'')}</span><span>${(m.actor||'').split('、')[0]||''}</span></div>
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
function env(){
  document.getElementById('mode').textContent = '静态索引';
  document.getElementById('hint').textContent = '本站只是索引 + 静态数据（anime.json / meta.json / 封面），'
    + '不含任何解析：解析与取流都在影视仓里完成（配置里的 4k动漫 线路转发给 jar 里饭太硬原生的夸克解析，'
    + '夸克登录见「🗂我的云盘┃配置」）。';
}
(async function(){
  document.getElementById('cfgA').textContent = CFG_A;
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
      `共 <b>${anime.total}</b> 条 ｜ 含封面 <b>${withCover}</b> ｜ 含详情 `
      + `<b>${((anime._details||{}).filled)||0}</b> ｜ 夸克 <b>${(anime.stat||{})['夸克']||0}</b> `
      + `｜ 同步时间 ${new Date(anime.synced_at).toLocaleString('zh-CN')}`;
    renderNav(); render();
  }catch(e){
    document.getElementById('status').textContent = '数据载入异常：' + e;
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
    print("✅ 生成 %s（%d 字节）—— 静态索引页" % (out, len(HTML.encode("utf-8"))))


if __name__ == "__main__":
    main()

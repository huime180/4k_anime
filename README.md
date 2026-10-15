# 4k_anime · 4K 动漫夸克接口

把一份**在线更新的 4K 动漫表格**自动同步成一套影视仓（TVBox）接口：
分类、封面、剧集列表自动生成，**解析全部在影视仓 App 内完成**。

```
       在线表格 ──► GitHub Actions（每周） ──► data/anime.json + meta.json
                                                    │
                                    数据站（纯静态，可上 Cloudflare Pages）
                                    anime.json / meta.json / cover/*.png / 索引页
                                                    │
                    影视仓 载入配置 A ◄──────────────┘
                       │
                       ├─ 配置 A：csp_Anime4KGuard  →  调 jar 里**饭太硬自己的**夸克解析
                       │                              （夸父原 / 夸父智，/proxy/play/... 代理直链）
```

* 数据源：在线表格 `ec61d240-…`（Luckysheet 结构，源自 Google Sheet）
* 内容规模：**771 条 / 563 个独立夸克分享**，3 个顶层分类、19 个类别
* 运行依赖：数据站是**纯静态**；解析在 App 内完成，**不需要**本机服务
* 自动同步：GitHub Actions **每周一**拉一次表格，跟随饭太硬官方 jar 重建合并 jar，并部署数据站

---

## 一、配置地址（导入影视仓）

只维护一份：**配置 A**，线路 `csp_Anime4KGuard`（我们自己的 Guard 类，放在合并 jar 里）。

```
https://gh-proxy.com/https://raw.githubusercontent.com/huime180/4k_anime/main/config/4k_anime_with_fty.json
```
（换 jar 版本后导入要带 `?t=<时间戳>` 穿透缓存。）

| 项 | 说明 |
| --- | --- |
| 目录数据 | `ext.data` → 数据站的 `anime.json`（`ext.data2` 是 GitHub raw 兜底） |
| 分类 | 我们自己的 20 个（全部 / 每周更新 / TV动画合集 / 其余群友资源合集 / 季度档…），来自 `anime.json` |
| 详情 / 播放 | 转发给 jar 里饭太硬原生的夸克解析 `Cloud_quark`（经 `Init.loader()` 的子 DexClassLoader），线路名就是它的 **夸父原 / 夸父智**，播放地址是 app 本地代理形态 `http://127.0.0.1:<端口>/proxy/play/…` |
| 夸克会话 | 由饭太硬那套负责：在「🗂我的云盘┃配置」里扫码登录一次即可 |


## 二、数据站（只放数据，不含解析；可搬 Cloudflare Pages）

`public/` 就是数据站根目录：`anime.json` / `meta.json` / `cover/*.png` / `index.html`。

* 现在默认发布在 GitHub Pages：<https://huime180.github.io/4k_anime/>
* 搬到 Cloudflare Pages 见 [`docs/cloudflare-pages.md`](docs/cloudflare-pages.md)（三步，不用写代码）

## 三、jar（`jar/4k_anime_fty_merged.jar`）

饭太硬官方 jar（其 `spider` 字段现在伪装成 `.jpg`，带 `;md5;` 校验）+ 我们两个类：

| 类 | 作用 |
| --- | --- |
| `Anime4KGuard` | 配置 A：详情/播放原样转发给解密 dex 里的 `Cloud_quark`（经 `Init.loader()`） |

每次 Action 会 `src/fetch_upstream_jar.py` 跟随官方 jar（校验 md5、解包）→
`build_spider.sh`（javac + d8 合并）→ 提交新 jar；拿不到就保留现有 jar。
`data/upstream.json` 记录上游 jar / guard 的 md5。

## 四、可选：本机服务（旧方案 / B 的兜底）

`src/server.py` 仍然提供苹果CMS(type=1) 接口、玩偶哥哥式 `/spider/*`、`/play` 取流、
扫码登录页 `/login`、`/api/session`（给 B 兜底）等。需要时：

### 1. 本地跑起来

```bash
git clone https://github.com/huime180/4k_anime.git
cd 4k_anime

# 同步一次表格（生成 data/anime.json）
python3 src/sync_table.py

# 补全封面与简介（可跳过，首次会比较慢；结果缓存在 data/meta.json）
python3 src/enrich.py

# 生成配置
python3 src/build_config.py --base http://127.0.0.1:8787

# 启动接口服务
python3 src/server.py --port 8787
```

打开 <http://127.0.0.1:8787/> 可以直接浏览（带封面、可搜索）。

### 2. 配置夸克 Cookie（**播放必需**）

实测结论：夸克分享的「**浏览**」是匿名的——申请令牌、列目录都不需要登录；
但「**取直链**」必须登录：

```
POST /1/clouddrive/share/sharepage/save   → 401 {"message":"require login [guest]"}
POST /1/clouddrive/file/download          → 401 {"code":31001,"message":"require login [guest]"}
```

所以要么在服务器上设置环境变量：

```bash
export QUARK_COOKIE='__puus=xxx; __pus=yyy; ...'
python3 src/server.py --port 8787
```

要么复制 `config.example.json` 成 `config.json` 填进去（`config.json` 已被 `.gitignore` 忽略，**不要提交**）。

#### 推荐：在影视仓里直接操作「我的云盘┃配置」

配置加载后，分类里会多一个 **🗂我的云盘┃配置**，点进去有四项：

| 条目 | 作用 |
| --- | --- |
| ① 夸克账号状态 | 详情页直接显示昵称 / 会员等级 / 容量 |
| ② 扫码登录夸克 | **详情页封面就是二维码**，用夸克 App 扫它；服务端后台自动轮询，扫完即登录 |
| ③ 清除夸克账号 | 删掉 `config.json` 里的 Cookie，立即生效 |
| ④ 清空转存缓存 | 删除 `4k_anime/` 目录（播放要转存文件占空间；另有后台 TTL 自动清理） |

不需要打开任何网页；`/login` 网页版仍然保留，命令行也有 `python3 src/quark_login.py`。

#### 网页扫码登录（备用）

服务启动后打开：

```
http://你的地址:8787/login
```

页面上会出现一个二维码，用**手机夸克 App 右上角「扫一扫」**扫描 → 在手机上点「确认登录」→
页面会自动检测到成功，并把 Cookie 写进 `config.json`，**服务立即热生效，不用重启**。

命令行/无浏览器的场景（比如 VPS），可以直接在终端里出码：

```bash
python3 src/quark_login.py      # 二维码直接画在终端里，扫完自动保存
```

> 如果服务暴露在公网，建议设置 `export ADMIN_TOKEN=你的口令`，
> 之后要访问 `/login?key=你的口令` 才能发起扫码，避免别人替你登录。

#### 手动方式（备用）

电脑浏览器登录 <https://pan.quark.cn> → F12 → Network → 随便点一个请求 →
复制请求头里的整条 `Cookie`（至少要含 `__puus`），或者：

```bash
export QUARK_COOKIE='__puus=xxx; __pus=yyy; ...'
```

> 未配置 Cookie 时：分类、封面、剧集列表全部正常，只有点播放会返回 `401`。

### 3. 接进 TVBox

在 TVBox 的「配置地址」里填：

```
http://你的地址:8787/4k_anime.json
```

配置里的 `sites[0]` 就是本项目提供的接口，`parses` 里挂了直链解析。
如果 TVBox 版本对 `type:1` 支持不佳，也可以直接把 `sites[0].api` 指向
`/api.php/provide/vod/`，或改用 `/spider/` 系列接口。

---

## 三、部署

### Docker

```bash
docker build -t 4k-anime .
docker run -d --name 4k-anime -p 8787:8787 \
  -e QUARK_COOKIE='__puus=xxx; ...' \
  -e PUBLIC_BASE='http://你的公网IP:8787' \
  4k-anime
```

### GitHub Pages（只有浏览，不能播放）

`public/` 目录会被 Actions 发布到 Pages：`index.html` + `anime.json` + `meta.json` + 占位封面。
这是一个纯静态的**资源索引页**（搜索、分类、封面），点「打开网盘」跳到夸克分享页。
真正的「直链播放」必须由 §2 那个带 Cookie 的服务完成——Pages 跑不了 Python。

---

## 四、自动同步

`.github/workflows/sync.yml`：

* `cron: "0 4 * * 1"` —— 每周一 04:00 UTC（北京 12:00）拉一次表格。
  想更勤快就把这行改成 `"*/30 * * * *"`（每 30 分钟）或 `"0 */6 * * *"`（每 6 小时）
* 依次执行 `sync_table.py` → `enrich.py` → `build_config.py`
* 有变化就 `git commit` 回仓库，并重新发布 Pages
* 想改配置地址：仓库 **Settings → Variables → `PUBLIC_BASE`** 设成你的服务地址即可

---

## 五、接口文档

### 1. 苹果 CMS（`type:1`，通用 TVBox）

```
GET /api.php/provide/vod/?ac=list
    → {"class":[{type_id,type_name,type_pid}...], "list":[...]}

GET /api.php/provide/vod/?ac=detail&t=<type_id>&pg=1&limit=24
    → {"class":[...], "list":[...], "total":307, "page":1, "pagecount":13}

GET /api.php/provide/vod/?ac=detail&ids=<id1,id2>
    → 含 vod_play_url（真正去列夸克目录，取剧集）

GET /api.php/provide/vod/?ac=detail&wd=<关键词>     # 搜索
```

`vod_play_url` 形如 `第01集$http://host/play?pwd=…&fid=…&ft=…#第02集$…`。

### 2. 玩偶哥哥式 spider 接口

```
GET /spider/home                              → {class, list}
GET /spider/homeVideo                         → {list}
GET /spider/category?t=<type_id>&pg=1&limit=24
GET /spider/detail?ids=<id1,id2>              → 含 vod_play_url
GET /spider/search?wd=<关键词>
GET /spider/play?pwd=…&fid=…&ft=…             → {"parse":0,"url":"<直链>","playUrl":"<直链>"}
```

### 3. 取流与封面

```
GET /play?pwd=<分享ID>&fid=<文件ID>&ft=<share_fid_token>          → 302 到直链
GET /play?pwd=…&fid=…&ft=…&proxy=1                                → 服务端反代（支持 Range）
GET /cover/<item_id>.png                                          → 封面（无 Bangumi 时为占位图）
GET /health                                                       → 条目数 / Cookie 是否已配置

GET /login                                                        → 夸克扫码登录页
GET /api/qr/new                                                   → 申请二维码 {token, rid, size, rows}
GET /api/qr/poll?token=…&rid=…                                    → 轮询扫码状态；确认后自动换取并保存 Cookie
```

---

## 六、数据来源与解析说明

### 表格结构（实测）

表格是 Luckysheet 结构，横向分 3 个数据块，每块 4 列（资源名称 / 使用模型 / 分辨率 / 网盘链接）：

| 块 | 列 | 分类 | 链接特征 |
| --- | --- | --- | --- |
| 0 | 0–3 | 每周更新 | **一个季度合集共用一个分享**，番名在分享内是子文件夹 |
| 1 | 5–8 | TV动画合集 | 每行一个独立分享 |
| 2 | 10–13 | 其余群友资源合集 | 每行一个独立分享 |

两个坑，`src/sync_table.py` 里都处理了：

1. 真正的链接不在单元格文本里，而在 `sheets[0].hyperlink`（键是 `"行_列"` 字符串）；
2. 分类小标题是**整行横向合并**（`cs >= 2`）的横幅，不能只看「使用模型列为空」。

「每周更新」的条目落到网盘里是一堆 `147.药屋少女的呢喃 [组名] [2160p]` 这样的
子文件夹，所以 `src/quark.py` 会**先在分享树里按番名模糊下钻**找到对应文件夹，
再递归收集其中的视频文件（实测：`药屋少女的呢喃 S3` → 命中 `147.药屋少女的呢喃 …`）。

### 封面图（重要）

Bangumi 返回的封面在 `lain.bgm.tv`，实测这个 **图片 CDN 在部分网络下会被连接重置**
（`curl` 直接报 TLS EOF，但同一个路径换到主站域名 `bgm.tv` 就 20/20 全部可取）。
所以项目里统一把封面域名归一化成 `https://bgm.tv/...`，见 `src/enrich.py` 的 `_reachable()`。

### 夸克接口（实测）

| 步骤 | 接口 | 是否需要登录 |
| --- | --- | --- |
| 取二维码 token | `GET uop.quark.cn/cas/ajax/getTokenForQrcodeLogin` | 否 |
| 轮询扫码结果 | `GET uop.quark.cn/cas/ajax/getServiceTicketByQrcodeToken` | 否 |
| 换 Cookie | `GET pan.quark.cn/account/info?st=…&lw=scan` | 否 |
| 申请分享令牌 | `POST /1/clouddrive/share/sharepage/token` | 否 |
| 列目录 | `GET /1/clouddrive/share/sharepage/detail` | 否 |
| 转存到自己网盘 | `POST /1/clouddrive/share/sharepage/save` | **是** |
| 查询转存任务 | `GET /1/clouddrive/task` | **是** |
| **取转码流（播放用）** | `GET /1/clouddrive/file/play?fid=…&resolution=raw` | **是** |
| 取下载直链 | `POST /1/clouddrive/file/download` | **是** |

### 播放链路（踩了很多坑，结论如下）

**画质分两档，对齐玩偶哥哥的「原画 / 智能」：**

| 档位 | 来源 | 说明 |
| --- | --- | --- |
| **原画** | `POST /file/download` 直链 | **源文件本体**（4K 就是 3840×2160），MKV/MP4 原封装 |
| **智能** | `GET /file/play` 转码流 | 夸克转码（会缩分辨率，省带宽） |

> 早先只用了转码档，4K 源被缩成 1440×810（正好 1/4），看着就"糊"。现在默认原画。

```
token → detail(列目录/按番名定位文件夹) → save(转存到自己网盘)
      → task(等转存完成) → 在 4k_anime/ 里按**精确大小**定位出真正的文件 fid
      → 原画: /file/download  → dl-pc-*.drive.quark.cn
      → 智能: /file/play      → video-play-*.drive.quark.cn
      → 服务端代理拉流（必须带会话 Cookie）
```

**必须注意的几个坑（全是实测踩出来的）：**

1. **必须用 `/file/play` 或 `file/download` + PC 客户端 UA**。浏览器 UA 调 `file/download` 对大文件报
   `400 download file size limit`；换 `quark-cloud-drive/3.14.2 …` 就 200。
2. **转码/直链都要求文件在自己网盘**。`/file/play` 对分享 fid 直接 `500 inner error`。
3. **CDN 校验会话 Cookie（`__pugs`）**，缺了必 `412 Precondition Failed` ⇒
   `/play` 默认服务端代理，要 302 得显式 `direct=1`。
4. **任务返回的 fid 不可信**：`save_as_top_fids` 有时给的是**目标文件夹**的 fid；
   `/1/clouddrive/file?fids=` 这个接口**根本不认 fids 参数**（会返回别的文件）。
   所以定位文件一律走 `/file/sort` 列目录 + **按大小精确匹配**。
5. **「拿完就删」要做对**。夸克对「刚删又存同一个文件」有竞态：固定目录下 save 任务
   会返回**已删除的死 fid**（实测成功率只有 1/2）。解法是**每次转存到一个全新的一次性子目录**
   （`4k_anime/r<时间戳>/`），取到直链后立刻把整个子目录删掉 —— 实测 **4/4 成功、网盘零残留**。
   这也是玩偶哥哥能"拿完就删"的原因（它把播放地址包在 app 内置代理里，每次请求现场解析）。

> 智能档转码是**异步**的，刚转存完 `video_list` 还是空的，代码会等文件可见并重试几轮。
> 原画档是即时的，且**取到直链后立刻删除一次性子目录**，不会在你网盘里留东西。
> 智能档因为要等转码，文件会留一会儿，由后台 janitor 按 `SAVE_TTL` 清理。

---

## 七、目录结构

```
4k_anime/
├── src/
│   ├── sync_table.py     # 在线表格 → data/anime.json（分类解析）
│   ├── enrich.py         # Bangumi 封面/简介/评分 → data/meta.json（增量缓存）
│   ├── quark.py          # 夸克 token/列目录/模糊匹配/转存/取直链
│   ├── server.py         # HTTP 服务：配置 + CMS + spider + 取流 + 网页
│   ├── quark_login.py    # 夸克扫码登录（取码/轮询/换 Cookie/二维码 PNG）
│   ├── _vendor/segno/    # 内置二维码库（BSD-3-Clause），保持零依赖
│   └── build_config.py   # 生成 public/4k_anime.json 与静态站点数据
├── data/                 # 自动生成的同步结果与缓存（cache/ 不提交）
├── public/               # GitHub Pages 静态站点 + 配置地址
├── .github/workflows/sync.yml
├── config.example.json   # Cookie 配置模板（config.json 不提交）
├── Dockerfile
└── README.md
```

---

## 八、免责声明

* 本项目**只是索引与解析工具**，不存储、不分发、不转码任何视频文件；所有视频都在第三方网盘上。
* 表格中的资源由第三方整理分享，**其内容与版权状况本项目无法核实**。请仅将本项目用于
  自己有权访问的内容（例如你自己上传到网盘的个人文件），并遵守所在地区的法律与网盘服务条款。
* 把表格内容再公开分发可能与原表格「禁止二次传播」的说明相冲突，请自行评估。
* 使用夸克 Cookie 意味着以你的账号身份调用接口，请自行承担账号风险；Cookie 请勿提交到仓库。

## 九、许可

MIT（仅覆盖本项目代码，不覆盖任何第三方资源）

### 并发拉流（4K 不卡的关键）

`dl-pc-zb.drive.quark.cn` 会 CNAME 到 `w.alikunlun.com` 并解析出 **8 个节点**（阿里云 CDN），
但**单节点被限到 1~2 MB/s**。玩偶哥哥的做法（boxproxy/sing-box 日志实锤）是
**同时连 8+ 个不同节点**并发拉流。

本项目：把请求的 Range 切成 N 段（`PARALLEL_N`，默认 4），**分发到不同解析 IP**
并发拉取、按序写出 —— 不是「同一 IP 开多连接」，那样会被单节点限速。

实测（同一台机器、同一文件）：

| 方式 | 吞吐 |
| --- | --- |
| 单连接 | ~2 MB/s |
| 玩偶哥哥（对照基准） | 11.4 ~ 12.3 MB/s |
| **本项目并发（N=4）** | **24.1 MB/s** |

调参：`PARALLEL_N=6 python3 src/server.py --port 8787`

---

## 部署形态（最终）

本项目**只提供一条 4k动漫线路**，以 `type:1` CMS 的形式挂在饭太硬配置里，
排在「🗂我的云盘┃配置」之后：

* 配置地址：`config/4k_anime_with_fty_cms.json`
  （饭太硬官方 48 站 + 4k动漫 = 49 站，**饭太硬的 jar 不改动**）
* 解析取流由本项目服务提供：`python3 src/server.py --port 8787`
* 数据维护：表格每 30 分钟自动同步 -> `public/anime.json`，配置本身不用再改

> 早期尝试过的「自建 spider jar / 合并饭太硬 jar」方案已移除 ——
> 饭太硬自己的夸克解析更成熟，没必要重造。

# 4k_anime · 4K 动漫夸克接口

把一份**在线更新的 4K 动漫表格**自动同步成一套 **TVBox 可直接使用的接口**：
分类、封面、剧集列表全部自动生成，播放时由本项目的解析器把**夸克网盘分享链接**
换成可直接播放的直链——用法和「饭太硬」里的 **玩偶哥哥（玩偶哥哥┃4K弹幕）** 一个路子。

* 数据源：在线表格 `ec61d240-…`（Luckysheet 结构，源自 Google Sheet，约 10 分钟同步一次）
* 内容规模：**771 条 / 563 个独立夸克分享**，共 3 个顶层分类、19 个类别
* 项目语言：**Python 3.9+，零第三方依赖**（只用标准库）
* 自动同步：GitHub Actions **每周一**拉一次表格，重新生成数据与配置

```
表格(在线,自动更新) ──► GitHub Actions 定时同步 ──► data/anime.json + data/meta.json
                                                      │
                            TVBox ◄── /4k_anime.json ─┘
                              │
                              ├─ /api.php/provide/vod/   ← 苹果CMS(type=1) 接口
                              ├─ /spider/{home,category,detail,play}  ← 玩偶哥哥式 spider 接口
                              └─ /play?pwd=&fid=&ft=     ← 夸克分享 → 可播放直链
```

---

## 一、它解决了什么

| 需求 | 实现 |
| --- | --- |
| 直接给 TVBox 一个配置地址 | `GET /4k_anime.json`，也有一份静态版在 `public/4k_anime.json` |
| 像玩偶哥哥那样的接口 | `GET /spider/home`、`/spider/category`、`/spider/detail`、`/spider/play` |
| 通用 TVBox 也能用 | `GET /api.php/provide/vod/?ac=list` / `?ac=detail`（标准苹果CMS JSON） |
| 解析播放夸克链接 | `GET /play?pwd=<分享ID>&fid=<文件ID>&ft=<分享令牌>` → `302` 到直链，或 `&proxy=1` 反代 |
| 视频有封面 | Bangumi 封面自动匹配；匹配不到时由服务端实时生成占位封面 PNG |
| 自动同步表格 | `.github/workflows/sync.yml`，每周一自动拉取并提交 |
| 按表格分类继续分类 | `每周更新`(15 个季度子类) / `TV动画合集` / `其余群友资源合集`(含子类) |

---

## 二、快速开始

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

**拿到 Cookie 的办法**：电脑浏览器登录 <https://pan.quark.cn> → F12 → Network → 随便点一个请求 →
复制请求头里的整条 `Cookie`（至少要含 `__puus`）。

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

### 夸克接口（实测）

| 步骤 | 接口 | 是否需要登录 |
| --- | --- | --- |
| 申请分享令牌 | `POST /1/clouddrive/share/sharepage/token` | 否 |
| 列目录 | `GET /1/clouddrive/share/sharepage/detail` | 否 |
| 转存到自己网盘 | `POST /1/clouddrive/share/sharepage/save` | **是** |
| 查询转存任务 | `GET /1/clouddrive/task` | **是** |
| 取直链 | `POST /1/clouddrive/file/download` | **是** |

解析流程：`token → detail（列目录/定位番剧文件夹）→ save（转存到自己网盘）→
task（等转存完成）→ file/download（拿直链）`。转存结果做了 7 天磁盘缓存，
不会每次播放都往用户网盘里塞新文件。

---

## 七、目录结构

```
4k_anime/
├── src/
│   ├── sync_table.py     # 在线表格 → data/anime.json（分类解析）
│   ├── enrich.py         # Bangumi 封面/简介/评分 → data/meta.json（增量缓存）
│   ├── quark.py          # 夸克 token/列目录/模糊匹配/转存/取直链
│   ├── server.py         # HTTP 服务：配置 + CMS + spider + 取流 + 网页
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

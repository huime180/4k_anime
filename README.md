# 4k_anime · 4K 动漫夸克线路

把一份**在线更新的 4K 动漫表格**自动同步成影视仓（TVBox / 影视仓）能用的配置：
分类、封面、**年份 / 地区 / 导演 / 演员 / 简介**、剧集列表全部自动生成，
**解析与取流全在影视仓 App 内完成**（转发给饭太硬 jar 里原生的夸克实现），
本项目自己的站点里**不含任何解析**。

```
      在线表格 ──► GitHub Actions（每周一） ──► data/anime.json（含封面 + 详情）
                                                    │
                                纯静态数据站（GitHub Pages / Cloudflare Pages）
                                anime.json / meta.json / cover/*.png / 索引页
                                                    │
                    影视仓 导入配置 ◄───────────────┘
                      │
                      └─ 线路 🎬4K动漫A┃夸克解析（csp_Anime4KGuard）
                           目录：我们的 anime.json
                           详情/播放：经 Init.loader() 转发给 jar 里饭太硬原生的 Cloud_quark
                                     （夸父原 / 夸父智，/proxy/play/... 本地代理直链）
```

* 数据源：在线表格 `ec61d240-…`（Luckysheet 结构，源自 Google Sheet）
* 内容规模：**771 条 / 563 个独立夸克分享**，3 个顶层分类、19 个类别
* 运行依赖：**零依赖**（只用 Python 3.9+ 标准库 + 系统 curl 兜底）；数据站纯静态，不需要服务端
* 自动同步：GitHub Actions **每周一**拉表格 → 补详情 → 跟随饭太硬官方 jar 重建合并 jar → 部署数据站

---

## 一、配置地址（导入影视仓）

只维护一份配置：`config/4k_anime_with_fty.json`
（饭太硬官方配置 + 插在「🗂我的云盘┃配置」后面的一条 `4k_anime` 线路）。

```
https://gh-proxy.com/https://raw.githubusercontent.com/huime180/4k_anime/main/config/4k_anime_with_fty.json
```

（换 jar 版本后导入时建议带 `?t=<时间戳>` 穿透缓存。）

| 项 | 说明 |
| --- | --- |
| 线路 | `key: 4k_anime`，`type: 3`，`api: csp_Anime4KGuard`（我们自己的类，在合并 jar 里） |
| 目录数据 | `ext.data` → 数据站的 `anime.json`（`ext.data2` 是 GitHub raw 兜底） |
| 分类 | 我们的 20 个（全部 / 每周更新 / TV动画合集 / 其余群友资源合集 / 季度档…） |
| 详情 / 播放 | 转发给 jar 里饭太硬原生的 `Cloud_quark`（经 `Init.loader()` 拿到的子 DexClassLoader），线路名是它的 **夸父原 / 夸父智**，播放地址是 app 本地代理形态 `http://127.0.0.1:<端口>/proxy/play/…` |
| 夸克会话 | 由饭太硬那套负责：在「🗂我的云盘┃配置」里扫码登录一次即可 |

---

## 二、详情补全（年份 / 地区 / 导演 / 演员 / 简介）

这些字段现在**跟着数据走**：先把结果写进 `data/meta.json`，构建时再注入 `anime.json` 的每个条目，
所以影视仓打开详情页就有内容，**不需要 App 现场联网查**。

`src/enrich.py` 取 Bangumi 的三个接口：

| 字段 | 来源 |
| --- | --- |
| 简介 / 评分 / 放送日期 | 搜索接口 `search/subject/<名字>` 的 `summary` / `rating` |
| 年份 | `v0/subjects/<id>` 的 `date`（取前 4 位） |
| 地区 | `v0/subjects/<id>` 的 infobox（地区 / 国家）→ tags 里的国家名 → 有「放送电视台」则判为日本 |
| 导演 | `v0/subjects/<id>/persons` 里 relation 为 导演 / 总导演 / 监督 的人 → infobox 兜底 |
| 演员（声优） | `v0/subjects/<id>/characters` 里每个角色挂的 actors，去重后取前 12 位 |

几个实测细节：

* `v0` 接口的响应在部分网络下会被 CDN **中途掐断**（`IncompleteRead` / `RemoteDisconnected`），
  但同一台机器上 `curl` 稳定成功，所以 `_fetch_json()` 会**自动退到系统 curl**（CI 里用不到）。
* 增量方式：已经有封面并且 `details` 标记为真的条目直接跳过；只差详情的条目走快路径，
  **不重新搜索**（省一次请求，也不会重复下载封面/简介）。
* 只有「搜到的候选里没有名字对得上的」才记 `{"miss": true}`（真·没这部番）；
  搜索接口一个候选都没返回（多半是网络抖动）时**什么都不写**，下一轮再试，
  不会把一次抖动记成「没这部番」。
* 匹配用的搜索词会自动剥掉 `第N期/全系列/(重制版)` 之类的尾巴，
  实测覆盖率 **701/771 条**（剩下的多是 Bangumi 没有中文条目的冷门/超长标题）。

`vod_year` / `vod_area` / `vod_director` / `vod_actor` / `vod_content` 会写进 `anime.json` 的每个 item；
`csp_Anime4KGuard` 在拼详情时**优先用我们这份**，我们没有的字段再向饭太硬那条详情借。

---

## 三、合集分享：条目改指「二级目录」

「每周更新」是**一季一个大文件夹**：一个夸克分享里塞着几十部番
（10 个分享装了 216 条条目，比如 `264977a28fdd` 一个分享 26 部）。
表格里每行的链接都指向**整个分享**，所以点开哪一部看到的都是整季混在一起的剧集。

`src/subfolder.py` 在同步之后跑一次，**只干一件事**：匿名列一次目录
（申请分享令牌 + 列目录都不需要登录，纯数据、不涉及解析），
把每个条目对应的**二级目录**（分享根 → 季度合集 → **番剧目录**）拼进链接：

```
https://pan.quark.cn/s/<pwd>#/list/share/<二级目录的 fid>
```

再往下（三级目录 = 同一部的分季/分 Part）**不再细分**：同一系列放一起就行。
匹配用「表格名 + Bangumi 别名 + 季数」，别名让「一拳超人」能对上目录里的
`240.One-Punch Man`；认不出来就保持原链接（整季列出），不会乱指。

实测（当前表格 216 条合集条目）：**203 条改指成功**，13 条在它自己的分享里
确实没有这部（表格里同一部番在多个月份重复出现、旧行的链接没跟着改），保持原样。

---

## 四、数据站（只放数据，不含解析）

`public/` 就是数据站根目录：`anime.json` / `meta.json` / `cover/*.png` / `index.html`。

* 默认发布在 GitHub Pages：<https://huime180.github.io/4k_anime/>
* 搬到 Cloudflare Pages 见 [`docs/cloudflare-pages.md`](docs/cloudflare-pages.md)（三步，不用写代码）
* `index.html` 只是**纯静态索引页**：浏览封面/评分/年份/地区 + 复制配置地址；
  没有服务端、没有 CMS 接口、没有扫码登录页

---

## 五、jar（`jar/4k_anime_fty_merged.jar`）

饭太硬官方 jar（其 `spider` 字段伪装成 `.jpg`，带 `;md5;` 校验）+ 我们自己的类：

| 类 | 作用 |
| --- | --- |
| `Anime4KGuard` | 线路 `csp_Anime4KGuard`：目录用我们的静态数据，详情/播放原样转发给解密 dex 里的 `Cloud_quark`（经 `Init.loader()`），并补上详情字段 |

* 每次 Action：`src/fetch_upstream_jar.py` 跟随官方 jar（校验 md5、解包）→
  `build_spider.sh`（javac + d8 合并 + 确定性打包）→ 提交新 jar；拿不到就保留现有 jar。
* `data/upstream.json` 记录上游 jar / guard 的 md5。
* jar 会另存一份**文件名里带内容 md5** 的副本到 `jar/h/`，配置里引用的就是它 ——
  这样即使 App 缓存里是旧配置，它指向的也是和自己声明的 md5 完全相同的文件，
  不会出现「配置旧 / jar 新」→ 校验失败 → spider 不加载 → 所有线路没分类。

---

## 六、自动同步

`.github/workflows/sync.yml`，`cron: "0 4 * * 1"`（每周一 04:00 UTC / 北京 12:00）：

1. `src/sync_table.py` —— 在线表格 → `data/anime.json`
2. `src/subfolder.py` —— 合集条目改指「二级目录」（匿名列一次夸克目录）
3. `src/enrich.py` —— Bangumi 封面 + 详情 + 别名 → `data/meta.json`
4. `src/fetch_upstream_jar.py` + `build_spider.sh` —— 跟随官方 jar 重建合并 jar
5. `src/fetch_fty.py` —— 抓饭太硬官方配置、插入 `4k_anime` 线路 → `config/4k_anime_with_fty.json`
6. `src/export_data.py` —— 封面 + 详情注入 `anime.json`，导出到 `public/`
7. `src/build_web.py` + `src/check_config.py` —— 生成索引页、校验配置里的 `csp_X` 在 jar 里都有
8. 有变化就 `git commit` 回仓库，并重新发布 Pages

想更勤快就把 cron 改成 `"0 */6 * * *"`（每 6 小时）。
把数据站搬到 Cloudflare Pages 时，仓库 **Settings → Variables → `DATA_BASE`** 设成 `https://<项目>.pages.dev` 即可。

---

## 七、本地跑一遍

```bash
git clone https://github.com/huime180/4k_anime.git
cd 4k_anime

python3 src/sync_table.py        # 表格 → data/anime.json
python3 src/subfolder.py         # 合集条目改指二级目录（要联网列夸克目录，可跳过）
python3 src/enrich.py            # 封面 + 详情 → data/meta.json（首次较慢，支持 --limit N）
python3 src/export_data.py       # 注入封面/详情 → public/anime.json
python3 src/build_web.py         # 生成 public/index.html
python3 src/fetch_fty.py         # 抓饭太硬配置 + 插线路 → config/4k_anime_with_fty.json
bash    build_spider.sh          # 编译 spider 并合并进饭太硬 jar（需要 javac；缺工具链会跳过）
python3 src/check_config.py      # 自检：配置里的 csp_X 必须在 jar 里
```

详情组装的本地自检（不联网、不需要饭太硬 jar，直接检查详情 JSON 的字段与转义）：

```bash
./build_spider.sh                                                    # 先保证能编译
JDK=work/tools/jdk/data/data/com.termux/files/usr/lib/jvm/java-21-openjdk   # 有系统 JDK 就用系统 JDK
"$JDK/bin/javac" -d work/jvmout $(find spider/src -name '*.java') spider/test/CheckDetail.java
"$JDK/bin/java" -cp work/jvmout com.github.catvod.spider.CheckDetail
```

本地看数据站：`cd public && python3 -m http.server 8000`（纯静态，随便什么静态服务器都行）。

---

## 八、数据来源与实测记录

### 表格结构

Luckysheet 结构，横向分 3 个数据块，每块 4 列（资源名称 / 使用模型 / 分辨率 / 网盘链接）：

| 块 | 列 | 分类 | 链接特征 |
| --- | --- | --- | --- |
| 0 | 0–3 | 每周更新 | **一个季度合集共用一个分享**，番名在分享内是子文件夹 |
| 1 | 5–8 | TV动画合集 | 每行一个独立分享 |
| 2 | 10–13 | 其余群友资源合集 | 每行一个独立分享 |

两个坑（`src/sync_table.py` 里都处理了）：

1. 真正的链接不在单元格文本里，而在 `sheets[0].hyperlink`（键是 `"行_列"` 字符串）；
2. 分类小标题是**整行横向合并**（`cs >= 2`）的横幅，不能只看「使用模型列为空」。

### 封面图

Bangumi 返回的封面在 `lain.bgm.tv`，实测这个**图片 CDN 在部分网络下会被连接重置**
（`curl` 直接报 TLS EOF，换到主站域名 `bgm.tv` 就 20/20 全部可取）。
所以统一把封面域名归一化成 `https://bgm.tv/...`，见 `src/enrich.py` 的 `_reachable()`。

### 夸克接口（实测，现在由饭太硬 jar 里的实现来跑）

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

**画质两档**（对齐玩偶哥哥的「原画 / 智能」，由 jar 里的实现按线路名分档）：

| 档位 | 来源 | 说明 |
| --- | --- | --- |
| **原画**（夸父原） | `POST /file/download` 直链 | **源文件本体**（4K 就是 3840×2160），原封装 |
| **智能**（夸父智） | `GET /file/play` 转码流 | 夸克转码（会缩分辨率，省带宽） |

踩过的坑（供以后排查参考）：

1. **必须用 PC 客户端 UA**（`quark-cloud-drive/3.14.2 …`）：浏览器 UA 调 `file/download` 对大文件报
   `400 download file size limit`。
2. **转码/直链都要求文件在自己网盘**：`/file/play` 对分享 fid 直接 `500 inner error`。
3. **CDN 校验会话 Cookie**（`__pugs` / `__puus`），缺了必 `412 Precondition Failed`。
4. **任务返回的 fid 不可信**：`/1/clouddrive/file?fids=` 这个接口根本不认 `fids` 参数，
   定位文件要么按大小精确匹配，要么按剧集名匹配。

---

## 九、目录结构

```
4k_anime/
├── src/
│   ├── sync_table.py      # 在线表格 → data/anime.json（分类解析）
│   ├── enrich.py          # Bangumi 封面 + 详情 → data/meta.json（增量缓存）
│   ├── names.py           # 番名归一化 / 相似度（enrich 与导出共用）
│   ├── export_data.py     # data/ → public/（注入封面与详情、占位封面）
│   ├── fetch_fty.py       # 抓饭太硬配置 + 插入 4k动漫线路 → config/
│   ├── fetch_upstream_jar.py  # 跟随官方 jar（伪装成 .jpg）并校验 md5
│   ├── pack_jar.py        # 确定性打 zip（固定时间戳/顺序 → md5 稳定）
│   ├── build_web.py       # 生成纯静态索引页 public/index.html
│   └── check_config.py    # 自检：配置里的 csp_X 必须在 jar 里
├── spider/src/…/Anime4KGuard.java   # 我们的线路类（编译进合并 jar）
├── build_spider.sh        # javac + d8 + 合并打包
├── data/                  # 同步结果与缓存（anime.json / meta.json / upstream.json）
├── public/                # 数据站根目录（Pages / Cloudflare Pages）
├── jar/                   # 合并 jar（jar/h/ 里是带 md5 文件名的版本）
├── config/                # 生成的配置（4k_anime_with_fty.json）
└── .github/workflows/sync.yml
```

---

## 十、免责声明

* 本项目**只是索引工具**，不存储、不分发、不转码任何视频文件；所有视频都在第三方网盘上。
* 表格中的资源由第三方整理分享，**其内容与版权状况本项目无法核实**。请仅将本项目用于
  自己有权访问的内容（例如你自己上传到网盘的个人文件），并遵守所在地区的法律与网盘服务条款。
* 把表格内容再公开分发可能与原表格「禁止二次传播」的说明相冲突，请自行评估。
* 夸克会话由影视仓里的饭太硬实现持有，请自行承担账号风险。

## 十一、许可

MIT（仅覆盖本项目代码，不覆盖任何第三方资源）

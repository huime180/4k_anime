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

## 三、合集分享：实时解析 + 按二级目录筛

「每周更新」是**一季一个大文件夹**：一个夸克分享里塞着几十部番
（10 个分享装了 216 条条目，比如 `264977a28fdd` 一个分享 26 部）。
表格每行的链接都指向**整个分享**，所以点开哪一部看到的都是整季混在一起的剧集。

### 同步时：只列一次目录名（不列剧集）

`src/subfolder.py` 匿名列一次目录（申请分享令牌 + 列目录都**不需要登录**），
把每个条目对到它自己那个分享里的**二级目录**（分享根 → 季度合集 → **番剧目录**，
二级认不出来才往下一层看），写进 `data/anime.json`：

* `subfolder` / `subfolder_fid`：spider 筛剧集要用
* `share_url`：`https://pan.quark.cn/s/<pwd>#/list/share/<fid>`（网页上点「打开网盘」直接进那个目录）

匹配规则（按实测「近似匹配问题太多」简化过）：**两边都去掉括号（含内容）、去掉数字、去掉符号**
再比，只认「完全相同」和「互相包含」，另外剥掉「合集/全系列/剧场版」「第N期季部」「尾巴上的 S/Part/Season」。
同包内目录名有错别字的（如「失野同学」vs 目录「矢野同学」）写在
`src/subfolder_overrides.json`，脚本会**校验它必须在本包**才生效。

列目录的结果缓存在 `public/tree/<pwd>.json`（只存目录名 + `file_num` + `synced_at`）：
`file_num` 没变且不到 7 天就直接复用，整步 **3～4 秒**（否则约 2～3 分钟）。

### 运行时：由本项目从二级目录开始列目录

合集条目的详情由本项目自行列目录（匿名接口），起点为该条目对应的二级目录：

* 该目录含视频文件时，直接生成剧集列表（多数条目属于此情况，一个请求即可完成）
* 该目录下仍为子目录时（分季 / Part），继续列取其子目录（上限 30 个、深度 2）并合并
* 剧集标识形如 `4k:own:<pwd>:<上级目录 fid>:<文件 fid>`；详情结果缓存 10 分钟

不调用第三方实现解析整个分享，原因如下：其 `detailVideo` 会递归遍历分享全部目录
（例如 7 月合集为 111 个目录 / 1161 个文件），并且一次性构造全部剧集数据，
超出应用可用堆内存。本项目仅列取被展开的那一层。实测：首次打开 2.1 秒（99 集，跨多个子目录），
命中缓存后 0 毫秒。

**播放**（`4k:own:`）：点播时列取该文件所在目录一次（约 169 毫秒），同时取得当次的
`share_fid_token`，据此构造第三方实现所需的 tX JSON，由其完成转存与直链获取
（登录、转存、直链均沿用该实现）。其中 `flag`、`shareUser` 等字段取自其解析单部分享所得的真实结构。

### 覆盖情况

* 当前 216 条合集条目中，**204 条**可对应到二级目录；其余 12 条无法对应
  （6 条位于其他季度合集、2 条位于「TV动画合集」的独立分享、4 条表格未收录），
  这 12 条按整个分享列出，并在简介中标注原因。

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
* jar 会另存一份**文件名中带内容 md5** 的副本到 `jar/h/`，配置引用的即为该文件。
  这样即使客户端持有的是缓存中的旧配置，其指向的文件与自身声明的 md5 也始终一致，
  不会出现「配置与 jar 版本不匹配导致线路未加载」的情况。

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

`src/sync_table.py` 中处理了两点：

1. 真正的链接不在单元格文本里，而在 `sheets[0].hyperlink`（键是 `"行_列"` 字符串）；
2. 分类小标题为**整行横向合并**（`cs >= 2`）的横幅，不能仅依据「使用模型列为空」判断。

### 封面图

考虑到 `bgm.tv` 在部分网络下直连不稳定，`src/export_data.py` 会将封面**镜像到本仓库**
（`public/cover/bgm/<md5>.jpg`，采用 Bangumi 的 `common` 规格，约 12KB/张，合计约 8MB），
`vod_pic` 指向经 **gh-proxy** 加速的地址（与配置、jar 使用同一加速通道）。
单张下载未成功时保留原始地址，在后续同步中再次尝试；未被引用的镜像会自动清理。

图片地址在 `src/enrich.py` 的 `_reachable()` 中统一归一化为主站域名 `https://bgm.tv/...`。

### 夸克接口（实测；实际调用由饭太硬 jar 内的实现完成）

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

实现时需要注意以下四点：

1. 请求需使用 PC 客户端 UA（`quark-cloud-drive/3.14.2 …`）；使用浏览器 UA 调用 `file/download`
   处理大文件时返回 `400 download file size limit`。
2. 转码与直链均要求文件位于本人网盘：`/file/play` 对分享内的 fid 返回 `500 inner error`。
3. CDN 会校验会话 Cookie（`__pugs` / `__puus`），缺失时返回 `412 Precondition Failed`。
4. 转存任务返回的 fid 不可直接采用：`/1/clouddrive/file?fids=` 不识别 `fids` 参数，
   定位文件应按文件大小或剧集名匹配。

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

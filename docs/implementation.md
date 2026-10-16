# 实现流程

从在线表格到可导入配置的完整链路。每一步都可单独执行，也可由 `.github/workflows/sync.yml` 串联。

## 一、总览

| 步骤 | 命令 | 产物 |
| --- | --- | --- |
| 1 同步在线表格 | `python3 src/sync_table.py` | `data/anime.json` |
| 2 合集条目改指二级目录 | `python3 src/subfolder.py` | 条目增加 `subfolder` / `subfolder_fid` / `share_url`；`public/tree/<pwd>.json` |
| 3 补全封面与详情 | `python3 src/enrich.py --jobs 4` | `data/meta.json` |
| 4 重建合并 jar | `python3 src/fetch_upstream_jar.py && bash build_spider.sh` | `jar/4k_anime_fty_merged.jar`、`jar/h/<...>.<md5>.jar` |
| 5 生成配置 | `python3 src/fetch_fty.py` | `config/4k_anime_with_fty.json` |
| 6 导出静态数据 | `python3 src/export_data.py` | `public/anime.json`、`public/meta.json`、`public/cover/` |
| 7 生成主页 | `python3 src/build_web.py` | `public/index.html` |
| 8 配置自检 | `python3 src/check_config.py` | 退出码（非 0 即阻断提交） |

顺序中有两处依赖：第 4 步必须早于第 5 步（配置里写的 jar md5 要对应刚构建出的文件）；第 6 步必须早于第 7 步（主页读取导出的 JSON）。

## 二、步骤一：同步在线表格

`src/sync_table.py` 抓取在线表格（Luckysheet），横向为 3 个数据块，每块 4 列（资源名称 / 使用模型 / 分辨率 / 网盘链接）：

| 块 | 分类 | 链接特征 |
| --- | --- | --- |
| 0 | 每周更新 | 一个季度合集共用一个分享，番名在分享内是子目录 |
| 1 | TV动画合集 | 每行一个独立分享 |
| 2 | 其余群友资源合集 | 每行一个独立分享 |

两处结构细节：

* 真正的链接不在单元格文本里，而在 `sheets[0].hyperlink`（键为 `"行_列"` 字符串）；
* 分类小标题是整行横向合并（`cs >= 2`）的横幅，不能仅依据「使用模型列为空」判断。

产物 `data/anime.json` 保存分类树与条目：`id`、`name`、`model`、`resolution`、`drive`、`drive_name`、`share_url`、`pwd_id`、`row`、`block`、`type_id`、`category`、`group`、`share_count`。

## 三、步骤二：合集条目改指二级目录

`src/subfolder.py` 对「多个条目共用一个分享」（`share_count > 1`）的情况，为每个条目找出分享内对应的二级目录：

1. 取分享令牌（`sharepage/token`），匿名列出根目录；
2. 归一化目录名与条目名：去掉括号（全角与半角）及其内容、`合集` / `全系列` / `剧场版`、`第N期/季/部`、数字与符号，并去掉末尾的 `part|season|s`；
3. 打分匹配：完全相同 3 分，包含关系 2 / 1.8 分，阈值 1.0；优先二级目录，其次更深层；
4. 命中后写入 `subfolder`（目录名）、`subfolder_fid`（目录 fid）与带 `#/list/share/<fid>` 的 `share_url`。

人工映射表 `src/subfolder_overrides.json` 用于个别名称差异较大的条目，脚本会校验映射目标必须在本分享内，否则不生效。

列目录结果缓存在 `public/tree/<pwd>.json`，只含目录名、`file_num`、`synced_at`、`stoken` 与 `title`：`file_num` 未变化且未超过 7 天时直接复用，整步 3～4 秒；需要完整列取时约 2～3 分钟。仓库不保存剧集与文件清单。

## 四、步骤三：补全封面与详情

`src/enrich.py` 以 Bangumi 搜索匹配条目，再取详情页补全年份、地区、导演、演员与别名，结果增量缓存到 `data/meta.json`（`--jobs N` 控制并发）。图片地址在 `_reachable()` 中统一归一化为主站域名 `https://bgm.tv/...`。

匹配依据为表格名称、Bangumi 别名与季数；无法匹配时保留原始链接（按整个分享列出），不写入推测结果。

## 五、步骤四：重建合并 jar

```bash
python3 src/fetch_upstream_jar.py   # 跟随官方 jar（伪装成 .jpg，带 ;md5;），校验并解包到 work/merge/fty
bash build_spider.sh                # javac + d8 + 确定性打包
```

* `fetch_upstream_jar.py` 从官方配置的 `spider` 字段取地址与 md5，校验 md5 与 zip 头（`PK`），解包到 `work/merge/fty`；失败时保留现有目录并返回非 0，Action 据此跳过重建；
* `build_spider.sh` 编译 `spider/src`（`-source 8 -target 8`，桩类仅参与编译），用 d8 以 `--min-api 21` 将上游 `classes.dex` 与本项目的 `Anime4KGuard*.class` 合并，再连同 `assets/*.so`、`assets/*.guard`、`META-INF/MANIFEST.MF` 打包；
* `src/pack_jar.py` 固定条目顺序、时间戳（1980-01-01）与权限，使内容不变时 md5 不变；产物另存副本 `jar/h/4k_anime_fty_merged.<md5>.jar`，仅保留最新两份。

jar 的内部结构与适配细节见 [`fty-jar.md`](fty-jar.md)。

## 六、步骤五：生成配置

`src/fetch_fty.py` 抓取饭太硬官方配置（`/tv` 返回一张真 JPEG，`FF D9` 之后是 base64 文本，解码后为带 `//` 注释的 JSON，需要宽松解析；失败时回落到 GitHub 镜像或本地现有配置），在其基础上：

* 删除既有的 `4k_anime` 条目后重新插入到 `MDrive` 之后（幂等）；
* 写入线路 `build_line()`：`type 3`、`api csp_Anime4KGuard`、`ext.data` 指向数据站 `anime.json`、`ext.data2` 指向 GitHub raw；
* 写入顶层 `spider`：指向 `jar/h/4k_anime_fty_merged.<md5>.jar;md5;<md5>`；`gh_wrap()` 只对 github 系地址套 gh-proxy（第三方 CDN 套上会取不到）。

输出唯一的配置文件 `config/4k_anime_with_fty.json`（官方全部线路 + 本项目一条线）。

## 七、步骤六：导出静态数据

`src/export_data.py` 把 `data/` 导出为 `public/`：

* `anime.json`：分类树与条目（含封面、年份、地区、导演、演员、简介；合集条目附带二级目录信息）；
* `meta.json`：站点统计与同步时间；
* `cover/bgm/<md5>.jpg`：封面镜像（Bangumi `common` 规格，约 12KB/张），未引用的图片自动清理；
* 不导出任何剧集或文件清单。

## 八、步骤七：生成主页

`src/build_web.py` 生成 `public/index.html`：纯静态索引页，浏览器端读取 `anime.json` / `meta.json`，用于浏览封面、评分、年份、地区并复制配置地址；没有服务端、CMS 接口或登录页。

## 九、步骤八：配置自检

`src/check_config.py` 检查配置里出现的每个 `csp_X` 是否在 jar 的 dex 中存在对应类：本项目自己的类是硬错误，饭太硬自家的类缺失仅提示（官方配置中亦有此类情况，客户端会跳过该条线）。不一致时返回非 0，阻断提交。

## 十、自动同步

`.github/workflows/sync.yml` 的触发条件：每周一 04:00 UTC（北京 12:00）、手动触发、以及推送涉及 `src/**`、`spider/**` 或工作流本身的改动。

执行顺序：同步在线表格 → 合集条目改指二级目录 → 补全封面与详情 → 跟随官方 jar 重建合并 jar → 生成配置 → 导出静态数据 → 生成主页 → 自检 → 提交（无变化则跳过）→ 发布 GitHub Pages。

其中第 2、3、5 步为 `continue-on-error`，抓取类操作失败时保留上一次的结果，避免一次网络抖动导致配置不可用。

## 十一、运行时链路（影视仓内）

| 环节 | 行为 |
| --- | --- |
| 目录 | 读取 `ext.data` / `data2` / `data3`，失败时回落到 GitHub raw 的 `anime.json` |
| 详情（有二级目录） | 从该二级目录开始列目录：含视频文件时直接生成剧集；仍为子目录时继续列取（上限 30 个子目录、深度 2）并合并；结果缓存 10 分钟 |
| 详情（无二级目录） | 转发给上游的 `Cloud_quark`，失败时如实说明原因并写入下次的简介提示 |
| 播放 | 剧集标识 `4k:own:<pwd>:<上级目录 fid>:<文件 fid>`；点播时列取该文件所在目录一次（约 169 毫秒），取得当次 `share_fid_token`，构造上游所需的 tX JSON 后交由上游完成转存与直链获取 |

## 十二、本地跑一遍

```bash
python3 src/sync_table.py
python3 src/subfolder.py
python3 src/enrich.py --jobs 4
python3 src/fetch_upstream_jar.py && bash build_spider.sh
python3 src/fetch_fty.py
python3 src/export_data.py
python3 src/build_web.py
python3 src/check_config.py
```

验证线路类（需本机 JDK 与 d8；`spider/test/` 下为独立可运行的检查程序）：

| 检查 | 内容 |
| --- | --- |
| `CheckOwnPlay` | 实时列目录生成剧集（99 集约 2090 毫秒）、缓存命中（0 毫秒）、点播文件定位（约 169 毫秒） |
| `CheckDetail` | 详情补全字段是否写入 |
| `CheckSubfolder` | 二级目录匹配结果 |

## 十三、目录结构

```
4k_anime/
├── src/
│   ├── sync_table.py            # 在线表格 → data/anime.json（分类解析）
│   ├── subfolder.py             # 合集条目 → 二级目录匹配
│   ├── subfolder_overrides.json # 人工映射表（限本包生效）
│   ├── enrich.py                # Bangumi 封面与详情 → data/meta.json
│   ├── names.py                 # 番名归一化 / 相似度（enrich 与匹配共用）
│   ├── export_data.py           # data/ → public/（注入封面与详情、镜像图片）
│   ├── fetch_fty.py             # 抓饭太硬配置 + 插入 4k动漫线路
│   ├── fetch_upstream_jar.py    # 跟随官方 jar 并校验 md5
│   ├── pack_jar.py              # 确定性打包（固定时间戳 / 顺序 → md5 稳定）
│   ├── build_web.py             # 生成静态索引页 public/index.html
│   └── check_config.py          # 自检：配置里的 csp_X 必须在 jar 里
├── spider/
│   ├── src/…/Anime4KGuard.java  # 线路类（编译进合并 jar）
│   ├── src/{Init,DexClassLoader,Spider,Context}.java  # 编译用桩，不进 dex
│   └── test/                    # 独立检查程序
├── build_spider.sh              # javac + d8 + 合并打包
├── data/                        # 同步结果与缓存（anime.json / meta.json / upstream.json）
├── public/                      # 数据站根目录（GitHub Pages / Cloudflare Pages）
├── jar/h/                       # 合并 jar（文件名含内容 md5）
├── config/                      # 生成的配置（4k_anime_with_fty.json）
├── docs/                        # 文档
└── .github/workflows/sync.yml
```

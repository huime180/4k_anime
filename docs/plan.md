# 项目计划与设计

## 一、目标

把一份在线 4K 动漫表格（Luckysheet）做成影视仓 / TVBox 可直接导入的一条线路，满足：

1. 分类与条目同表格一致，条目带封面、年份、地区、导演、演员与简介；
2. 合集分享（一个季度共用一个夸克分享）按条目对应的二级目录展开剧集，而非列出整个季度；
3. 解析、登录、转存与取流沿用饭太硬 jar 自带的夸克实现，本项目不重复实现；
4. 数据静态化：站点只放 JSON 与图片，没有服务端、没有 CMS 接口、没有扫码登录页；
5. 每周自动同步一次，配置文件与 jar 的 md5 始终自洽。

## 二、设计原则

| 原则 | 含义 |
| --- | --- |
| 站点不含解析 | `public/` 只有 `anime.json`、`meta.json`、封面图片与静态索引页 |
| 单一条线路 | 配置中只维护 `key=4k_anime`、`api=csp_Anime4KGuard` 一条线 |
| 解析交给上游 | 详情与播放转发至 jar 内饭太硬原生的 `Cloud_quark`，登录态由它统一持有 |
| 不预存剧集数据 | 仓库不保存剧集 / 文件清单；同步时仅列取目录名用于匹配，运行时按需列取 |
| 同包匹配 | 合集条目只允许匹配到本分享内的二级目录，不做跨分享映射 |
| 配置与 jar 自洽 | jar 文件名含内容 md5，配置引用该文件名并同时声明 `;md5;`，任何缓存组合都指向自洽文件 |

## 三、系统构成

```
在线表格（Luckysheet）
        │  src/sync_table.py        解析分类 / 超链接
        ▼
   data/anime.json ── src/subfolder.py ──► 二级目录匹配（subfolder / subfolder_fid）
        │  src/enrich.py            Bangumi 补全封面与详情
        ▼
   data/meta.json
        │  src/export_data.py       注入封面与详情、镜像图片
        ▼
  public/（数据站）── src/build_web.py ──► public/index.html（静态索引页）

饭太硬官方 jar ── src/fetch_upstream_jar.py ──► work/merge/fty
        │  build_spider.sh（javac + d8）＋ src/pack_jar.py（确定性打包）
        ▼
  jar/h/4k_anime_fty_merged.<md5>.jar ── src/fetch_fty.py ──► config/4k_anime_with_fty.json
```

三层职责：

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 数据层 | `public/` | 分类、条目、封面、详情与二级目录索引 |
| 线路层 | `spider/src/.../Anime4KGuard.java` | 目录取自静态数据；详情 / 播放转发给上游实现 |
| 载体层 | `jar/h/*.jar` | 上游 jar（壳 dex + 原生库 + 加密 dex）与本项目的线路类合并打包 |

## 四、分阶段计划

### 已完成

* 表格同步：3 个数据块、每块 4 列；超链接取自 `sheets[0].hyperlink`，分类小标题按整行横向合并识别。
* 详情补全：Bangumi 搜索与条目详情（年份 / 地区 / 导演 / 演员 / 别名），增量缓存。
* 封面镜像：`common` 规格约 12KB/张，累计约 8MB，经 gh-proxy 加速引用。
* 合集二级目录匹配：目录名归一化 + 别名 + 季数打分；人工映射表限本包生效。
* 运行时时序：从二级目录自行列目录生成剧集列表，首次 2.1 秒，缓存 10 分钟。
* 播放链路：点播时列取文件所在目录一次，取得当次 `share_fid_token`，据此构造上游所需的 tX JSON。
* jar 合并与确定性打包：内容 md5 写入文件名，配置引用该副本。
* 自动同步：每周一 04:00 UTC 的 Action，含重建、导出、自检与发布。
* 文档：README（主页）、本计划、实现流程、饭太硬 jar 适配说明。

### 待处理

| 项 | 说明 |
| --- | --- |
| 12 条未匹配合集条目 | 6 条属于其他季度、2 条为独立分享、4 条表格未收录；当前按整个分享列出并在简介中标注 |
| 2 条 PikPak 条目 | 非夸克分享，保持原始链接 |
| `src/subfolder.py` 冗余分支 | 仍保留 `collect_share` 与 `SHARE_DIR` / `MANY_FILES` 相关代码，可清理 |
| 旧 jar 副本 | `jar/h/` 中已不被引用的历史副本，待 CDN 缓存过期后删除 |

## 五、验收口径

1. 配置可被影视仓导入：`api` 指向的类存在于 jar 的 dex 中（`src/check_config.py` 把关）。
2. 分类与条目数量同表格一致，集数与目录实际内容一致。
3. `public/` 中不含剧集 / 文件清单，仓库中无 `public/share/*.json`。
4. 配置声明的 jar md5 与所引用文件的真实 md5 一致。
5. 每周 Action 可完整跑通：同步 → 匹配 → 补全 → 重建 jar → 生成配置 → 导出 → 自检 → 提交 → 发布。

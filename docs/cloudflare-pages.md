# 数据源站点搬到 Cloudflare Pages（站点不含解析）

要的就是这个结构：

| 角色 | 在哪 | 内容 |
|---|---|---|
| 数据源站点 | **Cloudflare Pages**（或 Workers） | `anime.json`（含封面 + 年份/地区/导演/演员/简介）/ `meta.json` / `cover/*.png` / 索引页 —— **纯静态，不含任何解析** |
| 配置 | 仓库 `config/4k_anime_with_fty.json` | 线路 `csp_Anime4KGuard`：目录取数据站，详情/播放转发给 **饭太硬 jar 自带的夸克实现**（夸父原/夸父智，`/proxy/play/...`） |
| 解析 | 影视仓 App 内（jar） | **不需要**任何服务端 / 本机 Python |

## 1. 建 Pages（两分钟，不用写代码）

Cloudflare Dashboard → **Workers & Pages** → Create → **Pages** → Connect to Git →
选 `huime180/4k_anime`，分支 `main`：

* Framework preset：**None**
* Build command：**留空**
* Build output directory：**`public`**

Deploy 完就得到 `https://<项目名>.pages.dev`，直接可用：

```
https://<项目名>.pages.dev/anime.json      # 目录数据 + 封面 + 详情
https://<项目名>.pages.dev/meta.json       # 封面/简介/详情原始缓存
https://<项目名>.pages.dev/cover/<id>.png  # 占位封面
https://<项目名>.pages.dev/               # 索引页
```

## 2. 把配置里的数据地址切过去

仓库 Settings → Secrets and variables → Actions → **Variables** 加一个：

```
DATA_BASE = https://<项目名>.pages.dev
```

下一次 Action 运行（或手动 `workflow_dispatch`）会自动把配置的
`ext.data` 改成 `<DATA_BASE>/anime.json`（`ext.data2` 保留 GitHub raw 作兜底）。
不想等 CI 的话，改 `src/fetch_fty.py` 里的 `DATA_BASE` 默认值再跑一次也行。

## 3. 配置地址（导入影视仓）

```
https://gh-proxy.com/https://raw.githubusercontent.com/huime180/4k_anime/main/config/4k_anime_with_fty.json
```

（`?t=<时间戳>` 可强制穿透 CDN 缓存；jar 换版本后务必带上。）

## 4. 夸克会话从哪来

由饭太硬那套负责 —— 在影视仓的「🗂我的云盘┃配置」里扫码登录一次即可。
也可以在配置的 `ext` 里加 `"session": "https://…/Cloud-drive.txt"`
（返回 `{"quarkCookie": "<cookie>"}` 的地址）来免扫码；
注意 `Cloud-drive` 这个键是**全线路共用**的，不要往配置里塞私人地址。

## 5. 附带说明

* `public/` 只放数据 + 索引页，站点内没有服务端、没有 CMS 接口、没有扫码登录页。
* jar 每次 Action 会跟随饭太硬官方 jar（伪装成 `.jpg`、带 `;md5;`）重建，
  记录在 `data/upstream.json`；成品另存 `jar/h/4k_anime_fty_merged.<md5>.jar` 供配置引用。

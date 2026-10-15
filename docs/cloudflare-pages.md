# 数据源站点搬到 Cloudflare Pages（站点不含解析）

要的就是这个结构：

| 角色 | 在哪 | 内容 |
|---|---|---|
| 数据源站点 | **Cloudflare Pages**（或 Workers） | `anime.json` / `meta.json` / `cover/*.png` / 首页 —— **纯静态，不含任何解析** |
| 配置 A | 仓库 `config/4k_anime_with_fty.json` | 线路 `csp_Anime4KGuard`：解析用 **饭太硬 jar 自带的夸克实现**（夸父原/夸父智，`/proxy/play/...`） |
| 配置 B | 仓库 `config/4k_anime_own.json` | 线路 `csp_Quark4K`：解析用 **我们自己那套**（转存 + 取链） |
| 解析 | 影视仓 App 内（jar） | 两份配置都**不需要**本机 `server.py` |

## 1. 建 Pages（两分钟，不用写代码）

Cloudflare Dashboard → **Workers & Pages** → Create → **Pages** → Connect to Git →
选 `huime180/4k_anime`，分支 `main`：

* Framework preset：**None**
* Build command：**留空**
* Build output directory：**`public`**

Deploy 完就得到 `https://<项目名>.pages.dev`，直接可用：

```
https://<项目名>.pages.dev/anime.json      # 目录数据（771 条）
https://<项目名>.pages.dev/meta.json       # 封面/简介
https://<项目名>.pages.dev/cover/<id>.png  # 占位封面
https://<项目名>.pages.dev/               # 索引页
```

## 2. 把配置里的数据地址切过去

仓库 Settings → Secrets and variables → Actions → **Variables** 加一个：

```
DATA_BASE = https://<项目名>.pages.dev
```

下一次 Action 运行（或手动 `workflow_dispatch`）会自动把两份配置的
`ext.data` 改成 `<DATA_BASE>/anime.json`（`ext.data2` 保留 GitHub raw 作兜底）。
不想等 CI 的话，把地址发我，我直接改文件提交。

## 3. 两份配置地址（导入影视仓）

```
A（饭太硬解析）：
https://gh-proxy.com/https://raw.githubusercontent.com/huime180/4k_anime/main/config/4k_anime_with_fty.json

B（自带解析）：
https://gh-proxy.com/https://raw.githubusercontent.com/huime180/4k_anime/main/config/4k_anime_own.json
```
（`?t=<时间戳>` 可强制穿透 CDN 缓存；jar 换版本后务必带上。）

## 4. 夸克会话从哪来

* **A**：由饭太硬那套负责 —— 在「🗂我的云盘┃配置」里扫码登录（夸父）一次即可；
  也可以在 A 的 `ext` 里加 `"session": "https://…/Cloud-drive.txt"`
  （返回 `{"quarkCookie": "<cookie>"}` 的地址）来免扫码。
  注意 `Cloud-drive` 这个键是**全线路共用**的，不要往配置里塞私人地址。
* **B**：按顺序取 —— ① `ext.cookie`（手填 `__puus=…`）；
  ② **反射读饭太硬那套的登录态**（你在「我的云盘」扫码后共用单例里就有，什么都不用配）；
  ③ 可选：本机 `server.py` 的 `/api/session`。
  另外 CDN 直链必须带 `__puus`，缺了会 412，B 会自动去
  `GET https://drive-pc.quark.cn/1/clouddrive/config` 的 `Set-Cookie` 里补一个。

## 5. 附带说明

* `config/4k_anime_with_fty_cms.json` 是旧方案（type 1 苹果CMS，走本机 `server.py`），
  站点不再提供解析后它就没用了，留着只是兼容。
* `public/` 现在只放数据 + 索引页；`public/site/`（玩偶哥哥式静态页）也是纯静态。
* jar 每次 Action 会跟随饭太硬官方 jar（伪装成 `.jpg`、带 `;md5;`）重建，
  记录在 `data/upstream.json`。

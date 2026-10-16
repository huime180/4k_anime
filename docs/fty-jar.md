# 饭太硬 jar 适配与当前 jar 结构

本项目不实现夸克解析，而是把饭太硬官方 jar 原样作为载体，在里面增加一个线路类。
本文说明该 jar 的内部结构、加载方式，以及本项目如何在其中适配。

## 一、上游 jar 的形态

官方配置的 `spider` 字段即 jar 地址，但**伪装成 `.jpg`**，并带 `;md5;` 校验：

```
https://xiuxiu-pro-new.meitudata.com/posters/3c60a3e44d582b5a74fdcab19a150ad5.jpg;md5;aa8d37525617af470b3b8dfc91db8669
```

下载下来是标准 zip/jar（1281099 字节）。解包（`work/merge/fty/`）后的结构：

| 成员 | 大小 | 说明 |
| --- | --- | --- |
| `classes.dex` | 36852 字节 | 壳 dex：`dex\n035`，75 个类、528 条字符串、352 个方法 |
| `assets/ftyguard_v7.so` | 81520 字节 | 32 位原生库 |
| `assets/ftyguard_v8.so` | 102440 字节 | 64 位原生库 |
| `assets/ftyshinidie.guard` | 1161179 字节 | 加密的 dex 容器（md5 `76d0196c…`） |
| `META-INF/MANIFEST.MF` | 73 字节 | `Manifest-Version` / `Dex-Location: classes.dex` / `Created-By: dx 1.11` |

### 壳 dex 的内容

`classes.dex` 只有壳与入口，不包含任何解析实现：

* `com.github.catvod.spider.Init`（含 `Init$1`、`Init$Loader`）：加载器单例；
* `com.github.catvod.spider.DexNative`：全部为 `native` 方法；
* `com.github.catvod.spider.Proxy`；
* 约 50 个 `*Guard` 入口类（`Anime1Guard`、`BiliGuard`、`Cloud_*` 之外的各站线路名，如 `YoutubeGuard`、`ZbzGuard` 等）；
* `com.github.catvod.spider.mergeguard.*` 混淆类。

这些入口类的方法体只是转发，真正的实现不在这个 dex 里。

### 加密 dex 容器

`assets/ftyshinidie.guard` 前两字节为 `PK`，但**不是标准 zip**（直接按 zip 打开会失败），
其内容中包含 `META-INF/`、`classes.dex` 等条目线索，需由原生库解密后才能加载。
解密后的子 dex 包含 69 个 `com.github.catvod.spider` 类，即真正的实现，例如：

* `Cloud_quark`、`Cloud_uc`、`Cloud_baidu`、`Cloud_ali`（网盘类）；
* `merge.N0`、`merge.Tq`（夸克分享的令牌与详情模型）；
* 其余各站实现（`Bili`、`Hmys`、`Youtube` 等）。

## 二、加载链路

依据反编译的 `Init` 与 `DexNative`，运行时顺序如下：

1. **释放原生库**：`DexNative` 的静态块按 `Build.CPU_ABI` 是否包含 `64` 选择
   `assets/ftyguard_v8.so` 或 `ftyguard_v7.so`，释放到应用缓存目录下的
   `.ftyfnw<10 位随机串>`（同时清理旧的 `.ftyfnw*`），随后 `System.load()`。
2. **解密并构造子 dex 加载器**：`Init.init(context)` → `DexNative.getLoader(context)`，
   返回值为 `dalvik.system.DexClassLoader`（其内容即解密后的子 dex）。
3. **取用**：
   * `Init.loader()` 返回该 `DexClassLoader`，签名为 `()Ldalvik/system/DexClassLoader;`；
   * `Init.getSpider(String)` → `DexNative.getSpider(loader(), name)`；
   * `DexNative` 另提供 `decrypt` / `encrypt` / `proxyInvoke` / `noxSign` / `native_ting_md5` / `calcResult`。

由于子 dex 只能经 `Init.loader()` 取得，外部实现（包括本项目）**只能通过该入口**加载真身，
不能自行 `loadClass` 通过类名直接加载。

## 三、本项目的合并 jar 结构

`build_spider.sh` 产出的 `jar/4k_anime_fty_merged.jar`（md5 `db97a722…`，1294899 字节）：

| 成员 | 来源 | 说明 |
| --- | --- | --- |
| `classes.dex` | 上游 `classes.dex` + 本项目类，经 d8 合并 | 64352 字节，79 个类、905 条字符串 |
| `assets/ftyguard_v7.so` | 上游原样拷贝 | md5 与上游一致 |
| `assets/ftyguard_v8.so` | 上游原样拷贝 | md5 与上游一致 |
| `assets/ftyshinidie.guard` | 上游原样拷贝 | md5 与上游一致 |
| `META-INF/MANIFEST.MF` | 上游原样拷贝 | 内容一致 |

类数 79 = 上游 75 个 + 本项目 4 个（`Anime4KGuard` 及其内部类 `J`、`P`、`Json`）。
上游的 75 个类（含入口壳与 `Init`、`DexNative`）全部保留，因此官方所有 `csp_*Guard` 线路
在本项目的配置里照旧可用；本项目只是多了一个类，并将其写在 `spider` 指向的 jar 中。

构建过程：

```bash
python3 src/fetch_upstream_jar.py   # 校验 md5 / PK 头，解包到 work/merge/fty
bash build_spider.sh                # javac（-source 8 -target 8）→ d8 --min-api 21 → 打包
```

打包由 `src/pack_jar.py` 完成：成员排序、时间戳固定为 1980-01-01、`ZIP_DEFLATED`、权限 0644，
因此**内容不变时 md5 不变**。产物另存一份文件名含内容 md5 的副本到 `jar/h/`（仅保留最新两份），
配置的 `spider` 字段引用的就是该副本：

```
https://gh-proxy.com/https://raw.githubusercontent.com/huime180/4k_anime/main/jar/h/4k_anime_fty_merged.db97a72201dcdb8af6a3edffbcb29fb8.jar;md5;db97a72201dcdb8af6a3edffbcb29fb8
```

文件名带 md5 的目的：客户端会分别缓存配置与 jar，两者刷新时间不一致。固定文件名会出现
「配置声明旧 md5、线上已是新 jar」的组合，导致校验不通过、线路未加载；每个内容对应唯一文件名后，
任何缓存组合都指向与自身声明一致的文件。

## 四、适配要点

1. **桩的方法签名必须与真身逐字一致**。编译用桩
   `spider/src/com/github/catvod/spider/Init.java` 声明的是
   `public static dalvik.system.DexClassLoader loader()`；若写成 `ClassLoader`，
   编译出的调用点描述符为 `()Ljava/lang/ClassLoader;`，与真身的
   `()Ldalvik/system/DexClassLoader;` 不匹配，运行时报 `NoSuchMethodError`。
2. **桩类不进入 dex**。`build_spider.sh` 只收集 `out/com/github/catvod/spider/Anime4KGuard*.class`，
   `Init`、`Spider`、`Context`、`DexClassLoader` 四个桩仅用于编译（放在 `spider/src/` 下）。
3. **不覆盖上游类名**。本项目只新增 `Anime4KGuard`（上游没有这个类名），避免与壳 dex 的类冲突。
4. **真身取用方式**：

   ```java
   ClassLoader cl = Init.loader();                                  // 子 dex 加载器
   Class<?> c = cl.loadClass("com.github.catvod.spider.Cloud_quark");
   Spider quark = (Spider) c.newInstance();
   quark.init(appContext, ext);                                     // ext 原样透传
   ```

   详情优先走 `quark.detailContent(Arrays.asList(share))`；未取得播放列表时退到
   `detailVideo(Arrays.asList(share), name)`，再用 `merge.Tq.v(ef)` 转成 JSON。
   播放走 `quark.playerContent(flag, id)`，线路名（`夸父原` / `夸父智`）与播放地址原样透传。
5. **字段照抄，不自行构造**。本项目构造的 tX JSON 以真身解析单部分享所得的结构为模板，
   `flag`、`shareUser` 等字段保持其原值。
6. **跟随上游更新**。`src/fetch_upstream_jar.py` 每次从官方配置重新取地址与 md5 校验并解包，
   `data/upstream.json` 记录 url、md5、字节数、`classes.dex` 大小、guard 的 md5 与大小、抓取时间；
   抓取或校验失败时保留现有 `work/merge/fty` 并返回非 0，Action 据此跳过重建，配置始终可用。
7. **加载失败的常见表现**：`Init.loader()` 返回空、或子 dex 中没有目标类时，
   本项目会记录原因，表现为详情为空并在简介中提示；官方线路则表现为无分类。

## 五、上游实现使用的夸克接口（实测）

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

### 画质两档

对齐玩偶哥哥的「原画 / 智能」，由 jar 内的实现按线路名分档：

| 档位 | 来源 | 说明 |
| --- | --- | --- |
| **原画**（夸父原） | `POST /file/download` 直链 | **源文件本体**（4K 就是 3840×2160），原封装 |
| **智能**（夸父智） | `GET /file/play` 转码流 | 夸克转码（会缩分辨率，省带宽） |

### 调用注意

实测需要注意以下四点：

1. 请求需使用 PC 客户端 UA（`quark-cloud-drive/3.14.2 …`）；使用浏览器 UA 调用 `file/download`
   处理大文件时返回 `400 download file size limit`。
2. 转码与直链均要求文件位于本人网盘：`/file/play` 对分享内的 fid 返回 `500 inner error`。
3. CDN 会校验会话 Cookie（`__pugs` / `__puus`），缺失时返回 `412 Precondition Failed`。
4. 转存任务返回的 fid 不可直接采用：`/1/clouddrive/file?fids=` 不识别 `fids` 参数，
   定位文件应按文件大小或剧集名匹配。

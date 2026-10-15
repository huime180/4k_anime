package com.github.catvod.spider;

import android.content.Context;
import com.github.catvod.crawler.Spider;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 4K动漫 · 配置 A：**解析全部交给饭太硬 jar 自己那套夸克实现**（配置里写 csp_Anime4KGuard）
 *
 * 详情页字段（年份 / 地区 / 导演 / 演员 / 简介）优先用我们静态 anime.json 里带的
 * （由 src/enrich.py 从 Bangumi 补全，构建时写进每个条目）；我们没有的字段
 * 就从饭太硬那条详情里借，两边都没有才留空。
 *
 * 目录数据是我们自己的静态 anime.json（可以挂在 Cloudflare Pages，站点本身不含解析）。
 * 详情/播放则直接调用解密 dex 里的 com.github.catvod.spider.Cloud_quark：
 *   * 线路名、播放地址原样透传 -> 就是玩偶哥哥那种
 *     http://127.0.0.1:<端口>/proxy/play/夸父盘/... 代理直链，播放器不需要 header；
 *   * 会话（Cookie / 扫码登录）由饭太硬那套负责：在「🗂我的云盘┃配置」里扫码最省事；
 *   * 可选：ext 里给 "session": "http://…/Cloud-drive.txt"（返回 {"quarkCookie": …} 的地址），
 *     就会用它初始化一次，省掉扫码。不给就纯靠 jar 自己的登录态。
 */
public class Anime4KGuard extends Spider {

    private static final String PC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            + "AppleWebKit/537.36 (KHTML, like Gecko) quark-cloud-drive/3.14.2 "
            + "Chrome/112.0.5615.165 Electron/24.4.1 Safari/537.36";

    // 目录数据回退链：ext.data / data2 / data3 -> GitHub raw（站点只有静态数据，没有服务端）
    private static final String RAW_DATA =
            "https://raw.githubusercontent.com/huime180/4k_anime/main/public/anime.json";
    private final java.util.List<String> extraUrls = new java.util.ArrayList<String>();

    private Context appContext = null;   // 转发给饭太硬自己的实现用
    private String extRaw = "";          // ext 原文，原样透传
    private String sessionUrl = "";      // 可选：ext.session，指向返回 {"quarkCookie": …} 的地址
    private Spider realQuark = null;     // 当前生效的 Cloud_quark 实例
    private Spider realPlain = null;     // 用配置 ext 原样初始化的实例（优先）
    private Spider realSession = null;   // 配置里没会话时，用 ext.session 补出来的实例
    private boolean plainTried = false, sessionTried = false;
    private String realReason = "未尝试";   // 饭太硬原生那条失败的原因（写进详情，方便排查）
    private String dataUrl = "";
    private boolean subfolderOnly = true;  // 合集分享只留本条目对应的那个目录（ext.subfolder=false 可关）
    String filterNote = "";                // 筛选结果，写进简介，在 App 里看得见
    private J theirsMeta = null;         // 饭太硬那条详情的第一个条目（字段回填用）

    private static String dataCache = null;
    private static long dataCacheAt = 0;

    /* ===================== Spider 生命周期 ===================== */

    @Override
    public void init(Context context, String ext) {
        try {
            appContext = context;
            extRaw = ext == null ? "" : ext.trim();
            if (extRaw.startsWith("{")) {
                J o = J.parse(extRaw);
                dataUrl = o.str("data");
                String d2 = o.str("data2"), d3 = o.str("data3");
                if (!d2.isEmpty()) extraUrls.add(d2);
                if (!d3.isEmpty()) extraUrls.add(d3);
                sessionUrl = o.str("session");
                if (o.get("subfolder") != null && "false".equalsIgnoreCase(o.str("subfolder"))) {
                    subfolderOnly = false;
                }
            } else if (!extRaw.isEmpty()) {
                dataUrl = extRaw;
            }
            extraUrls.add(RAW_DATA);
        } catch (Throwable t) {
            // 配置坏了不该让 app 崩
        }
    }

    @Override
    public void init(Context context) { }

    /** 目录数据（静态 anime.json），带 10 分钟内存缓存 */
    private J data() throws Exception {
        long now = System.currentTimeMillis();
        if (dataCache != null && now - dataCacheAt < 600000) return J.parse(dataCache);
        java.util.List<String> urls = new java.util.ArrayList<String>();
        if (dataUrl != null && !dataUrl.isEmpty()) urls.add(dataUrl);
        urls.addAll(extraUrls);
        Exception last = null;
        for (String u : urls) {
            try {
                String body = http("GET", u, null, null, null);
                if (body != null && body.contains("\"items\"")) {
                    dataCache = body;
                    dataCacheAt = now;
                    return J.parse(dataCache);
                }
                last = new Exception("源不含 items: " + u);
            } catch (Exception e) {
                last = e;
            }
        }
        if (dataCache != null) return J.parse(dataCache);
        throw last == null ? new Exception("no data source") : last;
    }

    /* ===================== 首页 / 分类 / 搜索 ===================== */

    @Override
    public String homeContent(boolean filter) {
        try {
            J d = data();
            // 分类要**全给**（和 A 版 CMS 一致），只给 type_pid=0 的顶层会让 app 里少一大截
            StringBuilder sb = new StringBuilder("{\"class\":[{\"type_id\":\"4k_all\",\"type_name\":\"全部\"}");
            for (J c : d.arr("classes")) {
                sb.append(",{\"type_id\":").append(J.q(c.str("type_id")))
                  .append(",\"type_name\":").append(J.q(c.str("type_name")))
                  .append(",\"type_pid\":").append(J.q(c.str("type_pid").isEmpty() ? "0" : c.str("type_pid")))
                  .append("}");
            }
            List<J> all = d.arr("items");
            sb.append("],\"list\":[");
            for (int i = 0; i < Math.min(24, all.size()); i++) {
                if (i > 0) sb.append(",");
                sb.append(brief(all.get(i)));
            }
            sb.append("]}");
            return sb.toString();
        } catch (Throwable t) {
            return "{\"class\":[{\"type_id\":\"4k_all\",\"type_name\":\"全部\"}],\"list\":[]}";
        }
    }

    @Override
    public String categoryContent(String tid, String pg, boolean filter, HashMap<String, String> ext) {
        try {
            int page = 1;
            try { page = Math.max(1, Integer.parseInt(pg)); } catch (Throwable ignore) { }
            int limit = 24;
            J d = data();
            List<J> hits = new ArrayList<J>();
            for (J it : d.arr("items")) {
                if ("4k_all".equals(tid)) { hits.add(it); continue; }
                String top = it.str("type_id_top"), own = it.str("type_id");
                if (tid.equals(top) || tid.equals(own)) hits.add(it);
            }
            int total = hits.size();
            int from = (page - 1) * limit, to = Math.min(total, from + limit);
            StringBuilder sb = new StringBuilder();
            sb.append("{\"page\":").append(page)
              .append(",\"pagecount\":").append(total / limit + 1)
              .append(",\"limit\":").append(limit)
              .append(",\"total\":").append(total)
              .append(",\"list\":[");
            for (int i = from; i < to; i++) {
                if (i > from) sb.append(",");
                sb.append(brief(hits.get(i)));
            }
            sb.append("]}");
            return sb.toString();
        } catch (Throwable t) {
            return "{\"page\":1,\"pagecount\":1,\"limit\":24,\"total\":0,\"list\":[]}";
        }
    }

    @Override
    public String searchContent(String key, boolean quick) {
        try {
            J d = data();
            StringBuilder sb = new StringBuilder("{\"list\":[");
            int n = 0;
            for (J it : d.arr("items")) {
                if (it.str("name").toLowerCase().contains(key.toLowerCase())) {
                    if (n++ > 0) sb.append(",");
                    sb.append(brief(it));
                    if (n >= 60) break;
                }
            }
            return sb.append("]}").toString();
        } catch (Throwable t) {
            return "{\"list\":[]}";
        }
    }

    private String brief(J it) {
        return "{\"vod_id\":\"4k:" + Json.esc(it.str("id")) + "\""
                + ",\"vod_name\":" + J.q(it.str("name"))
                + ",\"vod_pic\":" + J.q(it.str("vod_pic"))
                + ",\"vod_remarks\":" + J.q(it.str("resolution") + " · " + it.str("drive_name"))
                + ",\"type_name\":" + J.q(it.str("group").isEmpty() ? it.str("category") : it.str("group"))
                + ",\"vod_year\":" + J.q(it.str("vod_year"))
                + "}";
    }

    /* ===================== 详情 / 播放：全交给饭太硬原生 ===================== */

    @Override
    public String detailContent(List<String> ids) {
        try {
            String id = ids.get(0).replace("4k:", "");
            J item = null;
            for (J it : data().arr("items")) if (it.str("id").equals(id)) { item = it; break; }
            if (item == null) return fail("找不到该条目");
            String pwd = item.str("pwd_id");
            if (pwd.isEmpty()) {
                return oneItem(item, id, "诊断", "点我看原因$4k:diag",
                        "该条目不是夸克分享（网盘：" + item.str("drive_name") + "），这条线只吃夸克分享");
            }

            // 链接优先用条目里的 share_url：合集条目在同步时已经改指到「二级目录」
            // （https://pan.quark.cn/s/<pwd>#/list/share/<fid>），这样只会列这一部番
            String shareUrl = item.str("share_url");
            if (shareUrl.isEmpty()) shareUrl = "https://pan.quark.cn/s/" + pwd;
            String[] theirs = realDetail2(shareUrl, item.str("name"));
            if (theirs == null) {
                // 失败也返回一条「诊断条目」：原因写在简介里，App 里能直接看到
                // （否则 list 为空，客户端只显示「视频线路加载失败」，什么都查不到）
                String why = "解析没出播放列表：" + realReason
                        + "。可先到「🗂我的云盘┃配置」里扫码登录夸克，或在 ext 里加 session 地址";
                return oneItem(item, id, "诊断", "点我看原因$4k:diag", why);
            }
            return detailJson(item, id, subfolder(item, theirs));
        } catch (Throwable t) {
            return fail("详情解析失败：" + t);
        }
    }

    /** 拼详情 JSON：我们的静态数据（Bangumi 补全）优先，缺的字段向饭太硬那条详情借 */
    String detailJson(J item, String id, String[] theirs) {
        {
            String year = pick(item.str("vod_year"), "vod_year");
            String area = pick(item.str("vod_area"), "vod_area");
            String director = pick(item.str("vod_director"), "vod_director");
            String actor = pick(item.str("vod_actor"), "vod_actor");
            String remarks = pick(item.str("vod_remarks"), "vod_remarks");
            if (remarks.isEmpty()) remarks = item.str("resolution") + " · " + item.str("drive_name");
            String typeName = pick(item.str("group"), "type_name");
            return "{\"list\":[{\"vod_id\":\"4k:" + Json.esc(id) + "\""
                    + ",\"vod_name\":" + J.q(item.str("name"))
                    + ",\"vod_pic\":" + J.q(item.str("vod_pic"))
                    + ",\"vod_year\":" + J.q(year)
                    + ",\"vod_area\":" + J.q(area)
                    + ",\"vod_director\":" + J.q(director)
                    + ",\"vod_actor\":" + J.q(actor)
                    + ",\"vod_remarks\":" + J.q(remarks)
                    + ",\"type_name\":" + J.q(typeName)
                    + ",\"vod_content\":" + J.q(content(item, theirs[0].replace("$$$", "/")))
                    + ",\"vod_play_from\":" + J.q(theirs[0])
                    + ",\"vod_play_url\":" + J.q(theirs[1])
                    + "}]}";
        }
    }

    /** 我们没有的详情字段，向饭太硬那条详情借（它有就用它的） */
    /* ============ 合集分享：只留本条目对应的那个目录 ============
     *
     * 「每周更新」是**一季一个大文件夹**（10 个分享装了 216 条条目），
     * 饭太硬那套会把整季的剧集全列出来 —— 链接里带 #/list/share/<fid> 也没用，
     * 它只取 /s/<pwd> 那一段（实测）。所以这里在详情里把不属于本条目的剧集筛掉。
     *
     * 数据侧（src/subfolder.py）已经在同步时把每个条目对应的**二级目录名**写进
     * item["subfolder"]，这里拿它 + 番名/别名去比每一集的标签和它 id 里的
     * parent / vodName / fileName；一个都认不出来就原样返回（宁可多列，不能点开是空的）。
     */
    String[] subfolder(J item, String[] theirs) {   // 包内可见，方便本地自检
        filterNote = "";
        if (!subfolderOnly || theirs == null || theirs.length < 2) return theirs;
        if (item.str("share_count").isEmpty() || "1".equals(item.str("share_count"))) return theirs;
        try {
            String folder = item.str("subfolder");
            List<String> probes = new ArrayList<String>();
            if (!folder.isEmpty()) probes.add(norm(folder));
            for (String piece : item.str("vod_alias").split("[、/／|]")) {
                String n = norm(piece);
                if (n.length() >= 2 && !probes.contains(n)) probes.add(n);
            }
            for (String n : aliases(item.str("name"))) {
                if (!probes.contains(n)) probes.add(n);
            }
            if (probes.isEmpty()) return theirs;

            String[] got = pickEpisodes(theirs, probes);
            if (got[2].equals("0")) {
                String sample = firstLabels(theirs[1], 2);
                filterNote = "合集子目录：没认出《" + item.str("name") + "》对应的目录，先按全部 " + got[3]
                        + " 集列出（示例：" + sample + "）";
                if (!folder.isEmpty()) filterNote += "（数据里的目录名：" + folder + "）";
                return theirs;
            }
            filterNote = "合集子目录：已只保留《" + item.str("name") + "》对应的目录"
                    + (folder.isEmpty() ? "" : "「" + folder + "」") + "（" + got[3] + " 集 -> " + got[2] + " 集）";
            return new String[]{got[0], got[1]};
        } catch (Throwable t) {
            filterNote = "合集子目录：筛选出错(" + t + ")，按全部集数列出";
            return theirs;
        }
    }

    /** 按一组关键词筛剧集：返回 {线路名, 播放列表, 留下的集数, 总集数} */
    String[] pickEpisodes(String[] theirs, List<String> probes) {
        String[] flags = theirs[0].split("\\$\\$\\$");
        String[] groups = theirs[1].split("\\$\\$\\$");
        StringBuilder outFlags = new StringBuilder(), outUrls = new StringBuilder();
        int total = 0, kept = 0;
        for (int g = 0; g < groups.length; g++) {
            String flag = g < flags.length ? flags[g] : "";
            boolean wholeGroup = matches(flag, probes, false);
            StringBuilder eps = new StringBuilder();
            int inGroup = 0;
            for (String ep : groups[g].split("#")) {
                if (ep.isEmpty()) continue;
                total++;
                if (wholeGroup || episodeMatches(ep, probes)) {
                    if (inGroup++ > 0) eps.append("#");
                    eps.append(ep);
                    kept++;
                }
            }
            if (inGroup > 0) {
                if (outUrls.length() > 0) { outFlags.append("$$$"); outUrls.append("$$$"); }
                outFlags.append(flag);
                outUrls.append(eps);
            }
        }
        return new String[]{outFlags.toString(), outUrls.toString(), String.valueOf(kept), String.valueOf(total)};
    }

    /** 番名的几种写法：名字里的「A/B」拆开当别名，另外带上数据里的别名（Bangumi 的） */
    List<String> aliases(String name) {
        List<String> out = new ArrayList<String>();
        for (String piece : name.split("[/／|]")) {
            String norm = norm(piece);
            if (norm.length() >= 2 && !out.contains(norm)) out.add(norm);
        }
        String whole = norm(name);
        if (whole.length() >= 2 && !out.contains(whole)) out.add(0, whole);
        return out;
    }

    /** 这一集是不是属于本条目：标签 + id JSON 里的 parent/vodName/file_name 都比一遍 */
    boolean episodeMatches(String ep, List<String> probes) {
        int cut = ep.lastIndexOf('$');
        String label = cut > 0 ? ep.substring(0, cut) : ep;
        if (matches(label, probes, true)) return true;
        if (cut > 0 && ep.charAt(cut + 1) == '{') {
            try {
                J meta = J.parse(ep.substring(cut + 1));
                if (matches(meta.str("parent"), probes, false)) return true;
                if (matches(meta.str("vodName"), probes, false)) return true;
                if (matches(meta.str("file_name"), probes, false)) return true;
            } catch (Throwable ignore) { }
        }
        return false;
    }

    /** 认目录：整名包含优先；标签再宽松一点（前 8 个字） */
    boolean matches(String text, List<String> probes, boolean loose) {
        String hay = norm(text);
        if (hay.isEmpty()) return false;
        for (String a : probes) {
            if (hay.contains(a) || (a.contains(hay) && hay.length() >= 2)) return true;
            if (loose && a.length() >= 8 && hay.contains(a.substring(0, 8))) return true;
        }
        return false;
    }

    /** 认不出来时把前几集标签写进简介，方便排查 */
    String firstLabels(String urls, int n) {
        StringBuilder sb = new StringBuilder();
        for (String group : urls.split("\\$\\$\\$")) {
            for (String ep : group.split("#")) {
                if (ep.isEmpty()) continue;
                int cut = ep.lastIndexOf('$');
                String label = cut > 0 ? ep.substring(0, cut) : ep;
                if (sb.length() > 0) sb.append(" / ");
                sb.append(label.length() > 36 ? label.substring(0, 36) : label);
                if (--n <= 0) return sb.toString();
            }
        }
        return sb.toString();
    }

    /** 番名归一化：剥括号、剥「147.」序号、剥 S2/第2期、去标点空格，转小写 */
    static String norm(String s) {
        if (s == null) return "";
        String t = s.replaceAll("[\\[\\(（【][^\\]\\)）】]*[\\]\\)）】]", "");
        t = t.replaceAll("^\\s*\\d{1,4}\\s*[.\\-_、 ]\\s*", "");
        t = t.replaceAll("(?i)(?<![a-z0-9])(s\\d{1,2}|season\\s*\\d{1,2})(?![0-9])", "");
        t = t.replaceAll("第\\s*[0-9一二三四五六七八九十]{1,3}\\s*[期季部]", "");
        t = t.replaceAll("[\\s\\-_~·・:：,，。.、!！?？/\\\\|+&]+", "");
        return t.toLowerCase();
    }

    private String pick(String mine, String key) {
        if (mine != null && !mine.isEmpty()) return mine;
        if (theirsMeta == null) return "";
        return theirsMeta.str(key);
    }

    /** 简介：我们的 Bangumi 简介 + 画质/修复/解析备注（有分享链接也附上） */
    private String content(J item, String parseFrom) {
        StringBuilder sb = new StringBuilder();
        String mine = item.str("vod_content");
        if (!mine.isEmpty()) {
            sb.append(mine).append("\n\n");
        } else if (theirsMeta != null) {
            String other = theirsMeta.str("vod_content");
            if (!other.isEmpty()) sb.append(other).append("\n\n");
        }
        if (!filterNote.isEmpty()) sb.append(filterNote).append("\n");
        sb.append("画质 ").append(item.str("resolution"))
          .append(" ｜ 修复 ").append(item.str("model"))
          .append(" ｜ 解析：饭太硬原生(").append(parseFrom).append(")");
        String share = item.str("share_url");
        if (!share.isEmpty()) sb.append("\n分享链接：").append(share);
        return sb.toString();
    }

    /** 返回单条条目，把原因写进简介（失败时也能在 App 里看到原因） */
    private String oneItem(J item, String id, String from, String play, String content) {
        return "{\"list\":[{\"vod_id\":\"4k:" + Json.esc(id) + "\""
                + ",\"vod_name\":" + J.q("⚠️ " + item.str("name"))
                + ",\"vod_pic\":" + J.q(item.str("vod_pic"))
                + ",\"vod_year\":" + J.q(item.str("vod_year"))
                + ",\"vod_area\":" + J.q(item.str("vod_area"))
                + ",\"vod_content\":" + J.q(content)
                + ",\"vod_play_from\":" + J.q(from)
                + ",\"vod_play_url\":" + J.q(play)
                + "}]}";
    }

    @Override
    public String playerContent(String flag, String id, List<String> vipFlags) {
        if (id != null && id.startsWith("4k:diag")) {
            return media("这是诊断线路：请回到该条目的简介看失败原因（详情页上方文字）");
        }
        Spider rq = real();
        if (rq == null) return media("拿不到饭太硬的夸克实现：" + realReason);
        try {
            return rq.playerContent(flag, id, vipFlags);   // 原样转发，含 夸父原/夸父智 的分档逻辑
        } catch (Throwable t) {
            return media("取流失败：" + t.getMessage());
        }
    }

    private String fail(String msg) {
        return "{\"list\":[],\"msg\":" + J.q(msg) + "}";
    }

    private String media(String msg) {
        return "{\"parse\":0,\"playUrl\":\"\",\"url\":\"\",\"msg\":" + J.q(msg) + "}";
    }

    /* ===== 直接调用饭太硬 jar 里的夸克实现（解密 dex，只能经 Init.loader() 拿） ===== */

    private Spider build(String ext) {
        try {
            ClassLoader cl = Init.loader();
            if (cl == null) { realReason = "Init.loader() 返回空"; return null; }
            Class<?> c = cl.loadClass("com.github.catvod.spider.Cloud_quark");
            Spider s = (Spider) c.newInstance();
            s.init(appContext, ext);
            return s;
        } catch (Throwable t) {
            realReason = "加载 Cloud_quark 失败：" + t;
            return null;
        }
    }

    private String[] detailOf(Spider rq, String share, String name) {
        if (rq == null) return null;
        try {
            // 第一条路：它的 detailContent（内部剧名传空）
            String json = rq.detailContent(java.util.Arrays.asList(share));
            String[] got = parsePlayList(json);
            if (got != null) return got;
            realReason = "detailContent 没出播放列表";

            // 第二条路：detailVideo(list, 剧名) + Tq.v(ef)（反射；和玩偶 Pan.panList 同一条路）
            Object ef = rq.getClass()
                    .getMethod("detailVideo", List.class, String.class)
                    .invoke(rq, java.util.Arrays.asList(share), name == null ? "" : name);
            if (ef == null) { realReason += "；detailVideo 返回空（多为未扫码登录）"; return null; }
            ClassLoader cl = Init.loader();
            Class<?> tq = cl.loadClass("com.github.catvod.spider.merge.Tq");
            String json2 = (String) tq.getMethod("v", ef.getClass()).invoke(null, ef);
            got = parsePlayList(json2);
            if (got != null) return got;
            realReason += "；detailVideo+Tq.v 也没出播放列表";
            return null;
        } catch (Throwable t) {
            realReason = "调用它的详情抛异常：" + t;
            return null;
        }
    }

    /** 从它的详情 JSON 里取 {vod_play_from, vod_play_url} */
    private String[] parsePlayList(String json) {
        try {
            if (json == null || json.length() < 20) return null;
            List<J> list = J.parse(json).arr("list");
            if (list.isEmpty()) return null;
            J first = list.get(0);
            String from = first.str("vod_play_from");
            String url = first.str("vod_play_url");
            if (from.isEmpty() || url.isEmpty()) return null;
            theirsMeta = first;          // 留一份：我们没有的详情字段可以向它借
            return new String[]{from, url};
        } catch (Throwable t) {
            return null;
        }
    }

    /**
     * 解析分享，两条路：
     *  1) `Cloud_quark.detailContent(["https://pan.quark.cn/s/<pwd>"])` —— 但它内部是
     *     `detailVideo(list, "")`，**剧名传空**；有些分享（整季合集/多层目录）靠剧名才找对目录；
     *  2) 所以失败时再走一次 `detailVideo(list, 剧名)` + `Tq.v(ef)`（反射调用，和玩偶哥哥
     *     `Pan.panList` 用的是同一个方法、同一份参数），把 Ef 转成 JSON 再取播放列表。
     * 会话优先用配置里的 ext 原样初始化（用户扫码登录的会话就在共用单例里）；
     * 拿不到才用 ext.session 补一次。
     */
    private String[] realDetail(String pwd, String name) {
        return realDetail2("https://pan.quark.cn/s/" + pwd, name);
    }

    /** 同 realDetail，但直接给完整分享链接（合集条目带 #/list/share/<fid>） */
    private String[] realDetail2(String share, String name) {
        if (!plainTried) {
            plainTried = true;
            realPlain = build(extRaw.isEmpty() ? "{}" : extRaw);
        }
        String[] r = detailOf(realPlain, share, name);
        if (r != null) { realQuark = realPlain; return r; }

        if (!sessionUrl.isEmpty() && !sessionTried) {
            sessionTried = true;
            realSession = build("{\"Cloud-drive\":" + J.q(sessionUrl) + "}");
            r = detailOf(realSession, share, name);
            if (r != null) {
                realQuark = realSession;
                realReason = "配置里没有会话，用了 ext.session";
                return r;
            }
        }
        return null;
    }

    private Spider real() {
        if (realQuark != null) return realQuark;
        if (!plainTried) {
            plainTried = true;
            realPlain = build(extRaw.isEmpty() ? "{}" : extRaw);
        }
        if (realPlain != null) { realQuark = realPlain; return realQuark; }
        if (!sessionUrl.isEmpty() && !sessionTried) {
            sessionTried = true;
            realSession = build("{\"Cloud-drive\":" + J.q(sessionUrl) + "}");
            realQuark = realSession;
        }
        return realQuark;
    }

    /* ===================== HTTP / JSON 极简实现 ===================== */

    private static String http(String method, String url, String body, String extraHeader, String referer)
            throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(25000);
        c.setRequestMethod(method);
        c.setRequestProperty("User-Agent", PC_UA);
        c.setRequestProperty("Accept", "application/json, text/plain, */*");
        c.setRequestProperty("Referer", referer == null ? "https://pan.quark.cn/" : referer);
        if (extraHeader != null) {
            for (String line : extraHeader.split("\n")) {
                int i = line.indexOf(':');
                if (i > 0) c.setRequestProperty(line.substring(0, i).trim(), line.substring(i + 1).trim());
            }
        }
        if (body != null) {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            OutputStream os = c.getOutputStream();
            os.write(body.getBytes("UTF-8"));
            os.flush();
            os.close();
        }
        int code = c.getResponseCode();
        InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
        if (in == null) throw new Exception("HTTP " + code);
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
        in.close();
        c.disconnect();
        String s = new String(bo.toByteArray(), "UTF-8");
        if (code >= 400) throw new Exception("HTTP " + code + " " + (s.length() > 160 ? s.substring(0, 160) : s));
        return s;
    }

    private static String enc(String s) throws Exception { return URLEncoder.encode(s, "UTF-8"); }

    /** 极简 JSON：够用即可（对象/数组/字符串/数字/布尔），不依赖 org.json */
    static class J {
        private final Object v;
        J(Object v) { this.v = v; }

        static J parse(String s) { P p = new P(s); p.ws(); return new J(p.val()); }

        Object get(String k) {
            if (v instanceof Map) {
                Object o = ((Map<?, ?>) v).get(k);
                return o instanceof J ? ((J) o).v : o;
            }
            return null;
        }
        J node(String k) {
            if (v instanceof Map) {
                Object o = ((Map<?, ?>) v).get(k);
                if (o instanceof J) return (J) o;
            }
            return null;
        }
        String str(String k) {
            Object o = get(k);
            if (o == null) return "";
            if (o instanceof String) return (String) o;
            return String.valueOf(o);
        }
        String raw() { return v instanceof String ? (String) v : String.valueOf(v); }

        @SuppressWarnings("unchecked")
        List<J> arr(String k) {
            Object o = get(k);
            if (o instanceof List) return (List<J>) o;
            return new ArrayList<J>();
        }
        List<J> arr() { return v instanceof List ? (List<J>) v : new ArrayList<J>(); }

        static String q(String s) { return s == null ? "\"\"" : "\"" + Json.esc(s) + "\""; }

        /** 递归下降解析器 */
        static class P {
            private final String s; private int i = 0;
            P(String s) { this.s = s; }
            void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }
            Object val() {
                ws();
                if (i >= s.length()) return null;
                char c = s.charAt(i);
                if (c == '{') { i++; Map<String, J> m = new HashMap<String, J>(); ws();
                    if (i < s.length() && s.charAt(i) == '}') { i++; return m; }
                    while (i < s.length()) {
                        ws(); String k = (String) val(); ws();
                        if (i < s.length() && s.charAt(i) == ':') i++;
                        m.put(k, new J(val())); ws();
                        if (i < s.length() && s.charAt(i) == ',') { i++; continue; }
                        if (i < s.length() && s.charAt(i) == '}') { i++; break; }
                        break;
                    }
                    return m; }
                if (c == '[') { i++; List<J> l = new ArrayList<J>(); ws();
                    if (i < s.length() && s.charAt(i) == ']') { i++; return l; }
                    while (i < s.length()) {
                        l.add(new J(val())); ws();
                        if (i < s.length() && s.charAt(i) == ',') { i++; continue; }
                        if (i < s.length() && s.charAt(i) == ']') { i++; break; }
                        break;
                    }
                    return l; }
                if (c == '"') { i++; StringBuilder sb = new StringBuilder();
                    while (i < s.length()) { char ch = s.charAt(i++);
                        if (ch == '\\' && i < s.length()) { char e = s.charAt(i++);
                            if (e == 'n') sb.append('\n'); else if (e == 't') sb.append('\t');
                            else if (e == 'r') sb.append('\r'); else if (e == 'u' && i + 4 <= s.length()) {
                                sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4;
                            } else sb.append(e);
                        } else if (ch == '"') break; else sb.append(ch); }
                    return sb.toString(); }
                int st = i;
                while (i < s.length() && ",}] \t\r\n".indexOf(s.charAt(i)) < 0) i++;
                String t = s.substring(st, i);
                if ("true".equals(t)) return Boolean.TRUE;
                if ("false".equals(t)) return Boolean.FALSE;
                if ("null".equals(t)) return null;
                return t;
            }
        }
    }

    static class Json {
        static String esc(String s) {
            if (s == null) return "";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '"': sb.append("\\\""); break;
                    case '\\': sb.append("\\\\"); break;
                    case '\n': sb.append("\\n"); break;
                    case '\r': sb.append("\\r"); break;
                    case '\t': sb.append("\\t"); break;
                    default:
                        if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                        else sb.append(c);
                }
            }
            return sb.toString();
        }
    }
}

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
import java.util.concurrent.ConcurrentHashMap;

/**
 * 4K动漫 · 配置 B：**解析用我们自己这套**（配置里写 csp_Quark4K）
 *
 * 目录数据 = 静态 anime.json（挂 Cloudflare Pages 也行，站点本身不含解析），
 * 播放解析全在影视仓里跑：分享令牌 -> 列目录 -> 转存到自己网盘 -> 取流。
 *   * 夸父原 = file/download 源文件直链（全分辨率，要播放器带 header）
 *   * 夸父智 = /file/play 出来的转码 m3u8（播放器最友好）
 * 名字沿用饭太硬那套（夸父原/夸父智），两边互换也不会踩它的 contains 判断。
 *
 * Cookie 来源，按顺序取第一个可用的：
 *   1) ext.cookie（手填，和「之前」一样）
 *   2) **饭太硬那套的登录态**：用户在「🗂我的云盘┃配置」扫码后，共用单例里就有会话，
 *      这里反射读出来用 —— 于是不依赖任何外部服务；
 *   3) 本机 server.py 的 /api/session（可选兜底，离网就跳过）。
 * 取流还要求 __puus，缺了 CDN 一律 412，所以 ensurePuus() 会自动去
 * GET /1/clouddrive/config 的 Set-Cookie 里补一个。
 */
public class Quark4K extends Spider {

    private static final String PC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            + "AppleWebKit/537.36 (KHTML, like Gecko) quark-cloud-drive/3.14.2 "
            + "Chrome/112.0.5615.165 Electron/24.4.1 Safari/537.36";
    private static final String API = "https://drive-pc.quark.cn/1/clouddrive";
    private static final String SAVE_DIR = "4k_anime";

    // 数据源回退链：ext 里的 data / data2 / data3 -> 本机服务 -> GitHub raw
    private static final String LOCAL_DATA = "http://192.168.1.102:8787/anime.json";
    private static final String RAW_DATA =
            "https://raw.githubusercontent.com/huime180/4k_anime/main/public/anime.json";
    private final java.util.List<String> extraUrls = new java.util.ArrayList<String>();

    private String cookie = "";
    private String dataUrl = "";
    private String serverUrl = "";
    private static final String SERVER_DATA = "http://192.168.1.102:8787";
    private String saveDirFid = null;
    private long puusTryAt = 0;

    private static String dataCache = null;
    private static long dataCacheAt = 0;
    private final Map<String, String> stokenCache = new ConcurrentHashMap<String, String>();
    private final Map<String, String> savedCache = new ConcurrentHashMap<String, String>();
    private final Map<String, Integer> savedAt = new ConcurrentHashMap<String, Integer>();

    /* ===================== Spider 生命周期 ===================== */

    @Override
    public void init(Context context, String ext) {
        try {
            if (ext != null && ext.trim().startsWith("{")) {
                J o = J.parse(ext);
                cookie = o.str("cookie");
                dataUrl = o.str("data");
                // 多源回退：跨境时 GitHub Pages 常拉不到，这里可配备用地址
                String d2 = o.str("data2"), d3 = o.str("data3");
                if (!d2.isEmpty()) extraUrls.add(d2);
                if (!d3.isEmpty()) extraUrls.add(d3);
            } else if (ext != null && !ext.trim().isEmpty()) {
                dataUrl = ext.trim();
            }
            // 兜底源：本机服务 -> GitHub raw
            extraUrls.add(LOCAL_DATA);
            extraUrls.add(RAW_DATA);
            if (cookie != null && !cookie.contains("pus")) cookie = "";
            // cookie 的其余来源是懒解析（可能那时用户才刚扫码登录），见 ensureCookie()
        } catch (Throwable t) {
            // 配置坏了不该让 app 崩
        }
    }

    /**
     * 取会话 Cookie：ext.cookie -> 饭太硬自己的登录态 -> 本机 server.py。
     * 懒调用（详情/播放前各一次），因为用户可能是在 app 里刚扫码登录的。
     */
    private synchronized void ensureCookie() {
        if (!authed() || cookie.startsWith("\u2190") || cookie.contains("贴")) {
            String ck = jarSessionCookie();
            if (ck == null || ck.isEmpty()) ck = fetchCookieFromServer();
            if (ck != null && !ck.isEmpty()) cookie = ck;
        }
        ensurePuus();
    }

    /**
     * 从饭太硬那套的登录态里读 cookie。
     *
     * 用户在「🗂我的云盘┃配置」里扫码（夸父扫码登录）后，会话在解密 dex 的
     * N0 单例里；我们租同一个单例，所以直接反射把含 "__pus" 的字符串字段捞出来即可。
     */
    private String jarSessionCookie() {
        try {
            ClassLoader cl = Init.loader();
            if (cl == null) return "";
            Object inst = cl.loadClass("com.github.catvod.spider.merge.N0")
                    .getMethod("Zm").invoke(null);
            if (inst == null) return "";
            for (java.lang.reflect.Field f : inst.getClass().getDeclaredFields()) {
                if (f.getType() != String.class) continue;
                try {
                    f.setAccessible(true);
                    Object v = f.get(inst);
                    if (v instanceof String && ((String) v).contains("__pus") && ((String) v).length() > 40) {
                        return (String) v;
                    }
                } catch (Throwable ignore) { }
            }
        } catch (Throwable ignore) { }
        return "";
    }

    /**
     * 补上 __puus —— 夸克 CDN 直链的通行证。
     *
     * 2026-10 实测：GET /1/clouddrive/config 会在 Set-Cookie 里下发
     * __puus=<...>; Max-Age=86400。缺了它，file/download 直链和 /file/play
     * 出来的转码 m3u8 一律「412 Precondition Failed」——现象就是「条目能显示、
     * 一点播放就失败」。所以每次播放前都确保带上。
     */
    private void ensurePuus() {
        if (cookie == null || cookie.isEmpty()) return;
        if (cookie.contains("__puus=")) return;
        long now = System.currentTimeMillis();
        if (now - puusTryAt < 60000) return;      // 失败退避 60s
        puusTryAt = now;
        try {
            HttpURLConnection c = (HttpURLConnection)
                    new URL(API + "/config?pr=ucpro&fr=pc").openConnection();
            c.setConnectTimeout(12000);
            c.setReadTimeout(15000);
            c.setRequestProperty("User-Agent", PC_UA);
            c.setRequestProperty("Referer", "https://pan.quark.cn/");
            c.setRequestProperty("Cookie", cookie);
            Map<String, List<String>> hs = c.getHeaderFields();
            StringBuilder add = new StringBuilder();
            for (Map.Entry<String, List<String>> e : hs.entrySet()) {
                if (e.getKey() == null || !"set-cookie".equalsIgnoreCase(e.getKey())) continue;
                for (String line : e.getValue()) {
                    int eq = line.indexOf('=');
                    if (eq <= 0) continue;
                    int semi = line.indexOf(';');
                    String name = line.substring(0, eq).trim();
                    String val = line.substring(eq + 1, semi < 0 ? line.length() : semi).trim();
                    if (name.isEmpty() || val.isEmpty() || cookie.contains(name + "=")) continue;
                    add.append("; ").append(name).append('=').append(val);
                }
            }
            InputStream in = c.getInputStream();     // 响应体没用，但需要走完请求
            if (in != null) in.close();
            if (add.length() > 0) cookie = cookie + add.toString();
        } catch (Throwable ignore) {
            // 拿不到就照旧，播放时会如实报错
        }
    }

    @Override
    public void init(Context context) { }

    private boolean authed() { return cookie != null && cookie.length() > 0; }

    /** 从服务端 /api/session 取当前夸克会话（省得把 cookie 手写进配置） */
    private String fetchCookieFromServer() {
        java.util.List<String> servers = new java.util.ArrayList<String>();
        if (serverUrl != null && !serverUrl.isEmpty()) servers.add(serverUrl);
        servers.add(SERVER_DATA.length() > 0 ? SERVER_DATA : "");
        servers.add("http://192.168.1.102:8787");
        for (String base : servers) {
            if (base == null || base.isEmpty()) continue;
            try {
                String body = http("GET", base.replaceAll("/+$", "") + "/api/session",
                        null, null, null);
                if (body != null && body.contains("cookie")) {
                    String ck = J.parse(body).str("cookie");
                    if (ck != null && ck.contains("pus")) return ck;
                }
            } catch (Throwable ignore) { }
        }
        return "";
    }

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
        if (dataCache != null) return J.parse(dataCache);   // 有旧缓存就用旧的
        throw last == null ? new Exception("no data source") : last;
    }

    /* ===================== 首页 / 分类 / 搜索 ===================== */

    @Override
    public String homeContent(boolean filter) {
        try {
            J d = data();
            // 分类全给（别只给 type_pid=0 的顶层，否则 app 里分类少一大截）
            StringBuilder sb = new StringBuilder("{\"class\":[{\"type_id\":\"4k_all\",\"type_name\":\"全部\"}");
            for (J c : d.arr("classes")) {
                sb.append(",{\"type_id\":").append(J.q(c.str("type_id")))
                  .append(",\"type_name\":").append(J.q(c.str("type_name")))
                  .append(",\"type_pid\":").append(J.q(c.str("type_pid").isEmpty() ? "0" : c.str("type_pid")))
                  .append("}");
            }
            // 首页也要给出条目，否则客户端看起来「4k动漫为空」
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
                + "}";
    }

    /* ===================== 详情：列剧集 ===================== */

    @Override
    public String detailContent(List<String> ids) {
        try {
            ensureCookie();
            String id = ids.get(0).replace("4k:", "");
            J item = null;
            for (J it : data().arr("items")) if (it.str("id").equals(id)) { item = it; break; }
            if (item == null) return fail("找不到该条目");
            String pwd = item.str("pwd_id");
            if (pwd.isEmpty()) return fail("该条目不是夸克分享（网盘：" + item.str("drive_name") + "）");
            String stoken = stoken(pwd);
            List<J> root = listDir(pwd, stoken, "0");
            String startFid = "0";
            // 整季合集：按番名下钻找对应文件夹
            if (!root.isEmpty()) startFid = findDir(pwd, stoken, root, item.str("name"));
            List<J> eps = new ArrayList<J>();
            collect(pwd, stoken, startFid, eps, 0, 600);
            StringBuilder raw = new StringBuilder(), smart = new StringBuilder();
            for (int i = 0; i < eps.size(); i++) {
                J f = eps.get(i);
                String label = "第" + String.format("%02d", i + 1) + "集";
                String base = "4k:play:" + pwd + ":" + f.str("fid") + ":" + f.str("share_fid_token");
                if (i > 0) { raw.append("#"); smart.append("#"); }
                raw.append(label).append("$").append(base).append(":r");
                smart.append(label).append("$").append(base).append(":s");
            }
            // 两档：原画＝源文件直链（全分辨率）；智能＝夸克转码流（HLS，最省事能播）
            // —— 对齐玩偶哥哥的「夸父原 / 夸父智」，档位名用配置里的 原画 / 智能
            String playUrl = eps.isEmpty() ? "" : raw + "$$$" + smart;
            return "{\"list\":[{\"vod_id\":\"4k:" + Json.esc(id) + "\""
                    + ",\"vod_name\":" + J.q(item.str("name"))
                    + ",\"vod_pic\":" + J.q(item.str("vod_pic"))
                    + ",\"vod_content\":" + J.q("画质 " + item.str("resolution")
                        + " ｜ 修复 " + item.str("model") + " ｜ 共 " + eps.size() + " 集")
                    + ",\"vod_play_from\":\"夸父原$$$夸父智\",\"vod_play_url\":" + J.q(playUrl)
                    + "}]}";
        } catch (Throwable t) {
            return fail("详情解析失败：" + t.getMessage());
        }
    }

    /** 在分享树里按番名找最匹配的子目录（整季合集场景） */
    /** 统一的失败返回：必须是合法 JSON，否则客户端会报「JSON解析失败」 */
    private String fail(String msg) {
        return "{\"list\":[],\"msg\":" + J.q(msg) + "}";
    }

    private String findDir(String pwd, String stoken, List<J> roots, String name) throws Exception {
        for (J d : roots) {
            if (!"true".equals(d.str("dir")) && !"1".equals(d.str("dir"))) continue;
            String score = d.str("file_name");
            if (norm(score).contains(norm(name)) || norm(name).contains(norm(score))) return d.str("fid");
            List<J> sub = listDir(pwd, stoken, d.str("fid"));
            for (J s : sub) {
                if (("true".equals(s.str("dir")) || "1".equals(s.str("dir")))
                        && (norm(s.str("file_name")).contains(norm(name))
                            || norm(name).contains(norm(s.str("file_name"))))) {
                    return s.str("fid");
                }
            }
            return d.str("fid"); // 只有一个包装目录时直接下钻
        }
        return "0";
    }

    private static String norm(String s) {
        return s == null ? "" : s.replaceAll("\\[[^\\]]*\\]", "").replaceAll("^\\s*\\d+[.、\\-_ ]*", "")
                .replaceAll("(?i)\\bs\\d{1,2}\\b", "").replaceAll("[\\s\\-_·:：,，。.、]+", "").toLowerCase();
    }

    private void collect(String pwd, String stoken, String fid, List<J> out, int depth, int limit) throws Exception {
        if (depth > 5 || out.size() >= limit) return;
        for (J f : listDir(pwd, stoken, fid)) {
            if (out.size() >= limit) return;
            String nm = f.str("file_name").toLowerCase();
            if ("true".equals(f.str("dir")) || "1".equals(f.str("dir"))) {
                collect(pwd, stoken, f.str("fid"), out, depth + 1, limit);
            } else if (nm.endsWith(".mp4") || nm.endsWith(".mkv") || nm.endsWith(".ts")
                    || nm.endsWith(".m2ts") || nm.endsWith(".avi") || nm.endsWith(".mov")) {
                out.add(f);
            }
        }
    }

    /* ===================== 播放：转存 + 取流（原画 / 智能） ===================== */

    @Override
    public String playerContent(String flag, String id, List<String> vipFlags) {
        try {
            ensureCookie();
            if (!authed()) return media("没有夸克会话：先给 ext.cookie（__puus=…），或在「🗂我的云盘┃配置」里扫码登录夸克");
            String[] p = id.split(":");   // 4k:play:<pwd>:<fid>:<share_token>[:r|s]
            if (p.length < 5) return media("播放地址格式错误");
            String pwd = p[2], fid = p[3], token = p[4];
            String q = p.length > 5 ? p[5] : ("智能".equals(flag) ? "s" : "r");
            ensurePuus();
            String own = saveToTemp(pwd, fid, token);
            String url, how;
            if ("s".equals(q)) {
                // 智能：夸克转码流（m3u8）。玩偶哥哥的「夸父智」就是这条路：
                // /file/play 拿 video_list，转码是异步的所以要轮询几次。
                url = transcodeUrl(own);
                how = "智能·转码流";
                if (url == null || url.isEmpty()) {
                    url = downloadUrl(own);          // 转码还没好 -> 用源文件直链兜底
                    how = "智能→原画兜底";
                }
            } else {
                // 原画：file/download 直链，就是源文件本身（全分辨率、码率最高）
                how = "原画·源文件直链";
                url = "";
                try {
                    url = downloadUrl(own);
                } catch (Throwable t) {
                    url = transcodeUrl(own);         // 大文件被限/取链失败 -> 转码流兜底
                    how = "原画→智能兜底(" + t.getMessage() + ")";
                }
            }
            if (url == null || url.isEmpty()) return media("取流失败：" + how);
            return "{\"parse\":0,\"playUrl\":\"\",\"url\":" + J.q(url)
                    + ",\"header\":" + J.q(sessionHeader()) + "}";
        } catch (Throwable t) {
            return media("取流失败：" + t.getMessage());
        }
    }

    /** 夸克转码播放流：/file/play -> data.video_list[].url（m3u8，播放器最友好） */
    private String transcodeUrl(String ownFid) {
        for (int attempt = 0; attempt < 6; attempt++) {
            for (String res : new String[]{"raw", "low"}) {
                try {
                    String u = playUrl(ownFid, res);
                    if (u != null && !u.isEmpty()) return u;
                } catch (Throwable ignore) { }
            }
            try { Thread.sleep(attempt < 3 ? 1200 : 2500); } catch (InterruptedException ignore) { }
        }
        return "";
    }

    private String playUrl(String ownFid, String resolution) throws Exception {
        String q = "?pr=ucpro&fr=pc&fid=" + enc(ownFid) + "&resolution=" + enc(resolution);
        J r = J.parse(http("GET", API + "/file/play" + q, null, ckHeader(), null));
        J d = r.node("data");
        if (d == null) return "";
        for (J it : d.arr("video_list")) {
            String u = it.str("url");
            if (!u.isEmpty()) return u;
        }
        return "";
    }

    private String media(String msg) {
        return "{\"parse\":0,\"playUrl\":\"\",\"url\":\"\",\"msg\":" + J.q(msg) + "}";
    }

    private String sessionHeader() {
        ensurePuus();
        StringBuilder sb = new StringBuilder();
        String sc = sessionCookie();
        if (sc != null && !sc.isEmpty()) sb.append("Cookie: ").append(sc).append("\n");
        sb.append("User-Agent: ").append(PC_UA).append("\n");
        sb.append("Referer: https://pan.quark.cn/");
        return sb.toString();
    }

    /** 取流会话 Cookie（含 __puus） */
    private String sessionCookie() { return cookie; }

    /** 统一的会话请求头：夸克的转存/取链/列目录都必须带登录 Cookie，否则 401 require login [guest] */
    private String ckHeader() {
        ensurePuus();
        return "Cookie: " + cookie;
    }

    /* ===================== 夸克接口 ===================== */

    private String stoken(String pwd) throws Exception {
        String hit = stokenCache.get(pwd);
        if (hit != null) return hit;
        String body = "{\"pwd_id\":" + J.q(pwd) + ",\"passcode\":\"\"}";
        J r = J.parse(http("POST", API + "/share/sharepage/token?pr=ucpro&fr=pc", body, ckHeader(), null));
        J d = r.node("data");
        if (r.get("status") == null || !"200".equals(r.str("status")) || d == null)
            throw new Exception("分享不可用 " + r.str("message"));
        String st = d.str("stoken");
        stokenCache.put(pwd, st);
        return st;
    }

    private List<J> listDir(String pwd, String stoken, String fid) throws Exception {
        String q = "?pr=ucpro&fr=pc&pwd_id=" + enc(pwd) + "&stoken=" + enc(stoken)
                + "&pdir_fid=" + enc(fid) + "&force=0&_page=1&_size=200&_fetch_total=1"
                + "&_sort=" + enc("file_type:asc,file_name:asc");
        J r = J.parse(http("GET", API + "/share/sharepage/detail" + q, null, ckHeader(), null));
        J d = r.node("data");
        return d == null ? new ArrayList<J>() : d.arr("list");
    }

    /** 转存到一次性子目录，返回转存后的 fid（玩偶哥哥同款做法） */
    private String saveToTemp(String pwd, String fid, String token) throws Exception {
        String ck = "saved_" + pwd + "_" + fid;
        String hit = savedCache.get(ck);
        Integer at = savedAt.get(ck);
        if (hit != null && at != null && System.currentTimeMillis() / 1000 - at < 1800) return hit;

        String dir = ensureDir();
        String sub = createDir(dir, "r" + (System.currentTimeMillis() / 1000));
        String body = "{\"fid_list\":[" + J.q(fid) + "],\"fid_token_list\":[" + J.q(token) + "]"
                + ",\"to_pdir_fid\":" + J.q(sub) + ",\"pwd_id\":" + J.q(pwd)
                + ",\"stoken\":" + J.q(stoken(pwd)) + ",\"pdir_fid\":\"0\""
                + ",\"pdir_save_all\":false,\"exclude_fids\":[],\"scene\":\"link\"}";
        J r = J.parse(http("POST", API + "/share/sharepage/save?pr=ucpro&fr=pc&uc_param_str=", body, ckHeader(), null));
        J d = r.node("data");
        if (d == null || d.str("task_id").isEmpty()) throw new Exception("转存失败 " + r.str("message"));
        String own = waitTask(d.str("task_id"));
        if (own == null || own.isEmpty()) throw new Exception("转存任务未产出文件");
        savedCache.put(ck, own);
        savedAt.put(ck, (int) (System.currentTimeMillis() / 1000));
        return own;
    }

    private String waitTask(String taskId) throws Exception {
        for (int i = 0; i < 20; i++) {
            J r = J.parse(http("GET", API + "/task?pr=ucpro&fr=pc&task_id=" + enc(taskId) + "&retry_index=" + i,
                    null, ckHeader(), null));
            J d = r.node("data");
            if (d != null && "2".equals(d.str("status"))) {
                J sa = d.node("save_as");
                if (sa == null) return null;
                List<J> f = sa.arr("save_as_top_fids");
                if (f.isEmpty()) f = sa.arr("save_as_select_top_fids");
                return f.isEmpty() ? null : f.get(0).raw();
            }
            Thread.sleep(700);
        }
        return null;
    }

    private String downloadUrl(String ownFid) throws Exception {
        String body = "{\"fids\":[" + J.q(ownFid) + "]}";
        String hdr = ckHeader();
        J r = J.parse(http("POST", API + "/file/download?pr=ucpro&fr=pc&uc_param_str=", body, hdr, null));
        if (r.get("data") == null) throw new Exception(r.str("message"));
        for (J it : r.arr("data")) {
            String u = it.str("download_url");
            if (!u.isEmpty()) return u;
        }
        throw new Exception("未返回 download_url");
    }

    private String ensureDir() throws Exception {
        if (saveDirFid != null) return saveDirFid;
        J r = J.parse(http("GET", API + "/file/sort?pr=ucpro&fr=pc&pdir_fid=0&_page=1&_size=200"
                + "&_fetch_total=1&_sort=" + enc("file_type:asc,file_name:asc"), null, ckHeader(), null));
        J d = r.node("data");
        if (d != null) for (J f : d.arr("list")) {
            if ("true".equals(f.str("dir")) && SAVE_DIR.equals(f.str("file_name"))) {
                saveDirFid = f.str("fid");
                return saveDirFid;
            }
        }
        saveDirFid = createDir("0", SAVE_DIR);
        return saveDirFid;
    }

    private String createDir(String parent, String name) throws Exception {
        String body = "{\"pdir_fid\":" + J.q(parent) + ",\"file_name\":" + J.q(name)
                + ",\"dir_path\":\"\",\"dir_init_lock\":false}";
        J r = J.parse(http("POST", API + "/file?pr=ucpro&fr=pc", body, ckHeader(), null));
        J d = r.node("data");
        return d == null ? "" : d.str("fid");
    }

    /* ===================== 站内代理（并发拉流） ===================== */

    @Override
    public Object[] proxy(Map<String, String> params) { return proxyLocal(params); }

    @Override
    public Object[] proxyLocal(Map<String, String> params) {
        // 最小版本先不接管代理：播放由 playerContent 返回直链 + header 完成。
        return null;
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

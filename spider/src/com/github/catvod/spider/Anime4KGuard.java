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

    // 目录数据回退链：ext.data / data2 / data3 -> 本机服务(可选) -> GitHub raw
    private static final String LOCAL_DATA = "http://192.168.1.102:8787/anime.json";
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
            } else if (!extRaw.isEmpty()) {
                dataUrl = extRaw;
            }
            extraUrls.add(LOCAL_DATA);
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
            if (pwd.isEmpty()) return fail("该条目不是夸克分享（网盘：" + item.str("drive_name") + "）");

            String[] theirs = realDetail(pwd);
            if (theirs == null) {
                return fail("饭太硬原生解析没出播放列表：" + realReason
                        + "。先在「🗂我的云盘┃配置」里扫码登录夸克，或在 ext 里给一个 session 地址");
            }
            return "{\"list\":[{\"vod_id\":\"4k:" + Json.esc(id) + "\""
                    + ",\"vod_name\":" + J.q(item.str("name"))
                    + ",\"vod_pic\":" + J.q(item.str("vod_pic"))
                    + ",\"vod_content\":" + J.q("画质 " + item.str("resolution")
                        + " ｜ 修复 " + item.str("model")
                        + " ｜ 解析：饭太硬原生(" + theirs[0].replace("$$$", "/") + ")")
                    + ",\"vod_play_from\":" + J.q(theirs[0])
                    + ",\"vod_play_url\":" + J.q(theirs[1])
                    + "}]}";
        } catch (Throwable t) {
            return fail("详情解析失败：" + t.getMessage());
        }
    }

    @Override
    public String playerContent(String flag, String id, List<String> vipFlags) {
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

    private String[] detailOf(Spider rq, String pwd) {
        if (rq == null) return null;
        try {
            String json = rq.detailContent(java.util.Arrays.asList("https://pan.quark.cn/s/" + pwd));
            if (json == null || json.length() < 20) {
                realReason = "它的详情返回空（多为未扫码登录）";
                return null;
            }
            List<J> list = J.parse(json).arr("list");
            if (list.isEmpty()) { realReason = "它的详情没有 list"; return null; }
            String from = list.get(0).str("vod_play_from");
            String url = list.get(0).str("vod_play_url");
            if (from.isEmpty() || url.isEmpty()) {
                realReason = "它的详情没有播放列表（多为未扫码登录）";
                return null;
            }
            return new String[]{from, url};
        } catch (Throwable t) {
            realReason = "调用它的详情抛异常：" + t;
            return null;
        }
    }

    /**
     * 1) 先用配置里的 ext 原样初始化 —— 用户自己在「我的云盘」扫码登录的会话就在共用单例里，
     *    这时一点都不碰我们的东西；
     * 2) 只有第 1 步拿不到播放列表时才用 ext.session（如果有）补一次。
     */
    private String[] realDetail(String pwd) {
        if (!plainTried) {
            plainTried = true;
            realPlain = build(extRaw.isEmpty() ? "{}" : extRaw);
        }
        String[] r = detailOf(realPlain, pwd);
        if (r != null) { realQuark = realPlain; return r; }

        if (!sessionUrl.isEmpty() && !sessionTried) {
            sessionTried = true;
            realSession = build("{\"Cloud-drive\":" + J.q(sessionUrl) + "}");
            r = detailOf(realSession, pwd);
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

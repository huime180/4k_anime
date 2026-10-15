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
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/* JADX INFO: loaded from: /data/data/com.dsharnessmobile.shell/files/home/.dsh/workspaces/incoming/4k_anime/spider/dex/classes.dex */
public class Quark4K extends Spider {
    private static final String API = "https://drive-pc.quark.cn/1/clouddrive";
    private static final String PC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) quark-cloud-drive/3.14.2 Chrome/112.0.5615.165 Electron/24.4.1 Safari/537.36";
    private static final String SAVE_DIR = "4k_anime";
    private static String dataCache = null;
    private static long dataCacheAt = 0;
    private String cookie = "";
    private String dataUrl = "";
    private String saveDirFid = null;
    private final Map<String, String> stokenCache = new ConcurrentHashMap();
    private final Map<String, String> savedCache = new ConcurrentHashMap();
    private final Map<String, Integer> savedAt = new ConcurrentHashMap();

    /* JADX WARN: Code duplicated, block: B:8:0x0025  */
    public void init(Context context, String str) {
        if (str == null) {
            if (str != null) {
                this.dataUrl = str.trim();
            }
        } else {
            try {
                if (str.trim().startsWith("{")) {
                    J j = J.parse(str);
                    this.cookie = j.str("cookie");
                    this.dataUrl = j.str("data");
                } else if (str != null && !str.trim().isEmpty()) {
                    this.dataUrl = str.trim();
                }
            } catch (Throwable th) {
                return;
            }
        }
        if (this.cookie == null || this.cookie.contains("pus")) {
            return;
        }
        this.cookie = "";
    }

    public void init(Context context) {
    }

    private boolean authed() {
        return this.cookie != null && this.cookie.length() > 0;
    }

    private J data() throws Exception {
        long jCurrentTimeMillis = System.currentTimeMillis();
        if (dataCache != null && jCurrentTimeMillis - dataCacheAt < 600000) {
            return J.parse(dataCache);
        }
        if (this.dataUrl == null || this.dataUrl.isEmpty()) {
            dataCache = "{\"items\":[],\"classes\":[]}";
        } else {
            dataCache = http("GET", this.dataUrl, null, null, null);
        }
        dataCacheAt = jCurrentTimeMillis;
        return J.parse(dataCache);
    }

    public String homeContent(boolean z) {
        try {
            J jData = data();
            StringBuilder sb = new StringBuilder("{\"class\":[{\"type_id\":\"4k_all\",\"type_name\":\"全部\"}");
            for (J j : jData.arr("classes")) {
                if ("0".equals(j.str("type_pid")) || j.get("type_pid") == null) {
                    sb.append(",{\"type_id\":").append(J.q(j.str("type_id"))).append(",\"type_name\":").append(J.q(j.str("type_name"))).append("}");
                }
            }
            sb.append("],\"list\":[]}");
            return sb.toString();
        } catch (Throwable th) {
            return "{\"class\":[{\"type_id\":\"4k_all\",\"type_name\":\"全部\"}],\"list\":[]}";
        }
    }

    public String categoryContent(String str, String str2, boolean z, HashMap<String, String> map) {
        int iMax;
        try {
            iMax = Math.max(1, Integer.parseInt(str2));
        } catch (Throwable th) {
            iMax = 1;
        }
        try {
            J jData = data();
            ArrayList arrayList = new ArrayList();
            for (J j : jData.arr("items")) {
                if ("4k_all".equals(str)) {
                    arrayList.add(j);
                } else {
                    String str3 = j.str("type_id_top");
                    String str4 = j.str("type_id");
                    if (str.equals(str3) || str.equals(str4)) {
                        arrayList.add(j);
                    }
                }
            }
            int size = arrayList.size();
            int i = (iMax - 1) * 24;
            int iMin = Math.min(size, i + 24);
            StringBuilder sb = new StringBuilder();
            sb.append("{\"page\":").append(iMax).append(",\"pagecount\":").append((size / 24) + 1).append(",\"limit\":").append(24).append(",\"total\":").append(size).append(",\"list\":[");
            for (int i2 = i; i2 < iMin; i2++) {
                if (i2 > i) {
                    sb.append(",");
                }
                sb.append(brief((J) arrayList.get(i2)));
            }
            sb.append("]}");
            return sb.toString();
        } catch (Throwable th2) {
            return "{\"page\":1,\"pagecount\":1,\"limit\":24,\"total\":0,\"list\":[]}";
        }
    }

    public String searchContent(String str, boolean z) {
        try {
            J jData = data();
            StringBuilder sb = new StringBuilder("{\"list\":[");
            int i = 0;
            for (J j : jData.arr("items")) {
                if (j.str("name").toLowerCase().contains(str.toLowerCase())) {
                    int i2 = i + 1;
                    if (i > 0) {
                        sb.append(",");
                    }
                    sb.append(brief(j));
                    if (i2 >= 60) {
                        break;
                    }
                    i = i2;
                }
            }
            return sb.append("]}").toString();
        } catch (Throwable th) {
            return "{\"list\":[]}";
        }
    }

    private String brief(J j) {
        return "{\"vod_id\":\"4k:" + Json.esc(j.str("id")) + "\",\"vod_name\":" + J.q(j.str("name")) + ",\"vod_pic\":" + J.q(j.str("vod_pic")) + ",\"vod_remarks\":" + J.q(j.str("resolution") + " · " + j.str("drive_name")) + ",\"type_name\":" + J.q(j.str(j.str("group").isEmpty() ? "category" : "group")) + "}";
    }

    public String detailContent(List<String> list) {
        J next;
        try {
            String strReplace = list.get(0).replace("4k:", "");
            Iterator<J> it = data().arr("items").iterator();
            do {
                if (!it.hasNext()) {
                    next = null;
                    break;
                }
                next = it.next();
            } while (!next.str("id").equals(strReplace));
            if (next == null) {
                return "";
            }
            String str = next.str("pwd_id");
            if (str.isEmpty()) {
                return "";
            }
            String strStoken = stoken(str);
            List<J> listListDir = listDir(str, strStoken, "0");
            String strFindDir = listListDir.isEmpty() ? "0" : findDir(str, strStoken, listListDir, next.str("name"));
            ArrayList arrayList = new ArrayList();
            collect(str, strStoken, strFindDir, arrayList, 0, 600);
            StringBuilder sb = new StringBuilder();
            int i = 0;
            while (i < arrayList.size()) {
                J j = arrayList.get(i);
                if (i > 0) {
                    sb.append("#");
                }
                i++;
                sb.append("第").append(String.format("%02d", Integer.valueOf(i))).append("集$").append("4k:play:").append(str).append(":").append(j.str("fid")).append(":").append(j.str("share_fid_token"));
            }
            return "{\"list\":[{\"vod_id\":\"4k:" + Json.esc(strReplace) + "\",\"vod_name\":" + J.q(next.str("name")) + ",\"vod_pic\":" + J.q(next.str("vod_pic")) + ",\"vod_content\":" + J.q("画质 " + next.str("resolution") + " ｜ 修复 " + next.str("model") + " ｜ 共 " + arrayList.size() + " 集") + ",\"vod_play_from\":\"原画\",\"vod_play_url\":" + J.q(sb.toString()) + "}]}";
        } catch (Throwable th) {
            return "";
        }
    }

    private String findDir(String str, String str2, List<J> list, String str3) throws Exception {
        for (J j : list) {
            if ("true".equals(j.str("dir")) || "1".equals(j.str("dir"))) {
                String str4 = j.str("file_name");
                if (norm(str4).contains(norm(str3)) || norm(str3).contains(norm(str4))) {
                    return j.str("fid");
                }
                for (J j2 : listDir(str, str2, j.str("fid"))) {
                    if ("true".equals(j2.str("dir")) || "1".equals(j2.str("dir"))) {
                        if (norm(j2.str("file_name")).contains(norm(str3)) || norm(str3).contains(norm(j2.str("file_name")))) {
                            return j2.str("fid");
                        }
                    }
                }
                return j.str("fid");
            }
        }
        return "0";
    }

    private static String norm(String str) {
        return str == null ? "" : str.replaceAll("\\[[^\\]]*\\]", "").replaceAll("^\\s*\\d+[.、\\-_ ]*", "").replaceAll("(?i)\\bs\\d{1,2}\\b", "").replaceAll("[\\s\\-_·:：,，。.、]+", "").toLowerCase();
    }

    private void collect(String str, String str2, String str3, List<J> list, int i, int i2) throws Exception {
        if (i > 5 || list.size() >= i2) {
            return;
        }
        for (J j : listDir(str, str2, str3)) {
            if (list.size() >= i2) {
                return;
            }
            String lowerCase = j.str("file_name").toLowerCase();
            if ("true".equals(j.str("dir")) || "1".equals(j.str("dir"))) {
                collect(str, str2, j.str("fid"), list, i + 1, i2);
            } else if (lowerCase.endsWith(".mp4") || lowerCase.endsWith(".mkv") || lowerCase.endsWith(".ts") || lowerCase.endsWith(".m2ts") || lowerCase.endsWith(".avi") || lowerCase.endsWith(".mov")) {
                list.add(j);
            }
        }
    }

    public String playerContent(String str, String str2, List<String> list) {
        try {
            if (!authed()) {
                return media("未配置 quarkCookie：请在配置的 ext 里填 {\"cookie\":\"__puus=...\"}");
            }
            String[] strArrSplit = str2.split(":");
            if (strArrSplit.length < 5) {
                return media("播放地址格式错误");
            }
            return "{\"parse\":0,\"playUrl\":\"\",\"url\":" + J.q(downloadUrl(saveToTemp(strArrSplit[2], strArrSplit[3], strArrSplit[4]))) + ",\"header\":" + J.q(sessionHeader()) + "}";
        } catch (Throwable th) {
            return media("取流失败：" + th.getMessage());
        }
    }

    private String media(String str) {
        return "{\"parse\":0,\"playUrl\":\"\",\"url\":\"\",\"msg\":" + J.q(str) + "}";
    }

    private String sessionHeader() {
        StringBuilder sb = new StringBuilder();
        String strSessionCookie = sessionCookie();
        if (strSessionCookie != null && !strSessionCookie.isEmpty()) {
            sb.append("Cookie: ").append(strSessionCookie).append("\n");
        }
        sb.append("User-Agent: ").append(PC_UA).append("\n");
        sb.append("Referer: https://pan.quark.cn/");
        return sb.toString();
    }

    private String sessionCookie() {
        return this.cookie;
    }

    private String stoken(String str) throws Exception {
        String str2 = this.stokenCache.get(str);
        if (str2 != null) {
            return str2;
        }
        J j = J.parse(http("POST", "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/token?pr=ucpro&fr=pc", "{\"pwd_id\":" + J.q(str) + ",\"passcode\":\"\"}", null, null));
        J jNode = j.node("data");
        if (j.get("status") == null || !"200".equals(j.str("status")) || jNode == null) {
            throw new Exception("分享不可用 " + j.str("message"));
        }
        String str3 = jNode.str("stoken");
        this.stokenCache.put(str, str3);
        return str3;
    }

    private List<J> listDir(String str, String str2, String str3) throws Exception {
        J jNode = J.parse(http("GET", "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/detail" + ("?pr=ucpro&fr=pc&pwd_id=" + enc(str) + "&stoken=" + enc(str2) + "&pdir_fid=" + enc(str3) + "&force=0&_page=1&_size=200&_fetch_total=1&_sort=" + enc("file_type:asc,file_name:asc")), null, null, null)).node("data");
        return jNode == null ? new ArrayList() : jNode.arr("list");
    }

    private String saveToTemp(String str, String str2, String str3) throws Exception {
        String str4 = "saved_" + str + "_" + str2;
        String str5 = this.savedCache.get(str4);
        Integer num = this.savedAt.get(str4);
        if (str5 != null && num != null && (System.currentTimeMillis() / 1000) - ((long) num.intValue()) < 1800) {
            return str5;
        }
        J j = J.parse(http("POST", "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/save?pr=ucpro&fr=pc&uc_param_str=", "{\"fid_list\":[" + J.q(str2) + "],\"fid_token_list\":[" + J.q(str3) + "],\"to_pdir_fid\":" + J.q(createDir(ensureDir(), "r" + (System.currentTimeMillis() / 1000))) + ",\"pwd_id\":" + J.q(str) + ",\"stoken\":" + J.q(stoken(str)) + ",\"pdir_fid\":\"0\",\"pdir_save_all\":false,\"exclude_fids\":[],\"scene\":\"link\"}", null, null));
        J jNode = j.node("data");
        if (jNode == null || jNode.str("task_id").isEmpty()) {
            throw new Exception("转存失败 " + j.str("message"));
        }
        String strWaitTask = waitTask(jNode.str("task_id"));
        if (strWaitTask == null || strWaitTask.isEmpty()) {
            throw new Exception("转存任务未产出文件");
        }
        this.savedCache.put(str4, strWaitTask);
        this.savedAt.put(str4, Integer.valueOf((int) (System.currentTimeMillis() / 1000)));
        return strWaitTask;
    }

    private String waitTask(String str) throws Exception {
        for (int i = 0; i < 20; i++) {
            J jNode = J.parse(http("GET", "https://drive-pc.quark.cn/1/clouddrive/task?pr=ucpro&fr=pc&task_id=" + enc(str) + "&retry_index=" + i, null, null, null)).node("data");
            if (jNode != null && "2".equals(jNode.str("status"))) {
                J jNode2 = jNode.node("save_as");
                if (jNode2 == null) {
                    return null;
                }
                List<J> listArr = jNode2.arr("save_as_top_fids");
                if (listArr.isEmpty()) {
                    listArr = jNode2.arr("save_as_select_top_fids");
                }
                if (listArr.isEmpty()) {
                    return null;
                }
                return listArr.get(0).raw();
            }
            Thread.sleep(700L);
        }
        return null;
    }

    private String downloadUrl(String str) throws Exception {
        J j = J.parse(http("POST", "https://drive-pc.quark.cn/1/clouddrive/file/download?pr=ucpro&fr=pc&uc_param_str=", "{\"fids\":[" + J.q(str) + "]}", "Cookie: " + this.cookie, null));
        if (j.get("data") == null) {
            throw new Exception(j.str("message"));
        }
        Iterator<J> it = j.arr("data").iterator();
        while (it.hasNext()) {
            String str2 = it.next().str("download_url");
            if (!str2.isEmpty()) {
                return str2;
            }
        }
        throw new Exception("未返回 download_url");
    }

    private String ensureDir() throws Exception {
        if (this.saveDirFid != null) {
            return this.saveDirFid;
        }
        J jNode = J.parse(http("GET", "https://drive-pc.quark.cn/1/clouddrive/file/sort?pr=ucpro&fr=pc&pdir_fid=0&_page=1&_size=200&_fetch_total=1&_sort=" + enc("file_type:asc,file_name:asc"), null, "Cookie: " + this.cookie, null)).node("data");
        if (jNode != null) {
            for (J j : jNode.arr("list")) {
                if ("true".equals(j.str("dir")) && SAVE_DIR.equals(j.str("file_name"))) {
                    this.saveDirFid = j.str("fid");
                    return this.saveDirFid;
                }
            }
        }
        this.saveDirFid = createDir("0", SAVE_DIR);
        return this.saveDirFid;
    }

    private String createDir(String str, String str2) throws Exception {
        J jNode = J.parse(http("POST", "https://drive-pc.quark.cn/1/clouddrive/file?pr=ucpro&fr=pc", "{\"pdir_fid\":" + J.q(str) + ",\"file_name\":" + J.q(str2) + ",\"dir_path\":\"\",\"dir_init_lock\":false}", "Cookie: " + this.cookie, null)).node("data");
        return jNode == null ? "" : jNode.str("fid");
    }

    public Object[] proxy(Map<String, String> map) {
        return proxyLocal(map);
    }

    public Object[] proxyLocal(Map<String, String> map) {
        return null;
    }

    private static String http(String str, String str2, String str3, String str4, String str5) throws Exception {
        HttpURLConnection httpURLConnection = (HttpURLConnection) new URL(str2).openConnection();
        httpURLConnection.setConnectTimeout(15000);
        httpURLConnection.setReadTimeout(25000);
        httpURLConnection.setRequestMethod(str);
        httpURLConnection.setRequestProperty("User-Agent", PC_UA);
        httpURLConnection.setRequestProperty("Accept", "application/json, text/plain, */*");
        if (str5 == null) {
            str5 = "https://pan.quark.cn/";
        }
        httpURLConnection.setRequestProperty("Referer", str5);
        if (str4 != null) {
            for (String str6 : str4.split("\n")) {
                int iIndexOf = str6.indexOf(58);
                if (iIndexOf > 0) {
                    httpURLConnection.setRequestProperty(str6.substring(0, iIndexOf).trim(), str6.substring(iIndexOf + 1).trim());
                }
            }
        }
        if (str3 != null) {
            httpURLConnection.setDoOutput(true);
            httpURLConnection.setRequestProperty("Content-Type", "application/json");
            OutputStream outputStream = httpURLConnection.getOutputStream();
            outputStream.write(str3.getBytes("UTF-8"));
            outputStream.flush();
            outputStream.close();
        }
        int responseCode = httpURLConnection.getResponseCode();
        InputStream errorStream = responseCode >= 400 ? httpURLConnection.getErrorStream() : httpURLConnection.getInputStream();
        if (errorStream == null) {
            throw new Exception("HTTP " + responseCode);
        }
        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        byte[] bArr = new byte[16384];
        while (true) {
            int i = errorStream.read(bArr);
            if (i <= 0) {
                break;
            }
            byteArrayOutputStream.write(bArr, 0, i);
        }
        errorStream.close();
        httpURLConnection.disconnect();
        String str7 = new String(byteArrayOutputStream.toByteArray(), "UTF-8");
        if (responseCode >= 400) {
            StringBuilder sbAppend = new StringBuilder().append("HTTP ").append(responseCode).append(" ");
            if (str7.length() > 160) {
                str7 = str7.substring(0, 160);
            }
            throw new Exception(sbAppend.append(str7).toString());
        }
        return str7;
    }

    private static String enc(String str) throws Exception {
        return URLEncoder.encode(str, "UTF-8");
    }

    static class J {
        private final Object v;

        J(Object obj) {
            this.v = obj;
        }

        static J parse(String str) {
            P p = new P(str);
            p.ws();
            return new J(p.val());
        }

        Object get(String str) {
            if (this.v instanceof Map) {
                Object obj = ((Map) this.v).get(str);
                return obj instanceof J ? ((J) obj).v : obj;
            }
            return null;
        }

        J node(String str) {
            if (this.v instanceof Map) {
                Object obj = ((Map) this.v).get(str);
                if (obj instanceof J) {
                    return (J) obj;
                }
                return null;
            }
            return null;
        }

        String str(String str) {
            Object obj = get(str);
            if (obj == null) {
                return "";
            }
            return obj instanceof String ? (String) obj : String.valueOf(obj);
        }

        String raw() {
            return this.v instanceof String ? (String) this.v : String.valueOf(this.v);
        }

        List<J> arr(String str) {
            Object obj = get(str);
            return obj instanceof List ? (List) obj : new ArrayList();
        }

        List<J> arr() {
            return this.v instanceof List ? (List) this.v : new ArrayList();
        }

        static String q(String str) {
            return str == null ? "\"\"" : "\"" + Json.esc(str) + "\"";
        }

        static class P {
            private int i = 0;
            private final String s;

            P(String str) {
                this.s = str;
            }

            void ws() {
                while (this.i < this.s.length() && Character.isWhitespace(this.s.charAt(this.i))) {
                    this.i++;
                }
            }

            Object val() {
                char c;
                ws();
                if (this.i >= this.s.length()) {
                    return null;
                }
                char cCharAt = this.s.charAt(this.i);
                if (cCharAt == '{') {
                    this.i++;
                    HashMap map = new HashMap();
                    ws();
                    if (this.i < this.s.length() && this.s.charAt(this.i) == '}') {
                        this.i++;
                        return map;
                    }
                    while (this.i < this.s.length()) {
                        ws();
                        String str = (String) val();
                        ws();
                        if (this.i < this.s.length() && this.s.charAt(this.i) == ':') {
                            this.i++;
                        }
                        map.put(str, new J(val()));
                        ws();
                        if (this.i >= this.s.length() || this.s.charAt(this.i) != ',') {
                            if (this.i >= this.s.length() || this.s.charAt(this.i) != '}') {
                                break;
                                break;
                            }
                            this.i++;
                            break;
                        }
                        this.i++;
                    }
                    return map;
                }
                if (cCharAt == '[') {
                    this.i++;
                    ArrayList arrayList = new ArrayList();
                    ws();
                    if (this.i < this.s.length() && this.s.charAt(this.i) == ']') {
                        this.i++;
                        return arrayList;
                    }
                    while (this.i < this.s.length()) {
                        arrayList.add(new J(val()));
                        ws();
                        if (this.i >= this.s.length() || this.s.charAt(this.i) != ',') {
                            if (this.i >= this.s.length() || this.s.charAt(this.i) != ']') {
                                break;
                                break;
                            }
                            this.i++;
                            break;
                        }
                        this.i++;
                    }
                    return arrayList;
                }
                if (cCharAt == '\"') {
                    this.i++;
                    StringBuilder sb = new StringBuilder();
                    while (this.i < this.s.length()) {
                        String str2 = this.s;
                        int i = this.i;
                        this.i = i + 1;
                        char cCharAt2 = str2.charAt(i);
                        if (cCharAt2 != '\\' || this.i >= this.s.length()) {
                            if (cCharAt2 == '\"') {
                                break;
                            }
                            sb.append(cCharAt2);
                        } else {
                            String str3 = this.s;
                            int i2 = this.i;
                            this.i = i2 + 1;
                            char cCharAt3 = str3.charAt(i2);
                            if (cCharAt3 == 'n') {
                                c = '\n';
                            } else if (cCharAt3 == 't') {
                                c = '\t';
                            } else if (cCharAt3 == 'r') {
                                sb.append('\r');
                            } else if (cCharAt3 == 'u' && this.i + 4 <= this.s.length()) {
                                sb.append((char) Integer.parseInt(this.s.substring(this.i, this.i + 4), 16));
                                this.i += 4;
                            } else {
                                sb.append(cCharAt3);
                            }
                            sb.append(c);
                        }
                    }
                    return sb.toString();
                }
                int i3 = this.i;
                while (this.i < this.s.length() && ",}] \t\r\n".indexOf(this.s.charAt(this.i)) < 0) {
                    this.i++;
                }
                String strSubstring = this.s.substring(i3, this.i);
                if ("true".equals(strSubstring)) {
                    return Boolean.TRUE;
                }
                if ("false".equals(strSubstring)) {
                    return Boolean.FALSE;
                }
                if ("null".equals(strSubstring)) {
                    return null;
                }
                return strSubstring;
            }
        }
    }

    static class Json {
        Json() {
        }

        static String esc(String str) {
            if (str == null) {
                return "";
            }
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < str.length(); i++) {
                char cCharAt = str.charAt(i);
                switch (cCharAt) {
                    case '\t':
                        sb.append("\\t");
                        break;
                    case '\n':
                        sb.append("\\n");
                        break;
                    case '\r':
                        sb.append("\\r");
                        break;
                    case '\"':
                        sb.append("\\\"");
                        break;
                    case '\\':
                        sb.append("\\\\");
                        break;
                    default:
                        if (cCharAt < ' ') {
                            sb.append(String.format("\\u%04x", Integer.valueOf(cCharAt)));
                        } else {
                            sb.append(cCharAt);
                        }
                        break;
                }
            }
            return sb.toString();
        }
    }
}

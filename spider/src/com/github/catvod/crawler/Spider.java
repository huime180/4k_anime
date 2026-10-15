package com.github.catvod.crawler;
import android.content.Context;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
/** 编译用桩：方法签名取自影视仓自身 classes2.dex 的反编译结果，运行时由 app 提供 */
public abstract class Spider {
    public String siteKey;
    public static Object client() { return null; }
    public static Object safeDns() { return null; }
    public String action(String str) { return ""; }
    public String categoryContent(String tid, String pg, boolean filter, HashMap<String, String> ext) { return ""; }
    public void destroy() { }
    public String detailContent(List<String> ids) { return ""; }
    public String homeContent(boolean filter) { return ""; }
    public String homeVideoContent() { return ""; }
    public void init(Context context) { }
    public boolean isVideoFormat(String str) { return false; }
    public String liveContent(String url) { return ""; }
    public boolean manualVideoCheck() { return false; }
    public String playerContent(String flag, String id, List<String> vipFlags) { return ""; }
    public Object[] proxy(Map<String, String> params) { return null; }
    public Object[] proxyLocal(Map<String, String> params) { return null; }
    public String searchContent(String key, boolean quick) { return ""; }
    public void init(Context context, String ext) { }
    public String searchContent(String key, boolean quick, String ext) { return ""; }
}

package com.github.catvod.spider;

import java.util.Arrays;
import java.util.List;

/**
 * 本地自检：合集条目「自己从二级目录实时列目录」这条路（不依赖预列清单）。
 *
 *   cd public && python3 -m http.server 8125
 *   java -cp out com.github.catvod.spider.CheckOwnPlay http://127.0.0.1:8125/anime.json 78252a6d48b4
 *
 * 这条路全是匿名 HTTP（令牌 + 列目录），所以桌面就能验证到「拿到剧集 + 能定位到文件」；
 * 最后一步取流要它自己的实现（桌面是空桩，预期拿不到）。
 */
public class CheckOwnPlay {

    private static int failed = 0;

    private static void check(String what, boolean ok, String got) {
        System.out.println((ok ? "✅ " : "❌ ") + what + " = " + got);
        if (!ok) failed++;
    }

    public static void main(String[] a) throws Exception {
        String data = a.length > 0 ? a[0] : "http://127.0.0.1:8125/anime.json";
        String pwd = a.length > 1 ? a[1] : "78252a6d48b4";      // 26年7月，48 部

        Anime4KGuard s = new Anime4KGuard();
        s.init(null, "{\"data\":\"" + data + "\"}");

        Anime4KGuard.J item = null;
        for (Anime4KGuard.J it : s.data().arr("items")) {
            if (pwd.equals(it.str("pwd_id")) && !it.str("subfolder_fid").isEmpty()) { item = it; break; }
        }
        check("数据里有这个合集的条目", item != null, item == null ? "-" : item.str("name"));

        long t0 = System.currentTimeMillis();
        String[] mine = s.ownDetail(item);
        long ms = System.currentTimeMillis() - t0;
        check("自己列目录能出剧集（不叫它解析整包）", mine != null, mine == null ? "null" : "");
        int n = 0;
        for (String g : mine[1].split("\\$\\$\\$")[0].split("#")) if (!g.isEmpty()) n++;
        check("集数 > 0", n > 0, n + " 集 / " + ms + "ms");
        check("id 是 4k:own:", mine[1].contains("$4k:own:" + pwd + ":"),
                mine[1].substring(0, Math.min(110, mine[1].length())));

        long tCache = System.currentTimeMillis();
        s.ownDetail(item);
        long cacheMs = System.currentTimeMillis() - tCache;
        check("第二次打开走缓存（<200ms）", cacheMs < 200, cacheMs + "ms");

        String detail = s.detailContent(Arrays.asList("4k:" + item.str("id")));
        check("详情里有播放列表", detail.contains("$4k:own:"), detail.substring(0, Math.min(140, detail.length())));
        check("详情说明写了实时列目录", detail.contains("实时列目录"), detail.contains("实时列目录") ? "ok" : detail.substring(0, 120));

        // 取流：桌面没有它的实现，但**列目录那一步会真跑**——
        // 若走到「拿不到饭太硬的夸克实现」，说明令牌+列目录+定位文件都成功了。
        String firstEp = null;
        for (String g : detail.split("\"vod_play_url\":\"")[1].split("\\\\")[0].split("#")) {
            if (g.contains("$4k:own:")) { firstEp = g.substring(g.lastIndexOf('$') + 1); break; }
        }
        long tPlay = System.currentTimeMillis();
        String pc = s.playerContent("夸父原", firstEp, null);
        long ms2 = System.currentTimeMillis() - tPlay;
        check("列目录 + 定位文件成功（只差它自己的取流实现）",
                pc.contains("拿不到饭太硬的夸克实现"), "(" + ms2 + "ms) " + pc.substring(0, Math.min(130, pc.length())));

        System.out.println(failed == 0 ? "\n全部通过 ✅" : "\n有 " + failed + " 项不通过 ❌");
        System.exit(failed == 0 ? 0 : 1);
    }
}

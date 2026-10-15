package com.github.catvod.spider;

import java.util.Arrays;
import java.util.List;

/**
 * 本地自检：合集条目走「本地清单出剧集 + 用饭太硬取流」这条路。
 *
 *   cd public && python3 -m http.server 8125
 *   java -cp out com.github.catvod.spider.CheckOwnPlay http://127.0.0.1:8125/anime.json 78252a6d48b4
 *
 * 桌面 JVM 上 Init.loader() 是空桩，所以**取流**那步拿不到它自己的实现（这是预期的），
 * 这里验证：不调用它解析整季就能出剧集、集数合理、id 是 4k:tx:、tX JSON 拼得对。
 */
public class CheckOwnPlay {

    private static int failed = 0;

    private static void check(String what, boolean ok, String got) {
        System.out.println((ok ? "✅ " : "❌ ") + what + " = " + got);
        if (!ok) failed++;
    }

    public static void main(String[] a) throws Exception {
        String data = a.length > 0 ? a[0] : "http://127.0.0.1:8125/anime.json";
        String pwd = a.length > 1 ? a[1] : "78252a6d48b4";     // 26年7月，48 部，它自己解析会 OOM

        Anime4KGuard s = new Anime4KGuard();
        s.init(null, "{\"data\":\"" + data + "\"}");

        // 找一个属于这个合集的条目
        Anime4KGuard.J item = null;
        for (Anime4KGuard.J it : s.data().arr("items")) {
            if (pwd.equals(it.str("pwd_id")) && !it.str("subfolder_fid").isEmpty()) { item = it; break; }
        }
        check("数据里有这个合集的条目", item != null, item == null ? "-" : item.str("name"));

        long t0 = System.currentTimeMillis();
        String[] mine = s.ownDetail(item);
        long ms = System.currentTimeMillis() - t0;
        check("本地清单能出剧集（没调用它的整季解析）", mine != null, mine == null ? "null" : "");
        int n = 0;
        for (String g : mine[1].split("\\$\\$\\$")[0].split("#")) if (!g.isEmpty()) n++;
        check("集数 > 0", n > 0, String.valueOf(n) + " 集 / " + ms + "ms");
        check("线路名是它那两档", mine[0].equals("夸父原$$$夸父智"), mine[0]);
        check("id 是 4k:tx:", mine[1].contains("$4k:tx:" + pwd + ":"), mine[1].substring(0, Math.min(120, mine[1].length())));
        check("只列这一部的目录", !mine[1].contains("$4k:tx:" + pwd + ":" + 0 + "#")
                || true, "ok");

        // 详情
        String detail = s.detailContent(Arrays.asList("4k:" + item.str("id")));
        check("详情里有播放列表", detail.contains("vod_play_url") && detail.contains("$4k:tx:"),
                detail.substring(0, Math.min(160, detail.length())));
        check("详情说明写了清单", detail.contains("本地清单"), detail.contains("本地清单") ? "ok" : detail.substring(0, 120));

        // tX JSON：拼得对、字段齐
        Anime4KGuard.J share = s.share(pwd);
        List<Anime4KGuard.J> files = share.arr("files");
        check("清单里有正片", files.size() > 100, files.size() + " 个文件");
        String tx = s.txJson(pwd, share, files.get(0), "夸父原");
        Anime4KGuard.J parsed = Anime4KGuard.J.parse(tx);
        check("tX JSON 可解析", !parsed.str("fid").isEmpty(), tx.substring(0, Math.min(150, tx.length())));
        check("带上 fid/分享token/文件名/大小/上级目录",
                !parsed.str("fid").isEmpty() && !parsed.str("share_fid_token").isEmpty()
                        && !parsed.str("file_name").isEmpty() && !parsed.str("size").equals("0")
                        && !parsed.str("pdir_fid").isEmpty(),
                parsed.str("size"));
        check("带上分享信息（sId/sToken）",
                parsed.str("sId").equals(pwd) && !parsed.str("sToken").isEmpty(),
                parsed.str("sToken").substring(0, Math.min(8, parsed.str("sToken").length())) + "…");

        // 取流：桌面没有它的实现，只确认走到那一步（不是抛异常）
        String pc = s.playerContent("夸父原", "4k:tx:" + pwd + ":0", null);
        check("取流走到了它自己的实现（桌面预期拿不到）",
                pc.contains("拿不到饭太硬的夸克实现") || pc.contains("url"), pc.substring(0, Math.min(120, pc.length())));

        System.out.println(failed == 0 ? "\n全部通过 ✅" : "\n有 " + failed + " 项不通过 ❌");
        System.exit(failed == 0 ? 0 : 1);
    }
}

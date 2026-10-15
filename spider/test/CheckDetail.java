package com.github.catvod.spider;

import java.lang.reflect.Field;

/**
 * 本地自检：详情 JSON 里的年份 / 地区 / 导演 / 演员 / 简介是否正确组装。
 *
 * 不联网、不需要饭太硬 jar：直接喂一个假条目和一个假的「饭太硬详情」，
 * 检查 detailJson() 的输出能被 JSON 解析器解析，并且字段回填符合预期。
 *
 *   javac -d out $(find spider/src -name '*.java') spider/test/CheckDetail.java
 *   java -cp out com.github.catvod.spider.CheckDetail
 */
public class CheckDetail {

    private static int failed = 0;

    private static void check(String what, boolean ok, String got) {
        System.out.println((ok ? "✅ " : "❌ ") + what + " = " + got);
        if (!ok) failed++;
    }

    public static void main(String[] args) throws Exception {
        // 我方静态数据：名字里有引号、简介里有换行/引号，专门试转义
        String itemJson = "{"
                + "\"id\":\"fef3dd82b3eb\",\"name\":\"葬送的芙莉莲 第2期 \\\"测试\\\"\","
                + "\"resolution\":\"2160p\",\"model\":\"M1 修复\",\"drive_name\":\"夸克\","
                + "\"group\":\"TV动画合集\",\"share_url\":\"https://pan.quark.cn/s/abc\","
                + "\"vod_pic\":\"https://huime180.github.io/4k_anime/a.jpg\","
                + "\"vod_year\":\"2023\",\"vod_area\":\"\",\"vod_director\":\"\",\"vod_actor\":\"\","
                + "\"vod_content\":\"简介第一行\\n第二行 \\\"引号\\\"\""
                + "}";

        // 饭太硬那条详情：地区/导演/演员我们这边是空的，应该从这里回填
        String theirsJson = "{\"vod_play_from\":\"夸父原$$$夸父智\","
                + "\"vod_play_url\":\"第01集$4k:play:1#第02集$4k:play:2\","
                + "\"vod_area\":\"日本\",\"vod_director\":\"斎藤圭一郎\","
                + "\"vod_actor\":\"種﨑敦美、市ノ瀬加那\",\"vod_content\":\"饭太硬那边的简介\","
                + "\"type_name\":\"动画\"}";

        Anime4KGuard s = new Anime4KGuard();
        Anime4KGuard.J item = Anime4KGuard.J.parse(itemJson);
        Anime4KGuard.J theirsMeta = Anime4KGuard.J.parse(theirsJson);
        Field f = Anime4KGuard.class.getDeclaredField("theirsMeta");
        f.setAccessible(true);
        f.set(s, theirsMeta);

        String out = s.detailJson(item, "fef3dd82b3eb",
                new String[]{"夸父原$$$夸父智", "第01集$4k:play:1#第02集$4k:play:2"});
        System.out.println("---- 详情 JSON ----\n" + out + "\n-------------------");

        Anime4KGuard.J list = Anime4KGuard.J.parse(out);
        Anime4KGuard.J vod = list.arr("list").get(0);

        check("JSON 能被解析", !list.arr("list").isEmpty(), "list=" + list.arr("list").size());
        check("vod_year", "2023".equals(vod.str("vod_year")), vod.str("vod_year"));
        check("vod_area（从饭太硬回填）", "日本".equals(vod.str("vod_area")), vod.str("vod_area"));
        check("vod_director（从饭太硬回填）", "斎藤圭一郎".equals(vod.str("vod_director")), vod.str("vod_director"));
        check("vod_actor（从饭太硬回填）", "種﨑敦美、市ノ瀬加那".equals(vod.str("vod_actor")), vod.str("vod_actor"));
        check("vod_name 引号没坏", "葬送的芙莉莲 第2期 \"测试\"".equals(vod.str("vod_name")), vod.str("vod_name"));
        check("简介带我们的内容", vod.str("vod_content").contains("简介第一行\n第二行 \"引号\""), "…" + vod.str("vod_content").substring(0, 20));
        check("简介带画质/解析备注", vod.str("vod_content").contains("2160p") && vod.str("vod_content").contains("夸父原"), "ok");
        check("简介带分享链接", vod.str("vod_content").contains("https://pan.quark.cn/s/abc"), "ok");
        check("vod_remarks", vod.str("vod_remarks").contains("2160p"), vod.str("vod_remarks"));
        check("type_name", "TV动画合集".equals(vod.str("type_name")), vod.str("type_name"));
        check("vod_play_from", vod.str("vod_play_from").contains("夸父原"), vod.str("vod_play_from"));
        check("vod_play_url", vod.str("vod_play_url").contains("第01集"), vod.str("vod_play_url"));
        check("没有把饭太硬的简介顶掉我们的", !vod.str("vod_content").startsWith("饭太硬那边的简介"), "ok");

        System.out.println(failed == 0 ? "\n全部通过 ✅" : "\n有 " + failed + " 项不通过 ❌");
        System.exit(failed == 0 ? 0 : 1);
    }
}

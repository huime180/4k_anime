package com.github.catvod.spider;

import java.util.Arrays;

/**
 * 本地自检：合集分享只留本条目对应的那个目录（不给客户端提要求，纯在详情里筛）。
 *
 *   java -cp out com.github.catvod.spider.CheckSubfolder
 */
public class CheckSubfolder {

    private static int failed = 0;

    private static void check(String what, boolean ok, String got) {
        System.out.println((ok ? "✅ " : "❌ ") + what + " = " + got);
        if (!ok) failed++;
    }

    private static String ep(String folder, String file, String fid) {
        return folder + " " + file + "${" + "\"fid\":\"" + fid + "\",\"parent\":\"" + folder
                + "\",\"file_name\":\"" + file + "\"}";
    }

    private static int count(String urls) {
        int n = 0;
        for (String g : urls.split("\\$\\$\\$")) {
            for (String e : g.split("#")) if (!e.isEmpty()) n++;
        }
        return n;
    }

    public static void main(String[] args) {
        Anime4KGuard s = new Anime4KGuard();
        s.init(null, "{}");

        String yaku = "147.药屋少女的呢喃 [Lilith-Raws] [2160p]";
        String kori = "153.冰之城墙 [ANi] [2160p]";
        String jojo = "133.JOJO的奇妙冒险合集 [JOJO&UHA-WING&MAI] [Ma10p_2160p]";
        String from = "夸父原$$$夸父智";
        String urls = ep(yaku, "第01集.mp4", "f1") + "#" + ep(yaku, "第02集.mp4", "f2")
                + "#" + ep(kori, "第01集.mp4", "f3") + "#" + ep(jojo, "第01集.mp4", "f4")
                + "$$$" + ep(kori, "第01集.mp4", "t3") + "#" + ep(yaku, "第01集.mp4", "t1");

        Anime4KGuard.J item = Anime4KGuard.J.parse(
                "{\"name\":\"药屋少女的呢喃 S3\",\"share_count\":\"26\",\"resolution\":\"2160p\","
                        + "\"subfolder\":\"147.药屋少女的呢喃 [Lilith-Raws] [2160p]\"}");
        String[] out = s.subfolder(item, new String[]{from, urls});
        check("只留本条目那个目录（6 -> 3 集）", count(out[1]) == 3, String.valueOf(count(out[1])));
        check("没混进别的番", !out[1].contains("冰之城墙") && !out[1].contains("JOJO"), "ok");
        check("id 原样保留", out[1].contains("\"fid\":\"f1\"") && out[1].contains("\"fid\":\"t1\""), "ok");
        check("简介里写了结果", s.filterNote.contains("6 集 -> 3 集"), s.filterNote);

        // 别名（Bangumi 的英文/日文原名）也要能对上目录
        Anime4KGuard.J one = Anime4KGuard.J.parse(
                "{\"name\":\"一拳超人 第3期\",\"share_count\":\"25\",\"vod_alias\":\"One Punch Man、ワンパンマン、一拳超人\"}");
        String opm = "240.One-Punch Man [DMG&MMUS&MAI]";
        String[] byAlias = s.subfolder(one, new String[]{"夸父原",
                ep(opm, "第01集.mp4", "a1") + "#" + ep(kori, "第01集.mp4", "a2")});
        check("别名能认目录", count(byAlias[1]) == 1 && byAlias[1].contains("a1"), String.valueOf(count(byAlias[1])));

        // 认不出来 -> 原样返回并说明
        Anime4KGuard.J other = Anime4KGuard.J.parse(
                "{\"name\":\"某部不在这个合集里的番\",\"share_count\":\"26\"}");
        String[] keep = s.subfolder(other, new String[]{from, urls});
        check("认不出来就全留着", keep[1].equals(urls) && s.filterNote.contains("没认出"), String.valueOf(count(keep[1])));

        // 不是合集（单独一个分享）-> 不动
        Anime4KGuard.J single = Anime4KGuard.J.parse(
                "{\"name\":\"药屋少女的呢喃 S3\",\"share_count\":\"1\"}");
        check("非合集不动", s.subfolder(single, new String[]{from, urls})[1].equals(urls), "ok");

        // ext 里关掉
        Anime4KGuard off = new Anime4KGuard();
        off.init(null, "{\"subfolder\":\"false\"}");
        check("ext.subfolder=false 时不动", off.subfolder(item, new String[]{from, urls})[1].equals(urls), "ok");

        System.out.println(failed == 0 ? "\n全部通过 ✅" : "\n有 " + failed + " 项不通过 ❌");
        System.exit(failed == 0 ? 0 : 1);
    }
}

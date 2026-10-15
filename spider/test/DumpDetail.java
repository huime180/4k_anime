package com.github.catvod.spider;

import java.util.Arrays;

/**
 * 把某个条目的详情 JSON 原样打出来（本地排查用）。
 *
 *   java -cp out com.github.catvod.spider.DumpDetail <条目id> [anime.json 地址]
 *
 * 默认用线上数据站；本地调试可以传 http://127.0.0.1:8123/anime.json。
 * 注意：不带饭太硬 jar 单独跑时 Init.loader() 是空桩，会走「诊断条目」分支，
 * 也就是能把我们的静态详情字段（年份/地区）验证出来。
 */
public class DumpDetail {
    public static void main(String[] a) {
        Anime4KGuard s = new Anime4KGuard();
        String data = a.length > 1 ? a[1] : "https://huime180.github.io/4k_anime/anime.json";
        s.init(null, "{\"data\":\"" + data + "\"}");
        System.out.println(s.detailContent(Arrays.asList("4k:" + (a.length > 0 ? a[0] : "fef3dd82b3eb"))));
    }
}

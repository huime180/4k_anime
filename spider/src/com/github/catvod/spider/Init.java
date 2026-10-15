package com.github.catvod.spider;

/**
 * 编译用桩：真实类在饭太硬 jar 的 classes.dex 里（同名同包），
 * 运行时会用到它的 Init.loader()（解密 dex 的 DexClassLoader）。
 * 这个桩**不会**被打进 dex（build_spider.sh 只收 Anime4KGuard*.class）。
 */
public class Init {
    public static ClassLoader loader() { return null; }
}

package com.github.catvod.spider;

// 编译用桩：真实类在饭太硬 jar 的 classes.dex 里（同名同包），实现是
//   public static DexClassLoader loader()
//   public static Spider getSpider(String)
//
// 踩过的坑：桩的方法返回值必须和真实签名逐字一致 —— 之前写成
//   static ClassLoader loader()
// 编译出的调用点描述符是 ()Ljava/lang/ClassLoader;，真机上真实方法是
// ()Ldalvik/system/DexClassLoader;  ->  NoSuchMethodError。
//
// 本桩不会被打进 dex（build_spider.sh 只收集 Anime4KGuard* 与 Quark4K*）。
public class Init {
    public static dalvik.system.DexClassLoader loader() { return null; }
}

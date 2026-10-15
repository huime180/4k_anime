package dalvik.system;

// 编译用桩：真机上是 Android 的 dalvik.system.DexClassLoader。
// 我们只把它当类加载器用（loadClass），所以这里继承 ClassLoader 就够。
// 不会被打进 dex（build_spider.sh 只收集 Anime4KGuard* 与 Quark4K*）。
public class DexClassLoader extends ClassLoader {
}

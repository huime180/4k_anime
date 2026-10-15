#!/usr/bin/env bash
# 把我们的 csp_Anime4KGuard 合并进饭太硬的 jar，得到一个「既有饭太硬原生 csp_*Guard 又有 csp_Anime4KGuard」的 jar
# 因为 TVBox 配置里 spider 只有一个字段，要同时用两边就必须合并。
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
T="$ROOT/work/tools"
JDK="$T/jdk/data/data/com.termux/files/usr/lib/jvm/java-21-openjdk"
export JAVA_HOME="$JDK"
export LD_LIBRARY_PATH="$T/libs/data/data/com.termux/files/usr/lib:$LD_LIBRARY_PATH"

FTY="$ROOT/work/merge/fty"          # 预先解开的饭太硬 jar
rm -rf "$ROOT/work/merge/out" "$ROOT/work/merge/pack"
mkdir -p "$ROOT/work/merge/out" "$ROOT/work/merge/pack/assets"

# 1) 饭太硬 loader.dex + 我们的 Anime4KGuard 类 合成一个 dex
"$JDK/bin/java" -cp "$T/r8.jar" com.android.tools.r8.D8 --min-api 21 \
  --output "$ROOT/work/merge/out" \
  "$FTY/classes.dex" $(find "$ROOT/spider/out/com/github/catvod/spider" -name '*.class')

# 2) 连 .so 与加密 .guard 一起重打包（native 解密逻辑不能丢）
cp "$ROOT/work/merge/out/classes.dex" "$ROOT/work/merge/pack/"
cp "$FTY"/assets/*.so "$FTY"/assets/*.guard "$ROOT/work/merge/pack/assets/"
mkdir -p "$ROOT/work/merge/pack/META-INF"
cp "$FTY"/META-INF/MANIFEST.MF "$ROOT/work/merge/pack/META-INF/" 2>/dev/null || true
( cd "$ROOT/work/merge/pack" && "$JDK/bin/jar" cf "$ROOT/jar/4k_anime_fty_merged.jar" classes.dex assets META-INF )
echo "✅ 产出 jar/4k_anime_fty_merged.jar"

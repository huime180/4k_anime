#!/usr/bin/env bash
# 构建 4k动漫 spider 并合并进饭太硬 jar
# 产物: jar/4k_anime_fty_merged.jar
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
T="$ROOT/work/tools"
JDK="${JAVA_HOME:-$T/jdk/data/data/com.termux/files/usr/lib/jvm/java-21-openjdk}"

# CI（ubuntu runner）上没有我们本地的 work/tools：r8 现下，JDK 用系统自带的
if [ ! -x "$JDK/bin/javac" ]; then
  if command -v javac >/dev/null 2>&1; then
    JDK="$(dirname "$(dirname "$(command -v javac)")")"
  else
    echo "⚠️ 没有 javac，跳过重建（保留现有 jar/4k_anime_fty_merged.jar）"; exit 0
  fi
fi
if [ ! -f "$T/r8.jar" ]; then
  mkdir -p "$T"
  echo "· 下载 r8.jar（d8）…"
  curl -fsSL -o "$T/r8.jar" "https://maven.google.com/com/android/tools/r8/8.3.37/r8-8.3.37.jar" \
    || { echo "⚠️ r8.jar 下载失败，跳过重建（保留现有 jar）"; exit 0; }
fi
export JAVA_HOME="$JDK"
export LD_LIBRARY_PATH="$T/libs/data/data/com.termux/files/usr/lib:$LD_LIBRARY_PATH"
FTY="$ROOT/work/merge/fty"

cd "$ROOT/spider"
rm -rf out dex pack && mkdir -p out dex pack/assets

# 1) 编译（Context / Spider 是桩，仅用于编译，绝不进 dex）
"$JDK/bin/javac" -encoding UTF-8 -source 8 -target 8 -nowarn -d out $(find src -name '*.java')

# 2) d8：饭太硬 loader dex + 我们自己的类（只喂 com/github/catvod/spider 下属于我们的）
"$JDK/bin/java" -cp "$T/r8.jar" com.android.tools.r8.D8 --min-api 21 --output dex \
  "$FTY/classes.dex" $(find out/com/github/catvod/spider -maxdepth 1 \( -name 'Anime4KGuard*.class' -o -name 'Quark4K*.class' \))

# 3) 连 .so 与加密 .guard 一起重打包
cp dex/classes.dex pack/
cp "$FTY"/assets/*.so "$FTY"/assets/*.guard pack/assets/
mkdir -p pack/META-INF && cp "$FTY"/META-INF/MANIFEST.MF pack/META-INF/ 2>/dev/null || true
mkdir -p "$ROOT/jar"
( cd pack && "$JDK/bin/jar" cf "$ROOT/jar/4k_anime_fty_merged.jar" classes.dex assets META-INF )
echo "✅ 产出 jar/4k_anime_fty_merged.jar"

#!/usr/bin/env bash
# 编译 TVBox spider jar（在设备上用 Termux + 已解出的 OpenJDK/r8 完成）
# 产物：jar/4k_anime_spider.jar
set -e
T="$(cd "$(dirname "$0")" && pwd)/work/tools"
JDK="$T/jdk/data/data/com.termux/files/usr/lib/jvm/java-21-openjdk"
R8="$T/r8.jar"
export JAVA_HOME="$JDK"
export LD_LIBRARY_PATH="$T/libs/data/data/com.termux/files/usr/lib:$LD_LIBRARY_PATH"
cd "$(dirname "$0")/spider"
rm -rf out dex jarbuild && mkdir -p out dex jarbuild
# 1) 编译（桩类 android/content/Context、com/github/catvod/crawler/Spider 只用于编译）
"$JDK/bin/javac" -encoding UTF-8 -source 8 -target 8 -nowarn -d out $(find src -name '*.java')
# 2) 只把 com/github/catvod/spider/** 交给 d8 —— 桩类绝不能进 dex，会和 app 冲突
"$JDK/bin/java" -cp "$R8" com.android.tools.r8.D8 --min-api 21 --output dex \
  $(find out/com/github/catvod/spider -name '*.class')
# 3) 打包
cp dex/classes.dex jarbuild/
"$JDK/bin/jar" cf ../jar/4k_anime_spider.jar -C jarbuild classes.dex
echo "✅ 产出 jar/4k_anime_spider.jar"

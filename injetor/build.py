#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compila o injetor (Java -> dex -> jar) e gera ../espelha-input.jar.

Precisa de JDK (javac) e do Android SDK (build-tools com d8 e platforms com android.jar).
So e preciso rodar de novo se o Injector.java mudar; o jar gerado e versionado e embutido no .exe.
"""
import glob
import os
import shutil
import subprocess
import sys
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(AQUI, "src")
OUT = os.path.join(AQUI, "build")
JAR_FINAL = os.path.join(os.path.dirname(AQUI), "espelha-input.jar")


def sdk():
    for v in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if os.environ.get(v):
            return os.environ[v]
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")


def ultimo(padrao):
    achados = sorted(glob.glob(padrao))
    if not achados:
        sys.exit("nao encontrei: " + padrao)
    return achados[-1]


def main():
    base = sdk()
    android_jar = ultimo(os.path.join(base, "platforms", "android-*", "android.jar"))
    d8_jar = ultimo(os.path.join(base, "build-tools", "*", "lib", "d8.jar"))
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "classes"))
    fontes = glob.glob(os.path.join(SRC, "**", "*.java"), recursive=True)
    subprocess.check_call(
        ["javac", "--release", "8", "-Xlint:-options", "-cp", android_jar, "-d", os.path.join(OUT, "classes")] + fontes
    )
    classes = glob.glob(os.path.join(OUT, "classes", "**", "*.class"), recursive=True)
    # min-api 16: o injetor usa so reflexao e APIs antigas, entao roda de ponta a ponta no Android 4.1+
    subprocess.check_call(
        ["java", "-cp", d8_jar, "com.android.tools.r8.D8", "--release", "--min-api", "16", "--lib", android_jar, "--output", OUT] + classes
    )
    with zipfile.ZipFile(JAR_FINAL, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(OUT, "classes.dex"), "classes.dex")
    shutil.rmtree(OUT, ignore_errors=True)
    print("gerado:", JAR_FINAL, os.path.getsize(JAR_FINAL), "bytes")


if __name__ == "__main__":
    main()

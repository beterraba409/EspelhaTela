# -*- coding: utf-8 -*-
"""Ligar, desligar e acompanhar os emuladores; estados salvos (instantaneos) pelo console do emulador.

O emulador roda sem janela propria (-no-window): a tela dele aparece no espelho do Vision como a de
qualquer aparelho (`emulator-<porta>` no adb). Ele continua de pe se o Vision fechar (o Vision pergunta).
"""

import os
import re
import socket
import subprocess

import emulador_sdk

SEM_JANELA = 0x08000000 if os.name == "nt" else 0
NOVO_GRUPO = 0x00000200 if os.name == "nt" else 0
PORTAS = range(5554, 5684, 2)  # o emulador usa a porta par (console) e a seguinte (adb)


def pasta_logs():
    p = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Vision", "emuladores")
    os.makedirs(p, exist_ok=True)
    return p


def porta_em_uso(porta):
    for p in (porta, porta + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", p)) == 0:
                return True
    return False


def porta_livre(usadas=(), em_uso=porta_em_uso):
    for p in PORTAS:
        if p not in usadas and not em_uso(p):
            return p
    raise RuntimeError("nenhuma porta livre para mais um emulador")


def comando(raiz, nome, porta, modo="normal"):
    """Linha de comando do emulador. modo: normal | apagar (dados de fabrica).

    Sempre um boot limpo: abrir direto de um estado salvo (quick boot) deixa o emulador "offline" no adb
    neste emulador com WHPX; um estado salvo e carregado depois de ligar (carrega_estado), o que funciona."""
    cmd = [emulador_sdk.exe_emulador(raiz), "-avd", nome, "-port", str(porta), "-no-window", "-no-audio",
           "-no-boot-anim", "-gpu", "auto", "-no-snapshot-load", "-no-snapshot-save"]
    if modo == "apagar":
        cmd.append("-wipe-data")
    return cmd


def inicia(raiz, nome, porta, modo="normal"):
    """Liga o emulador em segundo plano e devolve (processo, serial, arquivo de log)."""
    log = os.path.join(pasta_logs(), "%s.log" % nome)
    env = dict(os.environ, ANDROID_SDK_ROOT=raiz, ANDROID_HOME=raiz)
    for k in [k for k in env if k.startswith(("_PYI", "_MEI"))]:
        env.pop(k)
    with open(log, "w", encoding="utf-8") as f:
        proc = subprocess.Popen(comando(raiz, nome, porta, modo), stdout=f, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, creationflags=SEM_JANELA | NOVO_GRUPO, close_fds=True)
    return proc, "emulator-%d" % porta, log


def emuladores_ligados(rodar, adb):
    """{serial: nome do AVD} dos emuladores que o adb ve."""
    try:
        _, out, _ = rodar([adb, "devices"], timeout=10)
    except Exception:  # noqa: BLE001
        return {}
    saida = {}
    for linha in out.splitlines():
        m = re.match(r"^(emulator-\d+)\s+(\S+)", linha.strip())
        if not m:
            continue
        nome = nome_do_avd(rodar, adb, m.group(1))
        saida[m.group(1)] = nome or ""
    return saida


def nome_do_avd(rodar, adb, serial):
    try:
        _, out, _ = rodar([adb, "-s", serial, "emu", "avd", "name"], timeout=10)
    except Exception:  # noqa: BLE001
        return ""
    linhas = [l.strip() for l in out.splitlines() if l.strip() and l.strip() != "OK"]
    return linhas[0] if linhas else ""


def ligou(rodar, adb, serial):
    """O Android terminou de ligar?"""
    try:
        _, out, _ = rodar([adb, "-s", serial, "shell", "getprop sys.boot_completed"], timeout=8)
        return out.strip() == "1"
    except Exception:  # noqa: BLE001
        return False


def desliga(rodar, adb, serial):
    """Desligamento limpo pelo console (salva o estado rapido para o proximo inicio)."""
    try:
        rodar([adb, "-s", serial, "emu", "kill"], timeout=20)
        return True
    except Exception:  # noqa: BLE001
        return False


def _console(rodar, adb, serial, *args, timeout=120):
    rc, out, err = rodar([adb, "-s", serial, "emu"] + list(args), timeout=timeout)
    texto = (out + err).strip()
    erros = [l.split(":", 1)[-1].strip() for l in texto.splitlines() if re.match(r"^KO\b", l.strip())]
    if erros:
        raise RuntimeError(erros[-1][:200] or "o emulador recusou")
    return texto


def salva_estado(rodar, adb, serial, nome):
    return _console(rodar, adb, serial, "avd", "snapshot", "save", nome)


def carrega_estado(rodar, adb, serial, nome):
    return _console(rodar, adb, serial, "avd", "snapshot", "load", nome)


def apaga_estado(rodar, adb, serial, nome):
    return _console(rodar, adb, serial, "avd", "snapshot", "delete", nome)


def nome_de_estado_valido(nome):
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,40}", nome or ""))


def ultimas_linhas(log, n=4):
    """Fim do log do emulador, para explicar por que ele nao ligou."""
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            linhas = [l.strip() for l in f if l.strip()]
    except OSError:
        return ""
    erros = [l for l in linhas if "ERROR" in l or "FATAL" in l or "PANIC" in l]
    return "\n".join((erros or linhas)[-n:])

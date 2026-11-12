# -*- coding: utf-8 -*-
"""Emuladores (AVDs) do Vision: perfis, criacao, lista e exclusao, sem avdmanager (nem Java).

Um AVD e uma pasta `<nome>.avd` com `config.ini` e um `<nome>.ini` ao lado, na pasta padrao do Android
(`%USERPROFILE%\\.android\\avd`, ou `ANDROID_AVD_HOME`). Assim o Android Studio e o Maestro tambem os veem.
Os do Vision levam o prefixo `vision-`.
"""

import os
import re
import shutil

PREFIXO = "vision-"

# perfil -> tela, densidade, RAM (MB), dados (GB), versao sugerida e aviso mostrado no assistente
PERFIS = {
    "smartpos": {"nome": "SmartPOS", "largura": 720, "altura": 1280, "dpi": 320, "ram": 3072, "dados": 6, "api": 30,
                 "descricao": "Tela de POS (720×1280), Android 11 como o GPOS e o L400. Telas e automação rodam; "
                              "pagamento com cartão não (não há leitor nem SDK de adquirente)."},
    "celular": {"nome": "Celular", "largura": 1080, "altura": 2400, "dpi": 420, "ram": 4096, "dados": 8, "api": 34,
                "descricao": "Celular moderno (1080×2400)."},
    "tablet": {"nome": "Tablet", "largura": 1600, "altura": 2560, "dpi": 320, "ram": 4096, "dados": 8, "api": 34,
               "descricao": "Tablet (1600×2560)."},
}

# API -> nome comercial
ANDROIDS = {30: "Android 11", 33: "Android 13", 34: "Android 14", 35: "Android 15", 36: "Android 16"}


def pasta_avd():
    if os.environ.get("ANDROID_AVD_HOME"):
        return os.environ["ANDROID_AVD_HOME"]
    base = os.environ.get("ANDROID_USER_HOME") or os.path.join(os.path.expanduser("~"), ".android")
    return os.path.join(base, "avd")


def nome_valido(nome):
    """Nome de AVD: letras, numeros, ponto, hifen e sublinhado (o emulador recusa o resto)."""
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,60}", nome or ""))


def sugere_nome(perfil, api, existentes):
    base = "%s%s-android%s" % (PREFIXO, perfil, {30: "11", 33: "13", 34: "14", 35: "15", 36: "16"}.get(api, api))
    nome, n = base, 2
    while nome in existentes:
        nome, n = "%s-%d" % (base, n), n + 1
    return nome


def sysdir(api, tag="google_apis", abi="x86_64"):
    """Caminho da imagem relativo a raiz do SDK, como o config.ini guarda."""
    return "system-images\\android-%d\\%s\\%s\\" % (api, tag, abi)


def config_ini(nome, perfil, api, ram=None, dados=None, tag="google_apis", abi="x86_64", rotulo=None):
    """Texto do config.ini do AVD."""
    p = PERFIS[perfil]
    linhas = [
        ("AvdId", nome),
        ("avd.ini.displayname", rotulo or "%s (%s)" % (p["nome"], ANDROIDS.get(api, "API %d" % api))),
        ("avd.ini.encoding", "UTF-8"),
        ("abi.type", abi),
        ("hw.cpu.arch", "x86_64" if abi == "x86_64" else abi),
        ("image.sysdir.1", sysdir(api, tag, abi)),
        ("tag.id", tag),
        ("tag.display", "Google APIs" if tag == "google_apis" else tag),
        ("target", "android-%d" % api),
        ("hw.lcd.width", p["largura"]),
        ("hw.lcd.height", p["altura"]),
        ("hw.lcd.density", p["dpi"]),
        ("hw.ramSize", ram or p["ram"]),
        ("disk.dataPartition.size", "%dG" % (dados or p["dados"])),
        ("hw.keyboard", "yes"),
        ("hw.gpu.enabled", "yes"),
        ("hw.gpu.mode", "auto"),
        ("hw.mainKeys", "no"),
        ("hw.camera.back", "none"),
        ("hw.camera.front", "none"),
        ("hw.audioInput", "no"),
        ("showDeviceFrame", "no"),
        ("PlayStore.enabled", "false"),
        ("fastboot.forceColdBoot", "no"),
        ("vision.perfil", perfil),
    ]
    return "".join("%s=%s\n" % (k, v) for k, v in linhas)


def le_ini(caminho):
    d = {}
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            for linha in f:
                if "=" in linha:
                    k, _, v = linha.partition("=")
                    d[k.strip()] = v.strip()
    except OSError:
        pass
    return d


def cria(nome, perfil, api, ram=None, dados=None, tag="google_apis", abi="x86_64", pasta=None):
    """Cria o AVD e devolve o caminho da pasta .avd. Levanta ValueError se o nome nao servir ou ja existir."""
    if not nome_valido(nome):
        raise ValueError("nome inválido: use letras, números, ponto, hífen ou sublinhado")
    pasta = pasta or pasta_avd()
    os.makedirs(pasta, exist_ok=True)
    avd = os.path.join(pasta, nome + ".avd")
    ini = os.path.join(pasta, nome + ".ini")
    if os.path.exists(avd) or os.path.exists(ini):
        raise ValueError("já existe um emulador chamado %s" % nome)
    os.makedirs(avd)
    with open(os.path.join(avd, "config.ini"), "w", encoding="utf-8") as f:
        f.write(config_ini(nome, perfil, api, ram, dados, tag, abi))
    with open(ini, "w", encoding="utf-8") as f:
        f.write("avd.ini.encoding=UTF-8\npath=%s\npath.rel=avd\\%s.avd\ntarget=android-%d\n" % (avd, nome, api))
    return avd


def lista(pasta=None, com_tamanho=True):
    """[{nome, rotulo, perfil, api, pasta, tamanho, do_vision}] dos AVDs na pasta (do Vision primeiro).
    com_tamanho=False nao percorre as pastas (para consultas frequentes)."""
    pasta = pasta or pasta_avd()
    saida = []
    if not os.path.isdir(pasta):
        return saida
    for arq in sorted(os.listdir(pasta)):
        if not arq.endswith(".ini"):
            continue
        nome = arq[:-4]
        ini = le_ini(os.path.join(pasta, arq))
        avd = ini.get("path") if ini.get("path") and os.path.isdir(ini.get("path")) else os.path.join(pasta, nome + ".avd")
        if not os.path.isdir(avd):
            continue
        cfg = le_ini(os.path.join(avd, "config.ini"))
        m = re.search(r"android-(\d+)", cfg.get("image.sysdir.1", "") + " " + cfg.get("target", ini.get("target", "")))
        saida.append({"nome": nome, "rotulo": cfg.get("avd.ini.displayname", nome), "perfil": cfg.get("vision.perfil", ""),
                      "api": int(m.group(1)) if m else None, "pasta": avd, "tamanho": tamanho_pasta(avd) if com_tamanho else 0,
                      "do_vision": nome.startswith(PREFIXO), "config": cfg})
    saida.sort(key=lambda a: (not a["do_vision"], a["nome"].lower()))
    return saida


def tamanho_pasta(pasta):
    total = 0
    for raiz, _, arqs in os.walk(pasta):
        for a in arqs:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
    return total


def exclui(nome, pasta=None):
    pasta = pasta or pasta_avd()
    ini = os.path.join(pasta, nome + ".ini")
    avd = le_ini(ini).get("path") or os.path.join(pasta, nome + ".avd")
    shutil.rmtree(avd, ignore_errors=True)
    try:
        os.remove(ini)
    except OSError:
        pass
    return not os.path.exists(avd)


def instantaneos(avd_pasta):
    """Estados salvos do AVD (pastas em snapshots/, menos o automatico do desligamento)."""
    snaps = os.path.join(avd_pasta, "snapshots")
    if not os.path.isdir(snaps):
        return []
    return sorted(n for n in os.listdir(snaps) if os.path.isdir(os.path.join(snaps, n)) and n != "default_boot")

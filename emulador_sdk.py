# -*- coding: utf-8 -*-
"""Android SDK minimo para os emuladores do Vision: acha um SDK no PC ou baixa o necessario direto do
repositorio oficial do Google (sem sdkmanager e sem Java), conferindo o checksum e continuando de onde parou.
"""

import hashlib
import os
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

REPO = "https://dl.google.com/android/repository/"
REPO_EMULADOR = REPO + "repository2-3.xml"
REPO_IMAGENS = REPO + "sys-img/%s/sys-img2-3.xml"  # % tag (google_apis, google_apis_playstore)
CANAL_ESTAVEL = "channel-0"
SEM_JANELA = 0x08000000 if os.name == "nt" else 0


def pasta_vision():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Vision", "android-sdk")


def candidatos_sdk():
    vistos = []
    for c in (os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk"), pasta_vision()):
        if c and c not in vistos:
            vistos.append(os.path.normpath(c))
    return vistos


def exe_emulador(raiz):
    return os.path.join(raiz, "emulator", "emulator.exe" if os.name == "nt" else "emulator")


def raiz_sdk():
    """O SDK com emulador que o Vision usa: um que ja exista no PC, senao a pasta do proprio Vision
    (onde ele baixa o que faltar)."""
    for c in candidatos_sdk():
        if os.path.isfile(exe_emulador(c)):
            return c
    return pasta_vision()


def pasta_imagem(raiz, api, tag="google_apis", abi="x86_64"):
    return os.path.join(raiz, "system-images", "android-%d" % api, tag, abi)


def imagem_completa(raiz, api, tag="google_apis", abi="x86_64"):
    """A imagem esta inteira? (um download antigo interrompido deixa a pasta sem o kernel)"""
    p = pasta_imagem(raiz, api, tag, abi)
    tem_kernel = any(os.path.isfile(os.path.join(p, k)) for k in ("kernel-ranchu", "kernel-ranchu-64", "kernel-qemu"))
    return tem_kernel and os.path.isfile(os.path.join(p, "system.img"))


# ---------------------------------------------------------------- repositorio
def _sem_ns(tag):
    return tag.rsplit("}", 1)[-1]


def _filho(el, nome):
    for f in el:
        if _sem_ns(f.tag) == nome:
            return f
    return None


def _texto(el, *caminho):
    for nome in caminho:
        el = _filho(el, nome) if el is not None else None
    return (el.text or "").strip() if el is not None else ""


def le_repositorio(xml, so="windows", arq="x64"):
    """{'pacotes': {path: {revisao, canal, licenca, size, sha1, url, api, tag}}, 'licencas': {id: texto}}.
    Para cada path fica o arquivo deste sistema operacional; entre canais, o mais estavel (menor numero)."""
    raiz = ET.fromstring(xml)
    licencas = {el.get("id"): (el.text or "").strip() for el in raiz if _sem_ns(el.tag) == "license"}
    pacotes = {}
    for el in raiz:
        if _sem_ns(el.tag) != "remotePackage":
            continue
        path = el.get("path")
        rev = tuple(int(_texto(el, "revision", p) or 0) for p in ("major", "minor", "micro"))
        canal = (_filho(el, "channelRef").get("ref") if _filho(el, "channelRef") is not None else CANAL_ESTAVEL)
        lic = _filho(el, "uses-license").get("ref") if _filho(el, "uses-license") is not None else ""
        arquivo = None
        arqs = _filho(el, "archives")
        for a in (arqs if arqs is not None else []):
            os_a, arq_a = _texto(a, "host-os"), _texto(a, "host-arch")
            if os_a and os_a != so or arq_a and arq_a != arq:
                continue
            c = _filho(a, "complete")
            ck = _filho(c, "checksum") if c is not None else None
            arquivo = {"size": int(_texto(c, "size") or 0), "sha1": (ck.text or "").strip() if ck is not None else "",
                       "url": _texto(c, "url")}
            break
        if not arquivo:
            continue
        det = _filho(el, "type-details")
        api = _texto(det, "api-level")
        info = dict(arquivo, revisao=rev, canal=canal, licenca=lic, api=int(api) if api.isdigit() else None,
                    tag=_texto(det, "tag", "id"), nome=_texto(el, "display-name"))
        atual = pacotes.get(path)
        if atual is None or (canal, tuple(-x for x in rev)) < (atual["canal"], tuple(-x for x in atual["revisao"])):
            pacotes[path] = info
    return {"pacotes": pacotes, "licencas": licencas}


def baixa_texto(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "Vision"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def catalogo(tag="google_apis"):
    """(emulador, {api: imagem}, licencas) do repositorio do Google."""
    rep = le_repositorio(baixa_texto(REPO_EMULADOR))
    emu = rep["pacotes"].get("emulator")
    if emu:
        emu["url_completa"] = REPO + emu["url"]
    img = le_repositorio(baixa_texto(REPO_IMAGENS % tag))
    imagens = {}
    for path, p in img["pacotes"].items():
        if path.endswith(";%s;x86_64" % tag) and p["api"]:
            p["url_completa"] = (REPO_IMAGENS % tag).rsplit("/", 1)[0] + "/" + p["url"]
            p["path"] = path
            imagens[p["api"]] = p
    licencas = dict(rep["licencas"], **img["licencas"])
    return emu, imagens, licencas


# ---------------------------------------------------------------- download
class Cancelado(Exception):
    pass


def sha1_arquivo(caminho):
    h = hashlib.sha1()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def baixa(url, destino, sha1="", total=0, progresso=lambda feito, total: None, cancelado=lambda: False):
    """Baixa para `destino` continuando um `.part` de uma tentativa anterior; confere o SHA-1 no fim."""
    if os.path.isfile(destino) and (not sha1 or sha1_arquivo(destino) == sha1):
        progresso(os.path.getsize(destino), total or os.path.getsize(destino))
        return destino
    parcial = destino + ".part"
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    feito = os.path.getsize(parcial) if os.path.isfile(parcial) else 0
    headers = {"User-Agent": "Vision"}
    if feito:
        headers["Range"] = "bytes=%d-" % feito
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        if feito and r.status != 206:  # o servidor ignorou o Range: recomeca
            feito = 0
        modo = "ab" if feito else "wb"
        with open(parcial, modo) as f:
            while True:
                if cancelado():
                    raise Cancelado()
                bloco = r.read(1 << 18)
                if not bloco:
                    break
                f.write(bloco)
                feito += len(bloco)
                progresso(feito, total)
    if sha1 and sha1_arquivo(parcial) != sha1:
        os.remove(parcial)
        raise ValueError("o arquivo baixado veio corrompido (checksum diferente); tente de novo")
    os.replace(parcial, destino)
    return destino


def extrai(zip_caminho, destino, cancelado=lambda: False):
    """Descompacta tirando a pasta de cima do zip (`emulator/`, `x86_64/`) e trocando o que havia antes."""
    tmp = destino + ".novo"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_caminho) as z:
        nomes = z.namelist()
        topo = os.path.commonprefix([n.split("/", 1)[0] + "/" for n in nomes if "/" in n]) if nomes else ""
        for n in nomes:
            if cancelado():
                shutil.rmtree(tmp, ignore_errors=True)
                raise Cancelado()
            rel = n[len(topo):] if topo and n.startswith(topo) else n
            if not rel or rel.endswith("/"):
                continue
            alvo = os.path.join(tmp, *rel.split("/"))
            os.makedirs(os.path.dirname(alvo), exist_ok=True)
            with z.open(n) as src, open(alvo, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    shutil.rmtree(destino, ignore_errors=True)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    os.replace(tmp, destino)
    return destino


# ---------------------------------------------------------------- requisitos
def checa_aceleracao(raiz):
    """(ok, texto) do `emulator -accel-check` (WHPX/AEHD no Windows)."""
    exe = exe_emulador(raiz)
    if not os.path.isfile(exe):
        return None, "emulador ainda não baixado"
    try:
        r = subprocess.run([exe, "-accel-check"], capture_output=True, timeout=60, creationflags=SEM_JANELA)
        saida = (r.stdout + r.stderr).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]
    ok = "is installed and usable" in saida or r.returncode == 0 and "accel" in saida and "not" not in saida.lower()
    linhas = [l.strip() for l in saida.splitlines() if l.strip() and l.strip() not in ("accel:", "accel")]
    return ok, (linhas[-1] if linhas else saida.strip())[:300]


def memoria_total_gb():
    try:
        import ctypes

        class M(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = M()
        m.dwLength = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullTotalPhys / (1 << 30)
    except Exception:  # noqa: BLE001
        return None


def disco_livre_gb(pasta):
    p = pasta
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    try:
        return shutil.disk_usage(p or os.path.expanduser("~")).free / (1 << 30)
    except OSError:
        return None


def requisitos(raiz, precisa_gb=0.0):
    """[(ok, item, detalhe)] para mostrar antes de criar: aceleracao, memoria e disco."""
    itens = []
    ok, txt = checa_aceleracao(raiz)
    if ok is None:
        itens.append((None, "Aceleração", "verificada depois de baixar o emulador"))
    else:
        itens.append((ok, "Aceleração", "pronta (%s)" % txt if ok else
                      "indisponível: ligue a virtualização na BIOS e a “Plataforma do Hipervisor do Windows” "
                      "(pode precisar da TI). Detalhe: %s" % txt))
    ram = memoria_total_gb()
    if ram is not None:
        itens.append((ram >= 7.5, "Memória", "%.0f GB%s" % (ram, "" if ram >= 7.5 else ": o recomendado são 8 GB ou mais")))
    livre = disco_livre_gb(raiz)
    if livre is not None:
        precisa = precisa_gb + 4
        itens.append((livre >= precisa, "Disco", "%.0f GB livres (precisa de uns %.0f GB)" % (livre, precisa)))
    return itens

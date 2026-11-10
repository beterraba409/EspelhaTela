# -*- coding: utf-8 -*-
"""Le pacote e versao de um APK sem o Android SDK (sem aapt): o AndroidManifest.xml dentro do APK
e um XML binario (AXML); aqui so o necessario para a tag <manifest>.

Sem Tkinter e sem aparelho: testavel em testes_sem_tela.py.
"""
import re
import struct
import zipfile

_STRING_POOL, _RESOURCE_MAP, _START_ELEMENT = 0x0001, 0x0180, 0x0102
_ID_VERSION_CODE, _ID_VERSION_NAME = 0x0101021B, 0x0101021C  # android:versionCode / android:versionName
_TIPO_STRING, _TIPO_INT_DEC, _TIPO_INT_HEX = 0x03, 0x10, 0x11


def _strings(dados, ini):
    """Pool de strings do AXML (UTF-8 ou UTF-16)."""
    _, cab, _, n, _, flags, inicio_txt, _ = struct.unpack_from("<HHIIIIII", dados, ini)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from("<%dI" % n, dados, ini + cab)
    base = ini + inicio_txt
    saida = []
    for off in offsets:
        p = base + off
        if utf8:
            p += 2 if dados[p] & 0x80 else 1  # tamanho em caracteres (ignorado)
            tam = dados[p]
            if tam & 0x80:
                tam = ((tam & 0x7F) << 8) | dados[p + 1]
                p += 1
            p += 1
            saida.append(dados[p:p + tam].decode("utf-8", "replace"))
        else:
            tam = struct.unpack_from("<H", dados, p)[0]
            if tam & 0x8000:
                tam = ((tam & 0x7FFF) << 16) | struct.unpack_from("<H", dados, p + 2)[0]
                p += 2
            p += 2
            saida.append(dados[p:p + tam * 2].decode("utf-16-le", "replace"))
    return saida


def le_manifesto(dados):
    """{'pacote', 'versao', 'codigo', 'split'} da tag <manifest> de um AndroidManifest.xml binario."""
    if len(dados) < 8 or struct.unpack_from("<H", dados, 0)[0] != 0x0003:
        raise ValueError("AndroidManifest.xml nao esta no formato binario esperado")
    strings, ids = [], []
    p = struct.unpack_from("<H", dados, 2)[0]
    while p + 8 <= len(dados):
        tipo, cab, tam = struct.unpack_from("<HHI", dados, p)
        if tam < 8:
            break
        if tipo == _STRING_POOL:
            strings = _strings(dados, p)
        elif tipo == _RESOURCE_MAP:
            ids = list(struct.unpack_from("<%dI" % ((tam - cab) // 4), dados, p + cab))
        elif tipo == _START_ELEMENT:
            nome = struct.unpack_from("<I", dados, p + 20)[0]
            if nome < len(strings) and strings[nome] == "manifest":
                ini_attr, tam_attr, n_attr = struct.unpack_from("<HHH", dados, p + 24)
                info = {"pacote": "", "versao": "", "codigo": None, "split": ""}
                for i in range(n_attr):
                    a = p + 16 + ini_attr + i * tam_attr
                    _, nome_a, bruto, _, _, tipo_v, valor = struct.unpack_from("<IIIHBBI", dados, a)
                    rid = ids[nome_a] if nome_a < len(ids) else None
                    nome_txt = strings[nome_a] if nome_a < len(strings) else ""
                    texto = strings[bruto] if bruto != 0xFFFFFFFF and bruto < len(strings) else (
                        strings[valor] if tipo_v == _TIPO_STRING and valor < len(strings) else None)
                    if rid == _ID_VERSION_CODE or nome_txt == "versionCode":
                        info["codigo"] = valor if tipo_v in (_TIPO_INT_DEC, _TIPO_INT_HEX) else int(texto or 0)
                    elif rid == _ID_VERSION_NAME or nome_txt == "versionName":
                        info["versao"] = texto if texto is not None else str(valor)
                    elif nome_txt == "package":
                        info["pacote"] = texto or ""
                    elif nome_txt == "split":
                        info["split"] = texto or ""
                return info
        p += tam
    raise ValueError("tag <manifest> nao encontrada")


def le_apk(caminho):
    """Pacote e versao de um arquivo .apk."""
    with zipfile.ZipFile(caminho) as z:
        return le_manifesto(z.read("AndroidManifest.xml"))


def le_apks(caminhos):
    """Para um app dividido (varias APKs), usa a APK base (a que nao e 'split')."""
    infos = []
    for c in caminhos:
        try:
            infos.append(le_apk(c))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile, struct.error, IndexError):
            continue
    base = next((i for i in infos if not i["split"]), infos[0] if infos else None)
    return base


def versao_no_aparelho(saida_dumpsys):
    """(versao, codigo) da saida de 'dumpsys package <pacote>'; (None, None) se nao instalado."""
    nome = re.search(r"versionName=(\S+)", saida_dumpsys or "")
    cod = re.search(r"versionCode=(\d+)", saida_dumpsys or "")
    if not nome and not cod:
        return None, None
    return (nome.group(1) if nome else ""), (int(cod.group(1)) if cod else None)


def tipo_de_mudanca(codigo_apk, codigo_aparelho):
    """'nova', 'atualizacao', 'mesma' ou 'downgrade' (pelo versionCode, que e o que o Android compara)."""
    if codigo_aparelho is None:
        return "nova"
    if codigo_apk is None:
        return "desconhecida"
    if codigo_apk > codigo_aparelho:
        return "atualizacao"
    return "mesma" if codigo_apk == codigo_aparelho else "downgrade"

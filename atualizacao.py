# -*- coding: utf-8 -*-
"""Busca de atualizacoes nas Releases do GitHub: compara versoes, acha o instalador e o baixa.

Sem Tkinter: a janela chama `ultima_versao` e `baixar` em segundo plano. Repositorio privado usa
um token (so leitura) passado pela janela; o token nunca vai para o servidor que entrega o arquivo.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
AGENTE = "Vision-atualizador"


def versao_tupla(texto):
    """'v1.10' -> (1, 10). Ignora prefixo e o que vier depois dos numeros."""
    m = re.search(r"(\d+(?:\.\d+)*)", texto or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def mais_nova(candidata, atual):
    return versao_tupla(candidata) > versao_tupla(atual)


class SemTokenNoRedirecionamento(urllib.request.HTTPRedirectHandler):
    """O GitHub redireciona o download para outro servidor (armazenamento): o token nao vai junto."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        novo = super().redirect_request(req, fp, code, msg, headers, newurl)
        if novo is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            for nome in list(novo.headers):
                if nome.lower() == "authorization":
                    del novo.headers[nome]
            novo.unredirected_hdrs.pop("Authorization", None)
        return novo


_abridor = urllib.request.build_opener(SemTokenNoRedirecionamento)


def _pedido(url, token=None, aceita="application/vnd.github+json"):
    cab = {"User-Agent": AGENTE, "Accept": aceita}
    if token:
        cab["Authorization"] = "Bearer " + token
    return urllib.request.Request(url, headers=cab)


def escolhe_release(releases, prefixo_tag, prefixo_arquivo):
    """A release publicada mais nova cuja tag comeca com `prefixo_tag` e que traz o instalador."""
    melhor = None
    for r in releases:
        tag = r.get("tag_name") or ""
        if r.get("draft") or r.get("prerelease") or not tag.startswith(prefixo_tag):
            continue
        arquivo = next((a for a in r.get("assets") or [] if (a.get("name") or "").startswith(prefixo_arquivo)
                        and a.get("name", "").lower().endswith(".exe")), None)
        if arquivo is None:
            continue
        versao = tag[len(prefixo_tag):]
        if melhor is None or versao_tupla(versao) > versao_tupla(melhor["versao"]):
            melhor = {
                "versao": versao,
                "titulo": r.get("name") or tag,
                "notas": (r.get("body") or "").strip(),
                "pagina": r.get("html_url") or "",
                "arquivo": arquivo.get("name"),
                "tamanho": arquivo.get("size") or 0,
                "url_api": arquivo.get("url") or "",
                "url_publica": arquivo.get("browser_download_url") or "",
            }
    return melhor


def ultima_versao(repo, prefixo_tag, prefixo_arquivo, token=None, timeout=15):
    """Consulta o GitHub. Devolve o dict de `escolhe_release` (ou None) e levanta RuntimeError com o motivo."""
    url = "%s/repos/%s/releases?per_page=30" % (API, repo)
    try:
        with _abridor.open(_pedido(url, token), timeout=timeout) as r:
            dados = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and token:
            raise RuntimeError("o token do GitHub foi recusado (vencido ou sem acesso ao reposit\u00f3rio)")
        if e.code == 404:
            raise RuntimeError("reposit\u00f3rio n\u00e3o encontrado" + ("" if token else " (privado? falta o token)"))
        raise RuntimeError("o GitHub respondeu %d" % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError("sem conex\u00e3o com o GitHub (%s)" % getattr(e, "reason", e))
    return escolhe_release(dados, prefixo_tag, prefixo_arquivo)


def baixar(info, destino, token=None, progresso=None, timeout=60):
    """Baixa o instalador para `destino` (arquivo .part renomeado ao final). progresso(feito, total)."""
    if token:  # repositorio privado: pela API, com o token so no GitHub
        pedido = _pedido(info["url_api"], token, aceita="application/octet-stream")
    else:
        pedido = _pedido(info["url_publica"], aceita="application/octet-stream")
    parcial = destino + ".part"
    feito = 0
    with _abridor.open(pedido, timeout=timeout) as r, open(parcial, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("tamanho") or 0)
        while True:
            bloco = r.read(256 * 1024)
            if not bloco:
                break
            f.write(bloco)
            feito += len(bloco)
            if progresso:
                progresso(feito, total)
    if total and feito != total:
        os.remove(parcial)
        raise RuntimeError("download incompleto (%d de %d bytes)" % (feito, total))
    os.replace(parcial, destino)
    return destino

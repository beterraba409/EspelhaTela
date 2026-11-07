# -*- coding: utf-8 -*-
"""Descobre com qual servidor adb (porta) cada adb conversa e quais aparelhos cada servidor tem.

Motivo: um `adb.cmd`/`adb.bat` no PATH pode ser um wrapper que repassa `-P <porta>` para o adb.exe
real. O EspelhaTela entao conversa com um servidor sem aparelhos enquanto o aparelho esta no servidor
padrao (5037), e a lista aparece vazia sem explicacao.

Nada aqui sobe ou derruba servidor: a consulta aos servidores e feita pelo protocolo do adb direto
no socket (`host:devices`), que so responde se o servidor ja estiver no ar.
"""

import os
import re
import socket

PORTA_PADRAO = 5037
PORTAS_CONHECIDAS = (5037, 5038, 5039)


def _expande(texto, env):
    """Troca %VAR% (cmd) pelo valor do ambiente; variavel desconhecida fica como esta."""
    return re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", lambda m: env.get(m.group(1), env.get(m.group(1).upper(), m.group(0))), texto)


def porta_do_ambiente(env=None):
    env = os.environ if env is None else env
    try:
        return int(env.get("ADB_SERVER_PORT", "") or PORTA_PADRAO)
    except ValueError:
        return PORTA_PADRAO


def analisa_adb(caminho, env=None):
    """Retorna {caminho, exe, porta, wrapper}.

    - adb.exe comum: porta = ADB_SERVER_PORT do ambiente ou 5037.
    - wrapper .cmd/.bat: le o texto, acha o adb.exe que ele chama e a porta que ele forca
      (`-P <n>`, `DEFAULT_ADB_SERVER_PORT=<n>` ou similar). ADB_SERVER_PORT do ambiente,
      quando o wrapper o respeita, vence o padrao do wrapper.
    """
    env = dict(os.environ if env is None else env)
    info = {"caminho": caminho, "exe": caminho, "porta": porta_do_ambiente(env), "wrapper": False}
    if not caminho or os.path.splitext(caminho)[1].lower() not in (".cmd", ".bat"):
        return info
    info["wrapper"] = True
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            texto = f.read()
    except OSError:
        return info
    sets = {}
    for m in re.finditer(r'(?im)^\s*set\s+"?([A-Za-z_][A-Za-z0-9_]*)=([^"\r\n]*)"?', texto):
        sets[m.group(1).upper()] = _expande(m.group(2).strip(), {**env, **sets})
    exe = next((v for v in sets.values() if v.lower().endswith("adb.exe")), "")
    if not exe:
        m = re.search(r'"?([A-Za-z]:[^"\r\n]*?adb\.exe)"?', _expande(texto, {**env, **sets}), re.I)
        exe = m.group(1) if m else ""
    if exe:
        info["exe"] = exe
    respeita_env = "ADB_SERVER_PORT%" in texto.upper()
    porta_wrapper = None
    for chave, valor in sets.items():
        if chave.endswith("PORT") and valor.isdigit():
            porta_wrapper = int(valor)
    if porta_wrapper is None:
        m = re.search(r"-P\s+(\d{4,5})\b", texto)
        porta_wrapper = int(m.group(1)) if m else None
    if respeita_env and env.get("ADB_SERVER_PORT", "").isdigit():
        info["porta"] = int(env["ADB_SERVER_PORT"])
    elif porta_wrapper is not None:
        info["porta"] = porta_wrapper
    return info


def aparelhos_no_servidor(porta, timeout=1.5):
    """Lista [{serial, estado}] do servidor adb na porta, ou None se nao houver servidor ali.

    Fala o protocolo do adb direto (4 hex de tamanho + `host:devices`): nao inicia servidor."""
    try:
        with socket.create_connection(("127.0.0.1", int(porta)), timeout=timeout) as s:
            s.settimeout(timeout)
            pedido = b"host:devices"
            s.sendall(b"%04x" % len(pedido) + pedido)
            resp = _le(s, 4)
            if resp != b"OKAY":
                return None
            tam = int(_le(s, 4), 16)
            corpo = _le(s, tam).decode("utf-8", "replace") if tam else ""
    except (OSError, ValueError):
        return None
    itens = []
    for linha in corpo.splitlines():
        p = linha.split()
        if len(p) >= 2:
            itens.append({"serial": p[0], "estado": p[1]})
    return itens


def _le(s, n):
    dados = b""
    while len(dados) < n:
        bloco = s.recv(n - len(dados))
        if not bloco:
            raise OSError("conexao fechada")
        dados += bloco
    return dados


def servidores(portas_extra=(), consulta=aparelhos_no_servidor):
    """{porta: [aparelhos]} so das portas com servidor adb no ar."""
    achados = {}
    for porta in sorted(set(PORTAS_CONHECIDAS) | {int(p) for p in portas_extra if p}):
        lista = consulta(porta)
        if lista is not None:
            achados[porta] = lista
    return achados


def sugestao(info, achados):
    """Se o adb em uso fala com um servidor sem aparelho prontos e outro servidor tem, devolve
    {porta, aparelhos, texto}; senao None."""
    prontos = lambda lst: [a for a in (lst or []) if a.get("estado") == "device"]  # noqa: E731
    if prontos(achados.get(info["porta"])):
        return None
    outros = [(p, prontos(lst)) for p, lst in achados.items() if p != info["porta"] and prontos(lst)]
    if not outros:
        return None
    porta, aparelhos = max(outros, key=lambda x: len(x[1]))
    origem = "o wrapper %s" % info["caminho"] if info["wrapper"] else "o adb %s" % info["caminho"]
    seriais = ", ".join(a["serial"] for a in aparelhos)
    situacao = "sem aparelhos" if info["porta"] in achados else "que nem esta no ar"
    texto = (
        "%s conversa com o servidor adb da porta %d, %s. O servidor da porta %d tem %d aparelho(s): %s."
        % (origem[0].upper() + origem[1:], info["porta"], situacao, porta, len(aparelhos), seriais)
    )
    return {"porta": porta, "aparelhos": aparelhos, "texto": texto}

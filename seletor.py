# -*- coding: utf-8 -*-
"""Seletor de identificador: le a arvore da tela (uiautomator dump), acha o elemento sob o mouse
e monta o seletor do Maestro pronto para colar no YAML.

No React Native o `testID` chega ao Android como `resource-id`, que e o que o `id:` do Maestro
compara. Sem id, o Maestro aceita o texto visivel ou o accessibilityLabel (content-desc) em
`text:`. Ultimo recurso: `point:` em porcentagem da tela.

Cuidado: `uiautomator dump` registra um UiAutomation no aparelho; rodar com um flow do Maestro
em andamento pode derrubar o driver dele. Por isso a leitura so acontece quando o usuario pede.
"""

import re
import xml.etree.ElementTree as ET

ARQ_REMOTO = "/data/local/tmp/espelha-ui.xml"
_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def extrai_xml(texto):
    """Recorta o XML da saida do dump (que vem com 'UI hierchary dumped to: ...' no fim)."""
    ini = texto.find("<?xml")
    if ini < 0:
        ini = texto.find("<hierarchy")
    fim = texto.rfind("</hierarchy>")
    if ini < 0 or fim < 0:
        return ""
    return texto[ini:fim + len("</hierarchy>")]


def le_nos(xml):
    """Lista plana de nos: {attrs..., bounds:(x1,y1,x2,y2), pai:int|None, prof:int}."""
    raiz = ET.fromstring(xml)
    nos = []

    def visita(el, pai, prof):
        for filho in el:
            if filho.tag != "node":
                continue
            m = _BOUNDS.match(filho.get("bounds", ""))
            b = tuple(int(v) for v in m.groups()) if m else (0, 0, 0, 0)
            no = {k: filho.get(k, "") for k in ("resource-id", "text", "content-desc", "class", "package", "clickable", "enabled", "checked", "focused", "scrollable", "hint")}
            no.update(bounds=b, pai=pai, prof=prof)
            nos.append(no)
            visita(filho, len(nos) - 1, prof + 1)

    visita(raiz, None, 0)
    return nos


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def no_no_ponto(nos, x, y):
    """Indice do menor no visivel que contem o ponto (empate: o mais fundo, desenhado por cima)."""
    melhor, chave = None, None
    for i, no in enumerate(nos):
        b = no["bounds"]
        if _area(b) == 0 or not (b[0] <= x < b[2] and b[1] <= y < b[3]):
            continue
        k = (_area(b), -no["prof"], -i)
        if chave is None or k < chave:
            melhor, chave = i, k
    return melhor


def ancestral_com(nos, i, campo, saltos=4):
    """O proprio no ou o ancestral mais proximo (ate `saltos` niveis) com `campo` preenchido."""
    n = 0
    while i is not None and n <= saltos:
        if nos[i].get(campo, "").strip():
            return i
        i, n = nos[i]["pai"], n + 1
    return None


def descendente_com_texto(nos, i):
    """Primeiro descendente com texto (botao do RN costuma ter o texto num filho)."""
    b = nos[i]["bounds"]
    for j in range(i + 1, len(nos)):
        if nos[j]["prof"] <= nos[i]["prof"]:
            break
        t = nos[j]["text"].strip()
        if t and _area(nos[j]["bounds"]) and nos[j]["bounds"][0] >= b[0] and nos[j]["bounds"][2] <= b[2]:
            return j
    return None


def textos_no_ponto(nos, x, y, limite=4):
    """Textos para copiar a partir de um ponto da tela, do mais especifico ao mais geral: o do menor
    elemento sob o ponto, o de um filho (botao do RN guarda o texto num filho) e o dos que o contem.
    Usa o texto e, sem ele, a descricao de acessibilidade."""
    contem = [k for k, no in enumerate(nos)
              if _area(no["bounds"]) and no["bounds"][0] <= x < no["bounds"][2] and no["bounds"][1] <= y < no["bounds"][3]]
    contem.sort(key=lambda k: (_area(nos[k]["bounds"]), -nos[k]["prof"]))
    saida = []

    def junta(t):
        t = (t or "").strip()
        if t and t not in saida:
            saida.append(t)

    if contem:
        # o texto de um filho so vale para botao (clicavel); num fundo vazio pegaria um texto qualquer da tela
        d = descendente_com_texto(nos, contem[0]) if nos[contem[0]].get("clickable") == "true" else None
        junta(nos[contem[0]]["text"])
        junta(nos[contem[0]]["content-desc"])
        if d is not None:
            junta(nos[d]["text"])
    for k in contem[1:]:
        junta(nos[k]["text"])
        junta(nos[k]["content-desc"])
    return saida[:limite]


def texto_da_tela(nos):
    """Todos os textos visiveis em ordem de leitura (de cima para baixo e da esquerda para a direita)."""
    itens = []
    for no in nos:
        t = no["text"].strip()
        b = no["bounds"]
        if t and _area(b):
            itens.append((b[1] // 12, b[0], t))  # mesma linha: topo parecido (12 px de folga)
    linhas = []
    for _, _, t in sorted(itens):
        if not linhas or linhas[-1] != t:
            linhas.append(t)
    return chr(10).join(linhas)  # uma linha por texto


def yaml_str(valor):
    """String YAML entre aspas duplas. Quebra de linha vira espaco (o Maestro compara assim)."""
    v = " ".join(valor.split())
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def curto(rid):
    """`pacote:id/nome` (view nativa) -> `nome`; testID do RN fica como esta."""
    return rid.split(":id/", 1)[1] if ":id/" in rid else rid


def clicavel(nos, i, saltos=4):
    """O proprio no ou o ancestral mais proximo que recebe clique."""
    n = 0
    while i is not None and n <= saltos:
        if nos[i]["clickable"] == "true":
            return i
        i, n = nos[i]["pai"], n + 1
    return None


def _por_id(nos, j, rotulo, conferir=False):
    rid = nos[j]["resource-id"]
    valor = curto(rid)
    iguais = [k for k, n in enumerate(nos) if n["resource-id"] == rid and _area(n["bounds"])]
    extra = ""
    if len(iguais) > 1:
        extra = "\n    index: %d" % iguais.index(j) if j in iguais else ""
        rotulo += " - %d elementos com esse id" % len(iguais)
    itens = [(rotulo, "- tapOn:\n    id: %s%s" % (yaml_str(valor), extra))]
    if conferir:
        itens.append(("conferir se aparece", "- assertVisible:\n    id: %s%s" % (yaml_str(valor), extra)))
    return itens


def seletores(nos, i, tela):
    """Sugestoes [(rotulo, yaml)] para o no i. `tela` = (largura, altura) do aparelho."""
    no = nos[i]
    saida = []
    j = ancestral_com(nos, i, "resource-id")
    if j is not None:
        rotulo = "id" if j == i else "id (do elemento pai)"
        saida += _por_id(nos, j, rotulo, conferir=True)
    c = clicavel(nos, i)
    if c is not None and c != j and nos[c]["resource-id"].strip():
        saida += _por_id(nos, c, "id do elemento clic\u00e1vel que cont\u00e9m este")
    t = i if no["text"].strip() else descendente_com_texto(nos, i)
    if t is not None:
        saida.append(("texto", "- tapOn: %s" % yaml_str(nos[t]["text"])))
    desc = no["content-desc"].strip()
    if desc and desc != (nos[t]["text"].strip() if t is not None else None) and desc != no["resource-id"]:
        saida.append(("accessibilityLabel", "- tapOn: %s" % yaml_str(desc)))
    if no["class"].endswith("EditText"):
        saida.append(("digitar no campo", "- inputText: \"\""))
    b = no["bounds"]
    if tela and tela[0] and tela[1]:
        cx = round(100.0 * (b[0] + b[2]) / 2 / tela[0])
        cy = round(100.0 * (b[1] + b[3]) / 2 / tela[1])
        saida.append(("ponto (\u00faltimo recurso)", "- tapOn:\n    point: \"%d%%,%d%%\"" % (cx, cy)))
    return saida


def resumo(no):
    """Uma linha para o rodape/titulo do painel."""
    partes = []
    if no["resource-id"]:
        partes.append("id=%s" % curto(no["resource-id"]))
    if no["text"].strip():
        partes.append('texto="%s"' % " ".join(no["text"].split())[:40])
    if no["content-desc"].strip():
        partes.append('desc="%s"' % " ".join(no["content-desc"].split())[:40])
    partes.append(no["class"].rsplit(".", 1)[-1] or "?")
    return "  ".join(partes)


def ler_tela(rodar, adb, serial):
    """Roda o dump e devolve (nos, erro). Tenta direto pela saida padrao; se o aparelho nao
    aceitar, grava em /data/local/tmp e le. Uma nova tentativa se a tela estiver animando."""
    erro = ""
    for _ in range(2):
        try:
            _, out, err = rodar([adb, "-s", serial, "exec-out", "uiautomator dump /dev/tty"], timeout=25)
            xml = extrai_xml(out)
            if not xml:
                _, out2, err2 = rodar([adb, "-s", serial, "exec-out", "uiautomator dump %s >/dev/null 2>&1; cat %s; rm -f %s" % (ARQ_REMOTO, ARQ_REMOTO, ARQ_REMOTO)], timeout=25)
                xml = extrai_xml(out2)
                err = err or err2 or out.strip()
            if xml:
                return le_nos(xml), ""
            erro = (err or out).strip()[:160] or "o aparelho n\u00e3o devolveu a \u00e1rvore da tela"
        except Exception as e:  # noqa: BLE001
            erro = str(e)[:160]
    return None, erro

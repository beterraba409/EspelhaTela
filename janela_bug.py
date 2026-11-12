# -*- coding: utf-8 -*-
"""Reportar bug: junta print, video dos ultimos segundos, logcat e dados do aparelho numa pasta + .zip,
com o texto do card no padrao do Jira (Descricao / Teste realizado / Resultado esperado / Resultado obtido)."""

import datetime
import os
import re
import threading
import tkinter as tk
import unicodedata
import zipfile
from tkinter import filedialog, ttk

import visual

CAMPOS = [("descricao", "Descrição"), ("teste", "Teste realizado"),
          ("esperado", "Resultado esperado"), ("obtido", "Resultado obtido")]
MINUTOS_LOGCAT = 5


def pasta_padrao():
    base = os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.isdir(base):
        base = os.path.expanduser("~")
    return os.path.join(base, "Vision", "Bugs")


def nome_pasta(titulo, agora):
    """'2026-11-11_1620-placa-nao-encontrada' (sem acento e sem simbolo, ate 50 letras do titulo)."""
    t = unicodedata.normalize("NFKD", titulo or "").encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:50].rstrip("-") or "bug"
    return "%s-%s" % (agora.strftime("%Y-%m-%d_%H%M"), t)


def le_getprop(saida):
    """Saida de COMANDO_APARELHO -> dict."""
    d = {}
    for linha in (saida or "").splitlines():
        if "=" in linha:
            k, _, v = linha.partition("=")
            d[k.strip()] = v.strip()
    return d


COMANDO_APARELHO = ("for p in ro.product.manufacturer ro.product.model ro.build.version.release ro.build.version.sdk "
                    "ro.serialno; do echo \"$p=$(getprop $p)\"; done")


def texto_bug(titulo, campos, ambiente, anexos):
    """Texto do card (Markdown, que o Jira aceita colado)."""
    partes = ["**%s**" % (titulo.strip() or "Bug"), ""]
    for chave, rotulo in CAMPOS:
        partes += ["**%s**" % rotulo, (campos.get(chave) or "").strip() or "-", ""]
    partes.append("**Ambiente**")
    partes += ["- %s" % a for a in ambiente]
    if anexos:
        partes += ["", "**Anexos:** " + ", ".join(anexos)]
    return "\n".join(partes).strip() + "\n"


def ambiente_de(props, nome_aparelho, pacote, versao_app, agora, versao_vision):
    fab = props.get("ro.product.manufacturer", "").strip()
    modelo = props.get("ro.product.model", "").strip()
    aparelho = " ".join(x for x in (fab.capitalize() if fab and fab.lower() not in modelo.lower() else "", modelo) if x) or nome_aparelho
    andr = props.get("ro.build.version.release", "?")
    linhas = ["Aparelho: %s (Android %s, SDK %s), serial %s" % (aparelho, andr, props.get("ro.build.version.sdk", "?"),
                                                              props.get("ro.serialno") or nome_aparelho)]
    if pacote:
        linhas.append("App em primeiro plano: %s %s" % (pacote, versao_app or ""))
    linhas.append("Data e hora: %s" % agora.strftime("%d/%m/%Y %H:%M:%S"))
    linhas.append("Registrado com o Vision %s" % versao_vision)
    return [l.strip() for l in linhas]


def compacta(pasta):
    """<pasta>.zip ao lado da pasta, com os arquivos dela."""
    destino = pasta.rstrip("\\/") + ".zip"
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in sorted(os.listdir(pasta)):
            z.write(os.path.join(pasta, nome), nome)
    return destino


class Coleta:
    """O que e coletado no instante do clique em Reportar bug (antes de a tela mudar)."""

    def __init__(self):
        self.pronto = threading.Event()
        self.print_png = None
        self.props = {}
        self.pacote = ""
        self.versao_app = ""
        self.quadros = []
        self.t_clique = None
        self.erros = []


class JanelaBug:
    """`ao_gerar(dados)` com titulo, campos, anexos escolhidos e a pasta; chamado ao clicar em Gerar."""

    def __init__(self, raiz, config, serial, coleta, ao_gerar, icone=None, ao_cancelar=None):
        self.config, self.coleta, self.ao_gerar, self.ao_cancelar = config, coleta, ao_gerar, ao_cancelar
        self.gerou = False
        w = self.win = tk.Toplevel(raiz)
        w.title("Reportar bug")
        if icone:
            icone(w)
        w.configure(bg=visual.BG)
        w.minsize(560, 600)
        w.transient(raiz)
        f = self.f = visual.fontes(w)

        tk.Label(w, text="Reportar bug", bg=visual.BG, fg=visual.FG, font=(f["forte"], 14)).pack(anchor="w", padx=20, pady=(18, 0))
        tk.Label(w, text="A tela, o vídeo e o log de %s foram guardados agora. Descreva o problema e gere o relatório." % serial,
                 bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9), wraplength=600, justify="left").pack(anchor="w", padx=20, pady=(2, 10))
        corpo = tk.Frame(w, bg=visual.BG)
        corpo.pack(fill="both", expand=True, padx=20)
        tk.Label(corpo, text="Título", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w")
        self.var_titulo = tk.StringVar()
        ent = ttk.Entry(corpo, textvariable=self.var_titulo)
        ent.pack(fill="x", ipady=3, pady=(4, 8))
        self.textos = {}
        for chave, rotulo in CAMPOS:
            tk.Label(corpo, text=rotulo, bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w")
            t = tk.Text(corpo, height=3, bg=visual.BG2, fg=visual.FG, insertbackground=visual.FG, relief="flat", wrap="word",
                        font=(f["texto"], 10), padx=8, pady=6, highlightthickness=1, highlightbackground=visual.BORDA,
                        highlightcolor=visual.ACENTO, undo=True)
            t.pack(fill="both", expand=True, pady=(4, 8))
            t.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
            self.textos[chave] = t

        tk.Label(corpo, text="Anexos", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w", pady=(2, 4))
        caixa = tk.Frame(corpo, bg=visual.BG2, highlightthickness=1, highlightbackground=visual.BORDA, padx=12, pady=8)
        caixa.pack(fill="x")
        dur = 0.0 if len(coleta.quadros) < 2 else coleta.quadros[-1][0] - coleta.quadros[0][0]
        self.var_print = tk.BooleanVar(value=True)
        self.var_video = tk.BooleanVar(value=dur >= 1)
        self.var_log = tk.BooleanVar(value=True)
        self.var_info = tk.BooleanVar(value=True)
        estilo = "Bug.TCheckbutton"
        ttk.Style(w).configure(estilo, background=visual.BG2)
        self.cks = []
        for var, texto, ok in ((self.var_print, "Print da tela em resolução total (print.png)", True),
                               (self.var_video, ("Vídeo dos últimos %d s antes de clicar (ultimos-segundos.mp4)" % round(dur)) if dur >= 1
                                else "Vídeo dos últimos segundos (nada guardado ainda: o espelho estava parado ou a memória desligada)", dur >= 1),
                               (self.var_log, "Logcat dos últimos %d minutos (logcat.txt)" % MINUTOS_LOGCAT, True),
                               (self.var_info, "Aparelho, Android e o app em primeiro plano com a versão (no texto do card)", True)):
            ck = ttk.Checkbutton(caixa, text=texto, variable=var, style=estilo, state="normal" if ok else "disabled")
            ck.pack(anchor="w", pady=1)
        self.var_memoria = tk.BooleanVar(value=config.get("guardar_recentes", True))
        ttk.Checkbutton(corpo, text="Guardar sempre os últimos 30 s do espelho para o Reportar bug (usa cerca de 10 MB de memória)",
                        variable=self.var_memoria).pack(anchor="w", pady=(8, 0))

        tk.Label(corpo, text="Salvar em", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w", pady=(10, 4))
        lp = tk.Frame(corpo, bg=visual.BG)
        lp.pack(fill="x")
        pasta = config.get("pasta_bugs") or ""
        self.var_pasta = tk.StringVar(value=pasta if os.path.isdir(pasta) else pasta_padrao())
        ttk.Entry(lp, textvariable=self.var_pasta, state="readonly").pack(side="left", fill="x", expand=True, ipady=2)
        ttk.Button(lp, text="Alterar…", command=self._escolhe_pasta).pack(side="left", padx=(8, 0))

        self.status = tk.Label(w, text="", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9), anchor="w")
        self.status.pack(fill="x", padx=20, pady=(8, 0))
        tk.Frame(w, bg=visual.BORDA, height=1).pack(fill="x", pady=(8, 0))
        botoes = tk.Frame(w, bg=visual.BG)
        botoes.pack(fill="x", padx=20, pady=14)
        self.bt_ok = visual.Botao(botoes, "bug", "Gerar relatório", comando=self._gerar, largura=180, altura=38)
        self.bt_ok.define(ativo=True)
        self.bt_ok.pack(side="right")
        visual.Botao(botoes, "fechar", "Cancelar", comando=w.destroy, largura=110, altura=38).pack(side="right", padx=(0, 8))
        w.bind("<Escape>", lambda e: w.destroy())
        w.bind("<Destroy>", self._destruida)  # Cancelar, Esc ou o X: o que foi guardado no clique e apagado
        w.update_idletasks()
        w.geometry("640x%d+%d+%d" % (min(w.winfo_reqheight(), w.winfo_screenheight() - 80), raiz.winfo_rootx() + 40, max(0, raiz.winfo_rooty() - 10)))
        ent.focus_set()
        self._mostra_coleta()

    def _mostra_coleta(self):
        try:
            if self.coleta.pronto.is_set():
                extra = ("  (%s)" % "; ".join(self.coleta.erros)) if self.coleta.erros else ""
                self.status.configure(text="tela e dados do aparelho guardados" + extra, fg=visual.FG2)
            else:
                self.status.configure(text="guardando a tela e os dados do aparelho…", fg=visual.ACENTO)
                self.win.after(300, self._mostra_coleta)
        except tk.TclError:
            pass

    def _escolhe_pasta(self):
        p = filedialog.askdirectory(title="Onde salvar os relatórios de bug?", initialdir=self.var_pasta.get(), parent=self.win)
        if p:
            self.var_pasta.set(os.path.normpath(p))

    def _gerar(self):
        titulo = self.var_titulo.get().strip()
        if not titulo:
            self.status.configure(text="Dê um título ao bug (vira o nome da pasta).", fg=visual.PERIGO)
            return
        dados = {
            "titulo": titulo,
            "campos": {k: t.get("1.0", "end").strip() for k, t in self.textos.items()},
            "print": self.var_print.get(), "video": self.var_video.get(), "logcat": self.var_log.get(), "info": self.var_info.get(),
            "pasta": self.var_pasta.get(),
        }
        self.config.update(pasta_bugs=dados["pasta"], guardar_recentes=bool(self.var_memoria.get()))
        self.gerou = True
        self.win.destroy()
        self.ao_gerar(dados)

    def _destruida(self, e):
        if e.widget is self.win and not self.gerou and self.ao_cancelar:
            self.gerou = True  # uma vez so
            self.ao_cancelar()

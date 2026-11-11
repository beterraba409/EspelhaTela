# -*- coding: utf-8 -*-
"""Janela "Gravar tela": escolha do formato (MP4 ou GIF), pasta, nome do arquivo e o que fazer no fim."""

import datetime
import os
import re
import tkinter as tk
from tkinter import filedialog, ttk

import gravacao
import visual

FORMATOS = {
    "mp4": {
        "icone": "\uE714", "reserva": "\U0001F3AC", "titulo": "MP4", "tipo": "V\u00eddeo",
        "resumo": "Fiel ao que aparece no espelho, sem limite de tempo.",
        "itens": ("30 quadros por segundo", "Abre em qualquer player, no Teams e no Jira",
                  "Arquivo leve: cerca de 0,5 MB a cada 10 s"),
    },
    "gif": {
        "icone": "\uE8B9", "reserva": "\U0001F5BC", "titulo": "GIF", "tipo": "Anima\u00e7\u00e3o",
        "resumo": "Roda sozinho, sem player: bom para colar num chamado ou chat.",
        "itens": ("10 quadros por segundo, %d px de largura" % gravacao.LARGURA_GIF,
                  "At\u00e9 %d s (para sozinho no limite)" % gravacao.LIMITE_GIF,
                  "Menos cores que o v\u00eddeo"),
    },
}


def pasta_padrao():
    return os.path.join(os.path.expanduser("~"), "Videos", "Vision")


def nome_sugerido(serial, agora=None):
    agora = agora or datetime.datetime.now()
    return "gravacao-%s-%s" % (re.sub(r"[^A-Za-z0-9._-]", "_", serial or "aparelho"), agora.strftime("%Y%m%d-%H%M%S"))


def caminho_final(pasta, nome, formato):
    """Pasta + nome com a extensao do formato (troca .gif por .mp4 e vice-versa; tira caracteres invalidos)."""
    nome = re.sub(r'[<>:"/\\|?*]', "_", (nome or "").strip()) or "gravacao"
    base, ext = os.path.splitext(nome)
    if ext.lower() in (".mp4", ".gif"):
        nome = base
    return os.path.normpath(os.path.join(pasta, nome + "." + formato))


class JanelaGravacao:
    """`ao_iniciar(formato, caminho, abrir_pasta)` quando o usuario clica em Iniciar gravacao."""

    def __init__(self, raiz, config, serial, ao_iniciar, icone=None):
        self.config, self.ao_iniciar = config, ao_iniciar
        w = self.win = tk.Toplevel(raiz)
        w.title("Gravar tela")
        if icone:
            icone(w)
        w.configure(bg=visual.BG)
        w.resizable(False, False)
        w.transient(raiz)
        self.f = f = visual.fontes(w)
        self.formato = config.get("formato_gravacao") if config.get("formato_gravacao") in FORMATOS else "mp4"
        pasta = config.get("pasta_gravacao") or ""
        self.var_pasta = tk.StringVar(value=pasta if os.path.isdir(pasta) else pasta_padrao())
        self.var_nome = tk.StringVar(value=nome_sugerido(serial))
        self.var_abrir = tk.BooleanVar(value=config.get("abrir_pasta_gravacao", True))

        tk.Label(w, text="Gravar tela", bg=visual.BG, fg=visual.FG, font=(f["forte"], 14)).pack(anchor="w", padx=20, pady=(18, 0))
        tk.Label(w, text="Grava o que aparece no espelho de %s at\u00e9 voc\u00ea clicar em Parar grava\u00e7\u00e3o." % (serial or "aparelho"),
                 bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9)).pack(anchor="w", padx=20, pady=(2, 12))

        tk.Label(w, text="Formato", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w", padx=20, pady=(0, 6))
        linha = tk.Frame(w, bg=visual.BG)
        linha.pack(fill="x", padx=20)
        self.cartoes = {}
        for chave in FORMATOS:
            self.cartoes[chave] = self._cartao(linha, chave)
        self._marca()

        tk.Label(w, text="Salvar em", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w", padx=20, pady=(16, 6))
        lp = tk.Frame(w, bg=visual.BG)
        lp.pack(fill="x", padx=20)
        ttk.Entry(lp, textvariable=self.var_pasta, state="readonly").pack(side="left", fill="x", expand=True, ipady=2)
        ttk.Button(lp, text="Alterar\u2026", command=self._escolhe_pasta).pack(side="left", padx=(8, 0))
        tk.Label(w, text="Nome do arquivo", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w", padx=20, pady=(12, 6))
        ln = tk.Frame(w, bg=visual.BG)
        ln.pack(fill="x", padx=20)
        ent = ttk.Entry(ln, textvariable=self.var_nome)
        ent.pack(side="left", fill="x", expand=True, ipady=2)
        self.lb_ext = tk.Label(ln, text="", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 10), width=5, anchor="w")
        self.lb_ext.pack(side="left", padx=(6, 0))
        ttk.Checkbutton(w, text="Abrir a pasta quando a grava\u00e7\u00e3o for salva", variable=self.var_abrir).pack(anchor="w", padx=20, pady=(12, 0))

        tk.Frame(w, bg=visual.BORDA, height=1).pack(fill="x", pady=(16, 0))
        botoes = tk.Frame(w, bg=visual.BG)
        botoes.pack(fill="x", padx=20, pady=14)
        ok = visual.Botao(botoes, "gravar", "Iniciar grava\u00e7\u00e3o", comando=self._iniciar, largura=170, altura=38)
        ok.define(ativo=True)
        ok.pack(side="right")
        visual.Botao(botoes, "fechar", "Cancelar", comando=w.destroy, largura=110, altura=38).pack(side="right", padx=(0, 8))
        self._atualiza_ext()
        w.bind("<Return>", lambda e: self._iniciar())
        w.bind("<Escape>", lambda e: w.destroy())
        w.update_idletasks()
        x = raiz.winfo_rootx() + max(0, (raiz.winfo_width() - w.winfo_reqwidth()) // 2)
        y = raiz.winfo_rooty() + max(0, (raiz.winfo_height() - w.winfo_reqheight()) // 3)
        w.geometry("+%d+%d" % (x, y))
        ent.focus_set()
        ent.icursor("end")
        w.grab_set()

    def _cartao(self, pai, chave):
        d, f = FORMATOS[chave], self.f
        c = tk.Frame(pai, bg=visual.BG2, highlightthickness=2, highlightbackground=visual.BORDA, padx=14, pady=12, cursor="arrow")
        c.pack(side="left", fill="both", expand=True, padx=(0, 10) if chave == "mp4" else 0)
        topo = tk.Frame(c, bg=visual.BG2)
        topo.pack(fill="x")
        icone, fonte_icone = (d["icone"], f["icones"]) if f["icones"] else (d["reserva"], "Segoe UI Symbol")
        lb_ic = tk.Label(topo, text=icone, bg=visual.BG2, fg=visual.ACENTO, font=(fonte_icone, 20))
        lb_ic.pack(side="left")
        tit = tk.Frame(topo, bg=visual.BG2)
        tit.pack(side="left", padx=(10, 0))
        tk.Label(tit, text=d["titulo"], bg=visual.BG2, fg=visual.FG, font=(f["forte"], 12)).pack(anchor="w")
        tk.Label(tit, text=d["tipo"], bg=visual.BG2, fg=visual.FG2, font=(f["texto"], 9)).pack(anchor="w")
        marca = tk.Label(topo, text="", bg=visual.BG2, fg=visual.ACENTO, font=(f["forte"], 12))
        marca.pack(side="right", anchor="n")
        tk.Label(c, text=d["resumo"], bg=visual.BG2, fg=visual.FG, font=(f["texto"], 9), wraplength=220, justify="left").pack(anchor="w", pady=(10, 6))
        for item in d["itens"]:
            tk.Label(c, text="\u2022  " + item, bg=visual.BG2, fg=visual.FG2, font=(f["texto"], 9), wraplength=220, justify="left").pack(anchor="w")

        def escolhe(_e=None):
            self.formato = chave
            self._marca()
            self._atualiza_ext()

        for wd in [c, topo, tit, lb_ic, marca] + list(c.winfo_children()) + list(tit.winfo_children()):
            wd.bind("<Button-1>", escolhe)
        return c, marca

    def _marca(self):
        for chave, (c, marca) in self.cartoes.items():
            sel = chave == self.formato
            c.configure(highlightbackground=visual.ACENTO if sel else visual.BORDA, highlightcolor=visual.ACENTO if sel else visual.BORDA)
            marca.configure(text="\u2713" if sel else "")

    def _atualiza_ext(self):
        self.lb_ext.configure(text="." + self.formato)

    def _escolhe_pasta(self):
        p = filedialog.askdirectory(title="Onde salvar a grava\u00e7\u00e3o?", initialdir=self.var_pasta.get(), parent=self.win)
        if p:
            self.var_pasta.set(os.path.normpath(p))

    def _iniciar(self):
        pasta = self.var_pasta.get()
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError as e:
            from tkinter import messagebox
            return messagebox.showerror("Gravar tela", "N\u00e3o d\u00e1 para salvar em %s:\n%s" % (pasta, e), parent=self.win)
        caminho = caminho_final(pasta, self.var_nome.get(), self.formato)
        if os.path.exists(caminho):
            from tkinter import messagebox
            if not messagebox.askyesno("Gravar tela", "J\u00e1 existe %s.\n\nSubstituir?" % os.path.basename(caminho), icon="warning", parent=self.win):
                return
        self.config.update(formato_gravacao=self.formato, pasta_gravacao=pasta, abrir_pasta_gravacao=bool(self.var_abrir.get()))
        self.win.destroy()
        self.ao_iniciar(self.formato, caminho, bool(self.var_abrir.get()))

# -*- coding: utf-8 -*-
"""Janela "Configuracoes": liga e desliga cada ferramenta da barra lateral. Desligada, a ferramenta some
do app (botao, atalho de teclado e o que ela faz ao soltar arquivos); ligada, volta no mesmo lugar."""

import tkinter as tk

import visual


def ocultas_do_config(config, chaves):
    """Ferramentas desligadas salvas no config.json (ignora nomes que nao existem mais)."""
    return {c for c in (config.get("ferramentas_ocultas") or []) if c in chaves}


class Interruptor(tk.Canvas):
    """Interruptor liga/desliga desenhado (como o do Windows 11)."""

    def __init__(self, pai, ligado, ao_mudar, largura=42, altura=22):
        super().__init__(pai, width=largura, height=altura, bg=pai.cget("bg"), highlightthickness=0, bd=0, cursor="arrow")
        self.ligado, self.ao_mudar, self.l, self.a = ligado, ao_mudar, largura, altura
        self.bind("<Button-1>", lambda e: self.alterna())
        self.desenha()

    def alterna(self):
        self.ligado = not self.ligado
        self.desenha()
        self.ao_mudar(self.ligado)

    def define(self, ligado):
        self.ligado = ligado
        self.desenha()

    def desenha(self):
        self.delete("all")
        l, a, r = self.l, self.a, self.a / 2
        fundo = visual.ACENTO if self.ligado else visual.BG
        borda = visual.ACENTO if self.ligado else visual.BORDA_HOVER
        self.create_oval(1, 1, a - 1, a - 1, fill=fundo, outline=borda)
        self.create_oval(l - a + 1, 1, l - 1, a - 1, fill=fundo, outline=borda)
        self.create_rectangle(r, 1, l - r, a - 1, fill=fundo, outline="")
        self.create_line(r, 1, l - r, 1, fill=borda)
        self.create_line(r, a - 1, l - r, a - 1, fill=borda)
        d = 6
        x = l - r if self.ligado else r
        self.create_oval(x - d, r - d, x + d, r + d, fill="#ffffff" if self.ligado else visual.FG2, outline="")


class JanelaConfig:
    """`ferramentas`: [(chave, icone, nome, descricao)] na ordem da barra; `ao_mudar(ocultas)` a cada troca."""

    def __init__(self, raiz, ferramentas, ocultas, ao_mudar, icone=None):
        self.ferramentas, self.ocultas, self.ao_mudar = ferramentas, set(ocultas), ao_mudar
        w = self.win = tk.Toplevel(raiz)
        w.title("Configurações")
        if icone:
            icone(w)
        w.configure(bg=visual.BG)
        w.resizable(False, False)
        w.transient(raiz)
        f = visual.fontes(w)
        tk.Label(w, text="Configurações", bg=visual.BG, fg=visual.FG, font=(f["forte"], 14)).pack(anchor="w", padx=20, pady=(18, 0))
        tk.Label(w, text="Escolha as ferramentas que aparecem na barra lateral. Desligada, a ferramenta some do Vision\n"
                         "(junto com o atalho de teclado dela); ligada, volta no mesmo lugar.",
                 bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9), justify="left").pack(anchor="w", padx=20, pady=(2, 12))
        tk.Label(w, text="Ferramentas", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w", padx=20, pady=(0, 6))
        lista = tk.Frame(w, bg=visual.BG2, highlightthickness=1, highlightbackground=visual.BORDA)
        lista.pack(fill="x", padx=20)
        self.chaves = {}
        for n, (chave, ic, nome, desc) in enumerate(ferramentas):
            if n:
                tk.Frame(lista, bg=visual.BORDA, height=1).pack(fill="x")
            linha = tk.Frame(lista, bg=visual.BG2, padx=12, pady=6)
            linha.pack(fill="x")
            glifo, fonte = visual.glifo(w, ic)
            tk.Label(linha, text=glifo, bg=visual.BG2, fg=visual.ACENTO, font=(fonte, 14), width=2).pack(side="left")
            textos = tk.Frame(linha, bg=visual.BG2)
            textos.pack(side="left", fill="x", expand=True, padx=(10, 12))
            tk.Label(textos, text=nome, bg=visual.BG2, fg=visual.FG, font=(f["forte"], 10), anchor="w").pack(anchor="w")
            tk.Label(textos, text=desc, bg=visual.BG2, fg=visual.FG2, font=(f["texto"], 9), anchor="w", justify="left",
                     wraplength=500).pack(anchor="w")
            sw = Interruptor(linha, chave not in self.ocultas, lambda lig, c=chave: self._muda(c, lig))
            sw.pack(side="right")
            self.chaves[chave] = sw
            for wd in (linha, textos) + tuple(textos.winfo_children()):
                wd.bind("<Button-1>", lambda e, s=sw: s.alterna())
        self.contagem = tk.Label(w, text="", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9), anchor="w")
        self.contagem.pack(fill="x", padx=20, pady=(8, 0))
        tk.Frame(w, bg=visual.BORDA, height=1).pack(fill="x", pady=(10, 0))
        botoes = tk.Frame(w, bg=visual.BG)
        botoes.pack(fill="x", padx=20, pady=14)
        ok = visual.Botao(botoes, "aplicar", "Fechar", comando=w.destroy, largura=110, altura=36)
        ok.define(ativo=True)
        ok.pack(side="right")
        visual.Botao(botoes, "atualizar", "Mostrar todas", comando=self._todas, largura=150, altura=36).pack(side="right", padx=(0, 8))
        w.bind("<Escape>", lambda e: w.destroy())
        self._conta()
        w.update_idletasks()
        x = raiz.winfo_rootx() + max(0, (raiz.winfo_width() - w.winfo_reqwidth()) // 2)
        y = min(raiz.winfo_rooty() + 20, w.winfo_screenheight() - w.winfo_reqheight() - 70)  # sempre cabe na tela
        w.geometry("+%d+%d" % (max(0, x), max(0, y)))

    def _muda(self, chave, ligado):
        (self.ocultas.discard if ligado else self.ocultas.add)(chave)
        self._conta()
        self.ao_mudar(set(self.ocultas))

    def _todas(self):
        self.ocultas.clear()
        for sw in self.chaves.values():
            sw.define(True)
        self._conta()
        self.ao_mudar(set())

    def _conta(self):
        total = len(self.ferramentas)
        vis = total - len(self.ocultas)
        self.contagem.configure(text="%d de %d ferramentas aparecendo" % (vis, total))

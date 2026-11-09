# -*- coding: utf-8 -*-
"""Pecas visuais da janela principal: botao com contorno e cantos arredondados, icones do
Windows (Segoe Fluent Icons / Segoe MDL2 Assets), barra lateral com rolagem e etiquetas do rodape.

So Tkinter: nada aqui fala com o aparelho.
"""
import tkinter as tk
import tkinter.font as tkfont

# paleta (fundo escuro, contornos finos)
BG = "#1c1c1e"
BG2 = "#2a2a2d"
HOVER = "#36363b"
PRESSIONADO = "#232326"
BORDA = "#3c3c42"
BORDA_HOVER = "#5c5c66"
FG = "#e9e9ec"
FG2 = "#8e8e93"
DESATIVADO = "#55555a"
ACENTO = "#7c4dff"
ACENTO_FUNDO = "#2f2550"
VERDE = "#30d158"
AMBAR = "#ffb340"
AZUL = "#3b9eff"
PERIGO = "#e5484d"

# icones (mesmo codigo nas duas fontes de icones do Windows) e o simbolo de reserva para Windows antigo
ICONES = {
    "menu": ("", "☰"),
    "pausar": ("", "⏸"),
    "retomar": ("", "▶"),
    "captura": ("", "\U0001F4F7"),
    "tela_cheia": ("", "⛶"),
    "voltar": ("", "◁"),
    "inicio": ("", "○"),
    "recentes": ("", "□"),
    "volume_menos": ("", "\U0001F509"),
    "volume_mais": ("", "\U0001F50A"),
    "energia": ("", "⏻"),
    "seletor": ("", "\U0001F3AF"),
    "instalar": ("", "⬇"),
    "desinstalar": ("", "\U0001F5D1"),
    "logcat": ("", "\U0001F4DC"),
    "aparelho": ("", "\U0001F4F1"),
    "arquivos": ("", "\U0001F4C1"),
    "memoria": ("", "\U0001F4CA"),
    "atualizar": ("", "↻"),
    "rede": ("", "+"),
    "janela": ("", "↗"),
    "aparencia": ("", "🎨"),
    "tema_escuro": ("", "☾"),
    "tema_claro": ("", "☀"),
    "aplicar": ("", "✓"),
    "fechar": ("", "✕"),
}

_fontes = {}


def fontes(raiz):
    """Fontes de texto e de icones disponiveis nesta maquina (Windows 11, 10 ou reserva)."""
    if not _fontes:
        familias = set(tkfont.families(raiz))
        texto = next((f for f in ("Segoe UI Variable Text", "Segoe UI") if f in familias), "TkDefaultFont")
        forte = next((f for f in ("Segoe UI Variable Text Semibold", "Segoe UI Semibold") if f in familias), texto)
        icones = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in familias), None)
        _fontes.update(texto=texto, forte=forte, icones=icones)
    return _fontes


def glifo(raiz, nome):
    """(caractere, fonte) do icone: o do Windows quando existe, senao o simbolo de reserva."""
    f = fontes(raiz)
    novo, reserva = ICONES[nome]
    return (novo, f["icones"]) if f["icones"] else (reserva, "Segoe UI Symbol")


CONTORNO = "#0b0b0d"
TELA_FUNDO = "#000000"  # em volta da imagem do aparelho

# temas: as cores acima sao as do escuro; aplica_tema troca todas antes de a janela ser montada
TEMAS = {
    "escuro": dict(BG="#1c1c1e", BG2="#2a2a2d", HOVER="#36363b", PRESSIONADO="#232326", BORDA="#3c3c42",
                   BORDA_HOVER="#5c5c66", FG="#e9e9ec", FG2="#8e8e93", DESATIVADO="#55555a", VERDE="#30d158",
                   AMBAR="#ffb340", AZUL="#3b9eff", PERIGO="#e5484d", CONTORNO="#0b0b0d", TELA_FUNDO="#000000"),
    "claro": dict(BG="#f3f3f6", BG2="#ffffff", HOVER="#ebebf0", PRESSIONADO="#dedee5", BORDA="#d2d2da",
                  BORDA_HOVER="#a5a5b2", FG="#1d1d22", FG2="#6a6a74", DESATIVADO="#b2b2ba", VERDE="#14883c",
                  AMBAR="#b86a00", AZUL="#1f6fe0", PERIGO="#d12f36", CONTORNO="#ffffff", TELA_FUNDO="#d9d9df"),
}
# cor de destaque: (destaque, fundo do botao ligado no escuro, no claro)
DESTAQUES = {
    "roxo": ("#7c4dff", "#2f2550", "#ebe4ff"),
    "azul": ("#2f7cf6", "#1b2d4f", "#e1ecff"),
    "verde": ("#1fa463", "#153b28", "#ddf4e7"),
    "laranja": ("#f07a1a", "#47290f", "#fdecdd"),
    "rosa": ("#e04f8f", "#481c30", "#fce4ef"),
}
TEMA = "escuro"


def aplica_tema(tema="escuro", destaque="roxo"):
    """Troca a paleta (claro/escuro e cor de destaque). Chamar antes de montar as janelas."""
    global ACENTO, ACENTO_FUNDO, TEMA
    tema = tema if tema in TEMAS else "escuro"
    destaque = destaque if destaque in DESTAQUES else "roxo"
    globals().update(TEMAS[tema])
    cor, fundo_escuro, fundo_claro = DESTAQUES[destaque]
    ACENTO, ACENTO_FUNDO, TEMA = cor, (fundo_claro if tema == "claro" else fundo_escuro), tema
    return tema, destaque


def texto_com_contorno(c, x, y, texto, fonte, cor, anchor="w", contorno=None):
    """Texto com uma borda de 1 px em volta (escura no tema escuro, clara no claro): letras nitidas."""
    contorno = contorno or CONTORNO
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        c.create_text(x + dx, y + dy, text=texto, font=fonte, fill=contorno, anchor=anchor)
    return c.create_text(x, y, text=texto, font=fonte, fill=cor, anchor=anchor)


def _retangulo_arredondado(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, splinesteps=12, **kw)


class Botao(tk.Canvas):
    """Botao desenhado: contorno fino, cantos arredondados, icone do Windows e, se houver, texto.

    Estados: normal, sob o mouse, pressionado, desativado e ativo (alternancia ligada, como o Seletor).
    """

    def __init__(self, pai, icone, texto="", comando=None, largura=44, altura=36, raio=7, cor_icone=None):
        super().__init__(pai, width=largura, height=altura, bg=pai.cget("bg"), highlightthickness=0, bd=0,
                         cursor="arrow", takefocus=0)
        self.icone, self.texto, self.comando, self.raio = icone, texto, comando, raio
        self.cor_icone = cor_icone  # cor fixa do icone (ex.: azul no Wi-Fi); None segue o texto
        self.desativado = self.ativo = self._sob = self._press = False
        self.bind("<Enter>", lambda e: self._muda(sob=True), add="+")
        self.bind("<Leave>", lambda e: self._muda(sob=False, press=False), add="+")
        self.bind("<ButtonPress-1>", lambda e: self._muda(press=True), add="+")
        self.bind("<ButtonRelease-1>", self._solta, add="+")
        self.bind("<Configure>", lambda e: self.desenha(), add="+")

    def _muda(self, sob=None, press=None):
        if sob is not None:
            self._sob = sob
        if press is not None:
            self._press = press
        self.desenha()

    def _solta(self, e):
        dentro = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        acionar = self._press and dentro and not self.desativado
        self._muda(press=False)
        if acionar and self.comando:
            self.comando()

    def define(self, icone=None, texto=None, desativado=None, ativo=None):
        if icone is not None:
            self.icone = icone
        if texto is not None:
            self.texto = texto
        if desativado is not None:
            self.desativado = desativado
        if ativo is not None:
            self.ativo = ativo
        self.desenha()

    def desenha(self):
        self.delete("all")
        w = max(self.winfo_width(), int(self.cget("width")))
        h = max(self.winfo_height(), int(self.cget("height")))
        if w < 4 or h < 4:
            return
        if self.desativado:
            fundo, borda, cor = BG2, BORDA, DESATIVADO
        elif self.ativo:
            fundo, borda, cor = ACENTO_FUNDO, ACENTO, ("#ffffff" if TEMA == "escuro" else FG)
        elif self._press:
            fundo, borda, cor = PRESSIONADO, BORDA_HOVER, FG
        elif self._sob:
            fundo, borda, cor = HOVER, BORDA_HOVER, ("#ffffff" if TEMA == "escuro" else FG)
        else:
            fundo, borda, cor = BG2, BORDA, FG
        _retangulo_arredondado(self, 1, 1, w - 2, h - 2, self.raio, fill=fundo, outline=borda, width=1)
        car, fonte_ic = glifo(self, self.icone)
        cor_ic = self.cor_icone if (self.cor_icone and not self.desativado) else cor
        f = fontes(self)
        tam_ic = 12 if f["icones"] else 11
        if self.texto:
            self.create_text(17, h / 2, text=car, font=(fonte_ic, tam_ic), fill=cor_ic, anchor="center")
            self.create_text(34, h / 2, text=self.texto, font=(f["forte"], 10), fill=cor, anchor="w")
        else:
            self.create_text(w / 2, h / 2, text=car, font=(fonte_ic, tam_ic), fill=cor_ic, anchor="center")


class Rolavel(tk.Frame):
    """Coluna com rolagem pela roda do mouse (sem barra visivel): nada fica cortado em tela baixa."""

    def __init__(self, pai, largura, **kw):
        super().__init__(pai, bg=BG, width=largura, **kw)
        self.tela = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0, width=largura)
        self.tela.pack(fill="both", expand=True)
        self.dentro = tk.Frame(self.tela, bg=BG)
        self._id = self.tela.create_window(0, 0, window=self.dentro, anchor="nw", width=largura)
        self.dentro.bind("<Configure>", lambda e: self.tela.configure(scrollregion=self.tela.bbox("all")))
        self.tela.bind("<Configure>", lambda e: self.tela.itemconfigure(self._id, width=e.width))
        self.bind_all("<MouseWheel>", self._roda, add="+")

    def _roda(self, e):
        w = e.widget
        while w is not None:  # so rola quando o mouse esta sobre esta coluna
            if w is self:
                if self.dentro.winfo_height() > self.tela.winfo_height():
                    self.tela.yview_scroll(-1 if e.delta > 0 else 1, "units")
                return
            w = getattr(w, "master", None)


def titulo_secao(pai, texto):
    """Titulo de secao: barra de destaque a esquerda e texto maior."""
    c = tk.Canvas(pai, height=28, bg=BG, highlightthickness=0, bd=0)
    c.pack(fill="x", pady=(12, 4))
    c.create_rectangle(2, 7, 5, 22, fill=ACENTO, outline="")
    c.create_text(13, 15, text=texto, font=(fontes(pai)["forte"], 11), fill=FG, anchor="w")


def linha_de_icones(pai, itens, largura_total, altura=36, espaco=5):
    """Varios botoes so de icone lado a lado; devolve os botoes na ordem."""
    linha = tk.Frame(pai, bg=BG)
    linha.pack(fill="x", pady=(0, espaco))
    n = len(itens)
    w = (largura_total - espaco * (n - 1)) // n
    botoes = []
    for i, (icone, comando) in enumerate(itens):
        b = Botao(linha, icone, comando=comando, largura=w, altura=altura)
        b.pack(side="left", padx=(0 if i == 0 else espaco, 0))
        botoes.append(b)
    return botoes


class Rodape(tk.Frame):
    """Rodape: uma mensagem (avisos, dicas, erros) ou, sem mensagem, etiquetas de estado."""

    def __init__(self, pai, versao=""):
        super().__init__(pai, bg=BG)
        tk.Frame(self, bg=BORDA, height=1).pack(fill="x")
        self.corpo = tk.Frame(self, bg=BG)
        self.corpo.pack(fill="x", padx=8, pady=6)
        f = fontes(pai)["texto"]
        self.versao = None
        if versao:  # fica sempre a direita, com mensagem ou com etiquetas
            self.versao = tk.Label(self.corpo, text=versao, bg=BG, fg=FG2, font=(f, 8))
            self.versao.pack(side="right", padx=(8, 0))
        self.msg = tk.Label(self.corpo, bg=BG, fg=FG2, anchor="w", font=(f, 9))
        self.etiquetas = []
        self._fonte = f
        self._modo = None

    def mensagem(self, texto, cor=FG2):
        if self._modo != "msg":
            for e in self.etiquetas:
                e.pack_forget()
            self._n = None
            self.msg.pack(side="left", fill="x", expand=True)
            self._modo = "msg"
        self.msg.configure(text=texto, fg=cor)

    def estado(self, itens):
        """itens: lista de (texto, cor do ponto ou None)."""
        if self._modo != "etiquetas":
            self.msg.pack_forget()
            self._modo = "etiquetas"
        while len(self.etiquetas) < len(itens):
            self.etiquetas.append(tk.Label(self.corpo, bg=BG2, fg=FG, font=(self._fonte, 8), padx=8, pady=2,
                                           highlightthickness=1, highlightbackground=BORDA))
        for e, (texto, cor) in zip(self.etiquetas, itens):
            e.configure(text=("● " + texto) if cor else texto, fg=cor or FG)
        # quantas cabem na largura (a versao fica a direita): as do fim saem inteiras, nunca cortadas
        livre = self.corpo.winfo_width() - (self.versao.winfo_reqwidth() + 12 if self.versao else 0)
        n, usado = 0, 0
        for e in self.etiquetas[:len(itens)]:
            usado += e.winfo_reqwidth() + 6
            if usado > livre and n > 0:
                break
            n += 1
        if getattr(self, "_n", None) != n:
            for e in self.etiquetas:
                e.pack_forget()
            for e in self.etiquetas[:n]:
                e.pack(side="left", padx=(0, 6))
            self._n = n


def estilo_ttk(raiz):
    """Estilo unico das pecas ttk (botoes, caixas, campos, tabelas, molduras, rolagem) no tema atual."""
    from tkinter import ttk
    e = ttk.Style(raiz)
    try:
        e.theme_use("clam")
    except tk.TclError:
        pass
    f = fontes(raiz)
    sel_fg = "#ffffff"
    e.configure(".", background=BG, foreground=FG, fieldbackground=BG2, bordercolor=BORDA, lightcolor=BG2,
                darkcolor=BG2, troughcolor=BG, focuscolor=ACENTO, selectbackground=ACENTO, selectforeground=sel_fg,
                insertcolor=FG, font=(f["texto"], 9))
    e.configure("TButton", background=BG2, foreground=FG, bordercolor=BORDA, lightcolor=BG2, darkcolor=BG2,
                padding=(10, 5), relief="flat", focusthickness=0)
    e.map("TButton", background=[("disabled", BG2), ("pressed", PRESSIONADO), ("active", HOVER)],
          foreground=[("disabled", DESATIVADO)], bordercolor=[("active", BORDA_HOVER)],
          lightcolor=[("active", HOVER)], darkcolor=[("active", HOVER)])
    for tipo in ("TCheckbutton", "TRadiobutton"):
        e.configure(tipo, background=BG, foreground=FG, indicatorbackground=BG2, indicatorforeground=FG,
                    indicatorrelief="flat", focusthickness=0)
        e.map(tipo, background=[("active", BG)], foreground=[("disabled", DESATIVADO)],
              indicatorbackground=[("selected", ACENTO), ("active", HOVER)], indicatorforeground=[("selected", sel_fg)])
    e.configure("TEntry", fieldbackground=BG2, foreground=FG, bordercolor=BORDA, lightcolor=BG2, darkcolor=BG2,
                insertcolor=FG, padding=4)
    e.map("TEntry", bordercolor=[("focus", ACENTO)])
    e.configure("TCombobox", fieldbackground=BG2, background=BG2, foreground=FG, arrowcolor=FG, bordercolor=BORDA,
                lightcolor=BG2, darkcolor=BG2, padding=(6, 4), arrowsize=13)
    e.map("TCombobox", fieldbackground=[("readonly", BG2)], foreground=[("readonly", FG)],
          selectbackground=[("readonly", BG2)], selectforeground=[("readonly", FG)], background=[("readonly", BG2)],
          bordercolor=[("focus", ACENTO)])
    e.configure("Treeview", background=BG2, fieldbackground=BG2, foreground=FG, rowheight=22, borderwidth=0,
                bordercolor=BORDA, lightcolor=BG2, darkcolor=BG2)
    e.map("Treeview", background=[("selected", ACENTO)], foreground=[("selected", sel_fg)])
    e.configure("Treeview.Heading", background=BG, foreground=FG2, relief="flat", bordercolor=BORDA, lightcolor=BG,
                darkcolor=BG, padding=(6, 4), font=(f["forte"], 9))
    e.map("Treeview.Heading", background=[("active", HOVER)], foreground=[("active", FG)])
    e.configure("TLabelframe", background=BG, bordercolor=BORDA, lightcolor=BG, darkcolor=BG)
    e.configure("TLabelframe.Label", background=BG, foreground=FG2)
    e.configure("TLabel", background=BG, foreground=FG)
    e.configure("TFrame", background=BG)
    for orient in ("Vertical", "Horizontal"):
        e.configure("%s.TScrollbar" % orient, background=BG2, troughcolor=BG, bordercolor=BG, arrowcolor=FG2,
                    lightcolor=BG2, darkcolor=BG2, gripcount=0)
        e.map("%s.TScrollbar" % orient, background=[("active", HOVER)])
    raiz.option_add("*TCombobox*Listbox.background", BG2)
    raiz.option_add("*TCombobox*Listbox.foreground", FG)
    raiz.option_add("*TCombobox*Listbox.selectBackground", ACENTO)
    raiz.option_add("*TCombobox*Listbox.selectForeground", sel_fg)
    return e

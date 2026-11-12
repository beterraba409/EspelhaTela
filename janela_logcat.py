# -*- coding: utf-8 -*-
"""Janela "Logcat ao vivo": o log do aparelho em tempo real, com filtro por app, nivel e texto.

O adb manda tudo (`logcat -v threadtime`); os filtros sao aplicados aqui, entao trocar de filtro nao
reinicia o log. O app e filtrado pelos PIDs do pacote, relidos a cada 3 s (o app pode reiniciar).
"""

import collections
import datetime
import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font  # noqa: F401  (tk.font.families)
from tkinter import filedialog, ttk

import visual

MAX_LINHAS = 20000  # guardadas (as mais antigas saem)
MAX_TELA = 6000  # mostradas de uma vez ao refazer a lista
NIVEIS = ["V", "D", "I", "W", "E", "F"]
NOMES_NIVEL = [("Verbose", "V"), ("Debug", "D"), ("Info", "I"), ("Aviso", "W"), ("Erro", "E")]
RX = re.compile(r"^(\d\d-\d\d\s+\d\d:\d\d:\d\d\.\d+)\s+(\d+)\s+(\d+)\s+([VDIWEFA])\s+(.*?)\s*:\s?(.*)$")
TODOS = "Todos os apps"


def parse_linha(linha):
    """'11-11 16:01:02.345  1234  1250 E Tag: msg' -> dict, ou None (cabecalhos do logcat, linhas soltas)."""
    m = RX.match(linha.rstrip("\r\n"))
    if not m:
        return None
    hora, pid, tid, nivel, tag, msg = m.groups()
    return {"hora": hora, "pid": int(pid), "tid": int(tid), "nivel": "F" if nivel == "A" else nivel,
            "tag": tag, "msg": msg, "texto": linha.rstrip("\r\n")}


def passa(item, nivel_min="V", pids=None, busca=""):
    """O item entra na lista com esses filtros? pids=None: todos os apps."""
    if NIVEIS.index(item["nivel"]) < NIVEIS.index(nivel_min):
        return False
    if pids is not None and item["pid"] not in pids:
        return False
    return not busca or busca.lower() in item["texto"].lower()


class JanelaLogcat:
    def __init__(self, raiz, adb, serial, rodar, sem_janela=0, pacote_em_foco=None, icone=None, ao_fechar=None):
        self.adb, self.serial, self.rodar, self.sem_janela = adb, serial, rodar, sem_janela
        self.ao_fechar = ao_fechar
        self.linhas = collections.deque(maxlen=MAX_LINHAS)
        self.q = queue.Queue()
        self.pausado = False
        self.pids = None
        self.proc = None
        self.parar = False
        self.acabou = False  # o logcat terminou (aparelho desconectou): fica avisado no rodape
        self.app_atual = pacote_em_foco or TODOS
        w = self.win = tk.Toplevel(raiz)
        w.title("Logcat ao vivo - %s" % serial)
        if icone:
            icone(w)
        w.configure(bg=visual.BG)
        w.geometry("1100x640")
        w.minsize(640, 360)
        w.protocol("WM_DELETE_WINDOW", self.fechar)
        f = self.f = visual.fontes(w)

        barra = tk.Frame(w, bg=visual.BG)
        barra.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(barra, text="App", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9)).pack(side="left")
        self.var_app = tk.StringVar(value=pacote_em_foco or TODOS)
        self.cb_app = ttk.Combobox(barra, textvariable=self.var_app, width=30, values=[TODOS] + ([pacote_em_foco] if pacote_em_foco else []))
        self.cb_app.pack(side="left", padx=(6, 12))
        self.cb_app.bind("<<ComboboxSelected>>", lambda e: self._muda_app())
        self.cb_app.bind("<Return>", lambda e: self._muda_app())
        tk.Label(barra, text="N\u00edvel", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9)).pack(side="left")
        self.var_nivel = tk.StringVar(value="Debug")
        cb = ttk.Combobox(barra, textvariable=self.var_nivel, state="readonly", width=9, values=[n for n, _ in NOMES_NIVEL])
        cb.pack(side="left", padx=(6, 12))
        cb.bind("<<ComboboxSelected>>", lambda e: self.refaz())
        tk.Label(barra, text="Buscar", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9)).pack(side="left")
        self.var_busca = tk.StringVar()
        ent = ttk.Entry(barra, textvariable=self.var_busca, width=24)
        ent.pack(side="left", padx=(6, 12))
        self.var_busca.trace_add("write", lambda *a: self._agenda_refaz())
        self.bt_pausa = ttk.Button(barra, text="\u23F8  Pausar", command=self.alterna_pausa)
        self.bt_pausa.pack(side="left", padx=(0, 6))
        ttk.Button(barra, text="Limpar", command=self.limpar).pack(side="left", padx=(0, 6))
        ttk.Button(barra, text="Salvar\u2026", command=self.salvar).pack(side="left")
        self.var_fim = tk.BooleanVar(value=True)
        ttk.Checkbutton(barra, text="Acompanhar o fim", variable=self.var_fim).pack(side="right")

        corpo = tk.Frame(w, bg=visual.BG)
        corpo.pack(fill="both", expand=True, padx=10)
        fonte = ("Cascadia Mono", 9) if "Cascadia Mono" in tk.font.families(w) else ("Consolas", 9)
        self.txt = tk.Text(corpo, bg=visual.BG2, fg=visual.FG, insertbackground=visual.FG, font=fonte, wrap="none",
                           relief="flat", borderwidth=0, padx=8, pady=6, undo=False)
        sy = ttk.Scrollbar(corpo, orient="vertical", command=self.txt.yview)
        sx = ttk.Scrollbar(w, orient="horizontal", command=self.txt.xview)
        self.txt.configure(yscrollcommand=self._rolou, xscrollcommand=sx.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        sx.pack(fill="x", padx=10)
        self.sy = sy
        cores = {"V": visual.FG2, "D": visual.FG2, "I": visual.FG, "W": visual.AMBAR, "E": visual.PERIGO, "F": visual.PERIGO}
        for n, cor in cores.items():
            self.txt.tag_configure(n, foreground=cor)
        self.txt.tag_configure("busca", background=visual.ACENTO, foreground="#ffffff")
        self.txt.bind("<Key>", lambda e: None if (e.state & 0x4 and e.keysym.lower() in ("c", "a")) else "break")  # so leitura

        self.rodape = tk.Label(w, text="", bg=visual.BG, fg=visual.FG2, anchor="w", font=(f["texto"], 9), padx=10)
        self.rodape.pack(fill="x", pady=(4, 8))
        self.mostradas = 0
        self._refaz_id = None
        self._muda_app(inicio=True)
        self._inicia()
        threading.Thread(target=self._pids_loop, daemon=True).start()
        w.after(150, self._consome)

    # ---- adb
    def _inicia(self):
        cmd = [self.adb, "-s", self.serial, "logcat", "-v", "threadtime", "-T", "2000"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=self.sem_janela)

        def leitor(p=self.proc):
            for bruto in p.stdout:
                if self.parar:
                    break
                item = parse_linha(bruto.decode("utf-8", "replace"))
                if item:
                    self.q.put(item)
            self.q.put(None)  # o logcat terminou (aparelho desconectou?)

        threading.Thread(target=leitor, daemon=True).start()

    def _pids_loop(self):
        while not self.parar:
            app = self.app_atual  # copia feita na thread do Tk (_muda_app): daqui nao se le widget
            if app and app != TODOS:
                try:
                    _, out, _ = self.rodar([self.adb, "-s", self.serial, "shell", "pidof %s" % app], timeout=10)
                    novos = {int(x) for x in out.split() if x.isdigit()}
                    if novos != (self.pids or set()):
                        self.pids = novos
                        self.q.put("refaz")
                except Exception:  # noqa: BLE001
                    pass
            for _ in range(30):
                if self.parar:
                    return
                time.sleep(0.1)

    # ---- filtros
    def _nivel(self):
        return dict(NOMES_NIVEL).get(self.var_nivel.get(), "V")

    def _filtro_pids(self):
        app = self.var_app.get().strip()
        return None if not app or app == TODOS else (self.pids or set())

    def _muda_app(self, inicio=False):
        app = self.app_atual = self.var_app.get().strip()
        self.pids = None if (not app or app == TODOS) else set()
        if not inicio:
            self.rodape.configure(text="buscando o processo de %s\u2026" % app if self.pids is not None else "")
            self.refaz()

    def _agenda_refaz(self):
        if self._refaz_id:
            self.win.after_cancel(self._refaz_id)
        self._refaz_id = self.win.after(250, self.refaz)

    def refaz(self):
        """Mostra de novo, com os filtros atuais, o que ja chegou (ate MAX_TELA linhas)."""
        self._refaz_id = None
        nivel, pids, busca = self._nivel(), self._filtro_pids(), self.var_busca.get().strip()
        itens = [i for i in self.linhas if passa(i, nivel, pids, busca)][-MAX_TELA:]
        self.txt.delete("1.0", "end")
        self.mostradas = 0
        self._insere(itens, busca)
        self.txt.see("end")

    def _insere(self, itens, busca):
        for i in itens:
            ini = self.txt.index("end-1c")
            self.txt.insert("end", i["texto"] + "\n", i["nivel"])
            if busca:
                linha = i["texto"].lower()
                pos = linha.find(busca.lower())
                while pos >= 0:
                    self.txt.tag_add("busca", "%s+%dc" % (ini, pos), "%s+%dc" % (ini, pos + len(busca)))
                    pos = linha.find(busca.lower(), pos + len(busca))
        self.mostradas += len(itens)
        if self.mostradas > MAX_TELA * 1.5:  # nao deixa o texto crescer sem fim
            corte = self.mostradas - MAX_TELA
            self.txt.delete("1.0", "%d.0" % (corte + 1))
            self.mostradas = MAX_TELA

    # ---- fila -> tela
    def _consome(self):
        if self.parar:
            return
        novos, refazer = [], False
        try:
            for _ in range(5000):
                item = self.q.get_nowait()
                if item is None:
                    self.acabou = True
                elif item == "refaz":
                    refazer = True
                else:
                    self.linhas.append(item)
                    novos.append(item)
        except queue.Empty:
            pass
        if refazer and not self.pausado:
            self.refaz()
        elif novos and not self.pausado:
            nivel, pids, busca = self._nivel(), self._filtro_pids(), self.var_busca.get().strip()
            vis = [i for i in novos if passa(i, nivel, pids, busca)]
            if vis:
                self._insere(vis, busca)
                if self.var_fim.get():
                    self.txt.see("end")
        estado = "pausado (as linhas continuam chegando e aparecem ao retomar)" if self.pausado else "ao vivo"
        if self.acabou:
            estado = "o logcat parou (o aparelho desconectou?)"
        app = self.var_app.get().strip()
        filtro = ("%s (%s)" % (app, ", ".join(str(p) for p in sorted(self.pids)) if self.pids else "%s (n\u00e3o est\u00e1 rodando)" % app)) if self._filtro_pids() is not None else TODOS.lower()
        self.rodape.configure(text="%s  \u00b7  %d linhas guardadas  \u00b7  %s" % (estado, len(self.linhas), filtro),
                              fg=visual.PERIGO if self.acabou else visual.FG2)
        self.win.after(150, self._consome)

    def _rolou(self, primeiro, ultimo):
        self.sy.set(primeiro, ultimo)
        # subiu a rolagem: para de acompanhar o fim; voltou ao fim: acompanha de novo
        self.var_fim.set(float(ultimo) >= 0.999)

    # ---- botoes
    def alterna_pausa(self):
        self.pausado = not self.pausado
        self.bt_pausa.configure(text="\u25B6  Retomar" if self.pausado else "\u23F8  Pausar")
        if not self.pausado:
            self.refaz()

    def limpar(self):
        self.linhas.clear()
        self.txt.delete("1.0", "end")
        self.mostradas = 0

    def salvar(self):
        nome = "logcat-%s-%s.txt" % (re.sub(r"[^A-Za-z0-9._-]", "_", self.serial), datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        caminho = filedialog.asksaveasfilename(title="Salvar o logcat (com os filtros atuais)", initialfile=nome, defaultextension=".txt",
                                               filetypes=[("Texto", "*.txt")], parent=self.win)
        if not caminho:
            return
        nivel, pids, busca = self._nivel(), self._filtro_pids(), self.var_busca.get().strip()
        with open(caminho, "w", encoding="utf-8") as f:
            for i in self.linhas:
                if passa(i, nivel, pids, busca):
                    f.write(i["texto"] + "\n")
        self.rodape.configure(text="salvo em %s" % caminho)
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(caminho)])

    def fechar(self):
        self.parar = True
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
        except Exception:  # noqa: BLE001
            pass
        if self.ao_fechar:
            self.ao_fechar()
        self.win.destroy()

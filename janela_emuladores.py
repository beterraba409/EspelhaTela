# -*- coding: utf-8 -*-
"""Janela "Emuladores" e o assistente "Criar emulador".

`Gerente` guarda o que o Vision ligou (sobrevive a janela fechada) e acompanha o boot numa thread;
as janelas so mostram e mandam. O emulador aparece no espelho do Vision quando termina de ligar.
"""

import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import emulador_avd as A
import emulador_proc as P
import emulador_sdk as S
import visual

LIMITE_BOOT = 420  # s ate desistir de um boot (o primeiro de uma imagem nova e o mais lento)


def tamanho(n):
    return "%.1f GB" % (n / (1 << 30)) if n >= (1 << 30) else "%d MB" % (n >> 20)


class Gerente:
    """Emuladores ligados pelo Vision: {nome: {serial, proc, t0, log, estado, erro}}; `ao_pronto(serial)`."""

    def __init__(self, adb, rodar, ao_pronto):
        self.adb, self.rodar, self.ao_pronto = adb, rodar, ao_pronto
        self.raiz = S.raiz_sdk()
        self.meus = {}
        self.ligados = {}  # serial -> nome (tambem os que o Vision nao ligou)
        self.lock = threading.Lock()
        self.parar = False
        threading.Thread(target=self._vigia, daemon=True).start()

    def estado(self, nome):
        """(estado, detalhe): desligado | iniciando | pronto | erro."""
        with self.lock:
            m = self.meus.get(nome)
            serial = next((s for s, n in self.ligados.items() if n == nome), None)
        if m and m["estado"] in ("iniciando", "erro"):
            return m["estado"], (m["erro"] if m["estado"] == "erro" else "%d s" % (time.time() - m["t0"]))
        if serial:
            return "pronto", serial
        return "desligado", ""

    def serial_de(self, nome):
        with self.lock:
            return next((s for s, n in self.ligados.items() if n == nome), None)

    def inicia(self, nome, modo="normal", instantaneo=None):
        """Liga; com `instantaneo`, carrega aquele estado salvo assim que o Android terminar de ligar."""
        with self.lock:  # as do adb e as dos que o Vision acabou de ligar (ainda nao aparecem no adb)
            usadas = [int(s.split("-")[1]) for s in self.ligados]
            usadas += [int(m["serial"].split("-")[1]) for m in self.meus.values() if m["proc"].poll() is None]
        porta = P.porta_livre(usadas)
        proc, serial, log = P.inicia(self.raiz, nome, porta, modo)
        with self.lock:
            self.meus[nome] = {"serial": serial, "proc": proc, "t0": time.time(), "log": log, "estado": "iniciando", "erro": "",
                               "carregar": instantaneo}
        return serial

    def desliga(self, nome):
        serial = self.serial_de(nome) or (self.meus.get(nome) or {}).get("serial")
        if serial:
            P.desliga(self.rodar, self.adb, serial)
        m = self.meus.get(nome)
        if m and m["proc"].poll() is None:
            try:
                m["proc"].wait(15)
            except Exception:  # noqa: BLE001
                m["proc"].kill()
        with self.lock:
            self.meus.pop(nome, None)
            self.ligados = {s: n for s, n in self.ligados.items() if n != nome and s != serial}  # sem esperar a proxima volta

    def ligados_pelo_vision(self):
        return [n for n, m in self.meus.items() if m["proc"].poll() is None]

    def _vigia(self):
        while not self.parar:
            ligados = P.emuladores_ligados(self.rodar, self.adb)
            with self.lock:
                self.ligados = ligados
                meus = list(self.meus.items())
            for nome, m in meus:
                if m["estado"] != "iniciando":
                    continue
                if m["proc"].poll() is not None:
                    m["estado"], m["erro"] = "erro", P.ultimas_linhas(m["log"]) or "o emulador fechou ao ligar"
                elif m["serial"] in ligados and P.ligou(self.rodar, self.adb, m["serial"]):
                    if m.get("carregar"):
                        try:
                            P.carrega_estado(self.rodar, self.adb, m["serial"], m["carregar"])
                        except Exception as e:  # noqa: BLE001
                            m["aviso"] = "ligou, mas não voltou ao estado %s: %s" % (m["carregar"], e)
                        m["carregar"] = None
                    m["estado"] = "pronto"
                    self.ao_pronto(m["serial"])
                elif time.time() - m["t0"] > LIMITE_BOOT:
                    P.desliga(self.rodar, self.adb, m["serial"])  # nao deixa um emulador fantasma prendendo o AVD
                    try:
                        m["proc"].wait(15)
                    except Exception:  # noqa: BLE001
                        m["proc"].kill()
                    m["estado"], m["erro"] = "erro", "não terminou de ligar em %d s (desliguei; tente “Apagar os dados e ligar”)" % LIMITE_BOOT
            for _ in range(20):
                if self.parar:
                    return
                time.sleep(0.1)


class JanelaEmuladores:
    def __init__(self, raiz, gerente, icone=None, espelhar=None):
        self.g, self.icone, self.espelhar = gerente, icone, espelhar
        w = self.win = tk.Toplevel(raiz)
        w.title("Emuladores")
        if icone:
            icone(w)
        w.configure(bg=visual.BG)
        raiz.update_idletasks()  # ao lado da janela principal quando couber, para nao cobrir o espelho
        x = raiz.winfo_rootx() + raiz.winfo_width() + 8
        if x + 720 > raiz.winfo_screenwidth():
            x = max(0, raiz.winfo_screenwidth() - 740)
        w.geometry("720x560+%d+%d" % (x, max(0, raiz.winfo_rooty() - 30)))
        w.minsize(600, 420)
        f = self.f = visual.fontes(w)
        topo = tk.Frame(w, bg=visual.BG)
        topo.pack(fill="x", padx=20, pady=(18, 4))
        tk.Label(topo, text="Emuladores", bg=visual.BG, fg=visual.FG, font=(f["forte"], 14)).pack(side="left")
        b = visual.Botao(topo, "aplicar", "Criar emulador", comando=self.criar, largura=170, altura=36)
        b.define(ativo=True)
        b.pack(side="right")
        tk.Label(w, text="Android virtual dentro do Vision: liga sem janela própria e aparece no espelho como um aparelho.",
                 bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9), anchor="w").pack(fill="x", padx=20, pady=(0, 10))
        corpo = visual.Rolavel(w, 720)
        corpo.pack(fill="both", expand=True, padx=20)
        self.lista = corpo.dentro
        self.rodape = tk.Label(w, text="SDK: %s" % gerente.raiz, bg=visual.BG, fg=visual.FG2, font=(f["texto"], 8), anchor="w")
        self.rodape.pack(fill="x", padx=20, pady=(6, 10))
        self.cartoes = {}
        self._medido = {}
        self.monta()
        w.after(1000, self._atualiza)

    # ---- lista
    def monta(self):
        for c in self.lista.winfo_children():
            c.destroy()
        self.cartoes = {}
        avds = A.lista()
        if not avds:
            tk.Label(self.lista, text="Nenhum emulador ainda. Clique em “Criar emulador”: o perfil SmartPOS tem a tela\n"
                                      "de um POS e o Android 11 do GPOS e do L400.", bg=visual.BG, fg=visual.FG2,
                     font=(self.f["texto"], 10), justify="left").pack(anchor="w", pady=20)
        for a in avds:
            self._cartao(a)

    def _cartao(self, a):
        f = self.f
        c = tk.Frame(self.lista, bg=visual.BG2, highlightthickness=1, highlightbackground=visual.BORDA, padx=16, pady=12)
        c.pack(fill="x", pady=(0, 10))
        esq = tk.Frame(c, bg=visual.BG2)
        esq.pack(side="left", fill="x", expand=True)
        tk.Label(esq, text=a["rotulo"], bg=visual.BG2, fg=visual.FG, font=(f["forte"], 11), anchor="w").pack(anchor="w")
        info = "%s  ·  %s  ·  %s" % (A.ANDROIDS.get(a["api"], "API %s" % a["api"]), a["nome"], tamanho(a["tamanho"]))
        lb_info = tk.Label(esq, text=info, bg=visual.BG2, fg=visual.FG2, font=(f["texto"], 9), anchor="w")
        lb_info.pack(anchor="w")
        est = tk.Label(esq, text="", bg=visual.BG2, fg=visual.FG2, font=(f["texto"], 9), anchor="w", justify="left", wraplength=420)
        est.pack(anchor="w", pady=(4, 0))
        dir_ = tk.Frame(c, bg=visual.BG2)
        dir_.pack(side="right")
        mais = visual.Botao(dir_, "menu", comando=lambda: self._menu(a, mais), largura=40, altura=34)
        mais.pack(side="right")
        bt2 = visual.Botao(dir_, "energia", "", largura=118, altura=34)
        bt2.pack(side="right", padx=(0, 6))
        bt1 = visual.Botao(dir_, "retomar", "", largura=118, altura=34)
        bt1.pack(side="right", padx=(0, 6))
        self.cartoes[a["nome"]] = (a, est, bt1, bt2, lb_info)
        self._pinta(a["nome"])

    def _botao(self, b, icone, texto, comando, ativo=False, desativado=False):
        b.comando = comando
        b.define(icone=icone, texto=texto, ativo=ativo, desativado=desativado)

    def _pinta(self, nome):
        a, est, bt1, bt2, lb_info = self.cartoes[nome]
        estado, det = self.g.estado(nome)
        agora = time.time()
        if agora - self._medido.get(nome, 0) > 8:  # o tamanho muda enquanto o emulador roda
            self._medido[nome] = agora
            lb_info.configure(text="%s  \u00b7  %s  \u00b7  %s" % (A.ANDROIDS.get(a["api"], "API %s" % a["api"]), a["nome"],
                                                                    tamanho(A.tamanho_pasta(a["pasta"]))))
        if estado == "pronto":
            est.configure(text="●  Ligado (%s)" % det, fg=visual.VERDE)
            self._botao(bt1, "janela", "Espelhar", lambda: self.espelhar and self.espelhar(det), ativo=True)
            self._botao(bt2, "energia", "Desligar", lambda: self._desliga(nome))
        elif estado == "iniciando":
            est.configure(text="●  Ligando… %s (o primeiro boot demora mais)" % det, fg=visual.AMBAR)
            self._botao(bt1, "janela", "Espelhar", None, desativado=True)
            self._botao(bt2, "energia", "Desligar", lambda: self._desliga(nome))
        else:
            erro = det if estado == "erro" else ""
            est.configure(text=("✕  Não ligou: %s" % erro) if erro else "○  Desligado", fg=visual.PERIGO if erro else visual.FG2)
            self._botao(bt1, "retomar", "Ligar", lambda: self._liga(nome), ativo=True)
            estados = A.instantaneos(a["pasta"])
            self._botao(bt2, "atualizar", "Estado salvo", lambda: self._menu_estados(nome, estados, bt2), desativado=not estados)

    def _atualiza(self):
        try:
            nomes = {a["nome"] for a in A.lista(com_tamanho=False)}
            if nomes != set(self.cartoes):
                self.monta()
            for nome in self.cartoes:
                self._pinta(nome)
        except tk.TclError:
            return  # janela fechada
        except Exception as e:  # noqa: BLE001  (pasta de AVD apagada no meio, por exemplo): avisa e segue
            try:
                self.rodape.configure(text="erro ao atualizar: %s" % str(e)[:120], fg=visual.PERIGO)
            except tk.TclError:
                return
        try:
            self.win.after(1500, self._atualiza)
        except tk.TclError:
            pass

    # ---- acoes
    def _menu_estados(self, nome, estados, bt):
        """Ligar e ja voltar a um estado salvo (ex.: SmartPOS ativado e logado)."""
        m = visual.menu(self.win)
        for e in estados:
            m.add_command(label="Ligar em “%s”" % e, command=lambda e=e: self._liga(nome, instantaneo=e))
        m.tk_popup(bt.winfo_rootx(), bt.winfo_rooty() + bt.winfo_height())

    def _liga(self, nome, modo="normal", instantaneo=None):
        a = self.cartoes[nome][0]
        if self.g.estado(nome)[0] in ("iniciando", "pronto"):
            return
        api, tag = a["api"], a["config"].get("tag.id", "google_apis")
        if api and not S.imagem_completa(self.g.raiz, api, tag):
            return messagebox.showerror("Emuladores", "A imagem do %s deste emulador não está completa no PC.\n\n"
                                        "Crie o emulador de novo pelo Vision: ele baixa a imagem." % A.ANDROIDS.get(api, api), parent=self.win)
        try:
            self.g.inicia(nome, modo, instantaneo)
        except Exception as e:  # noqa: BLE001
            return messagebox.showerror("Emuladores", "Não consegui ligar: %s" % e, parent=self.win)
        self._pinta(nome)

    def _desliga(self, nome):
        threading.Thread(target=self.g.desliga, args=(nome,), daemon=True).start()

    def _menu(self, a, bt):
        nome = a["nome"]
        estado, serial = self.g.estado(nome)
        m = visual.menu(self.win)
        estados = A.instantaneos(a["pasta"])
        if estado == "pronto":
            m.add_command(label="Salvar estado agora…", command=lambda: self._salva(serial))
            if estados:
                sub = visual.menu(m)
                for e in estados:
                    sub.add_command(label=e, command=lambda e=e: self._console(P.carrega_estado, serial, e, "restaurado: %s" % e))
                m.add_cascade(label="Voltar a um estado salvo", menu=sub)
        elif estado in ("desligado", "erro"):
            if estados:
                sub = visual.menu(m)
                for e in estados:
                    sub.add_command(label=e, command=lambda e=e: self._liga(nome, instantaneo=e))
                m.add_cascade(label="Ligar num estado salvo", menu=sub)
            else:
                visual.item_info(m, "Nenhum estado salvo ainda: ligue e use “Salvar estado agora”")
            m.add_command(label="Apagar os dados e ligar (de fábrica)", command=lambda: self._apaga_e_liga(nome))
        if estados:
            sub2 = visual.menu(m)
            for e in estados:
                sub2.add_command(label=e, command=lambda e=e: self._apaga_estado(a, e))
            m.add_cascade(label="Excluir um estado salvo", menu=sub2)
        m.add_separator()
        m.add_command(label="Abrir a pasta do emulador", command=lambda: os.startfile(a["pasta"]) if os.name == "nt" else None)
        if estado in ("desligado", "erro"):
            m.add_command(label="Excluir emulador…", command=lambda: self._exclui(a))
        else:
            visual.item_info(m, "Para excluir, desligue o emulador")
        m.tk_popup(bt.winfo_rootx(), bt.winfo_rooty() + bt.winfo_height())

    def _salva(self, serial):
        nome = simpledialog.askstring("Salvar estado", "Nome do estado (ex.: smartpos-ativado):", parent=self.win)
        if not nome:
            return
        if not P.nome_de_estado_valido(nome):
            return messagebox.showerror("Salvar estado", "Use letras, números, ponto, hífen ou sublinhado.", parent=self.win)
        self._console(P.salva_estado, serial, nome, "estado salvo: %s" % nome)

    def _console(self, funcao, serial, nome, ok_texto):
        self.rodape.configure(text="aguarde…", fg=visual.ACENTO)

        def trabalho():
            try:
                funcao(self.g.rodar, self.g.adb, serial, nome)
                msg, cor = ok_texto, visual.VERDE
            except Exception as e:  # noqa: BLE001
                msg, cor = "falhou: %s" % e, visual.PERIGO
            try:
                self.win.after(0, lambda: self.rodape.configure(text=msg, fg=cor))
            except tk.TclError:
                pass

        threading.Thread(target=trabalho, daemon=True).start()

    def _apaga_estado(self, a, estado):
        if not messagebox.askyesno("Excluir estado", "Excluir o estado “%s” de %s?" % (estado, a["rotulo"]), parent=self.win):
            return
        serial = self.g.serial_de(a["nome"])
        if serial:
            return self._console(P.apaga_estado, serial, estado, "estado excluído: %s" % estado)
        import shutil
        shutil.rmtree(os.path.join(a["pasta"], "snapshots", estado), ignore_errors=True)
        self.rodape.configure(text="estado excluído: %s" % estado, fg=visual.VERDE)

    def _apaga_e_liga(self, nome):
        if messagebox.askyesno("Apagar os dados", "Apagar todos os dados de %s (apps, login, arquivos) e ligar como novo?" % nome,
                               icon="warning", parent=self.win):
            self._liga(nome, "apagar")

    def _exclui(self, a):
        if not messagebox.askyesno("Excluir emulador", "Excluir %s e os dados dele (%s)?\n\nA imagem do Android baixada continua no PC "
                                   "para os próximos emuladores." % (a["rotulo"], tamanho(a["tamanho"])), icon="warning", parent=self.win):
            return
        A.exclui(a["nome"])
        self.monta()

    def criar(self):
        JanelaCriar(self.win, self.g, icone=self.icone, ao_criar=lambda nome, ligar: (self.monta(), ligar and self._liga(nome)))


class JanelaCriar:
    """Assistente: perfil, versao do Android, nome e ajustes; baixa o que faltar e cria."""

    def __init__(self, raiz, gerente, icone=None, ao_criar=None):
        self.g, self.ao_criar = gerente, ao_criar
        self.q = queue.Queue()
        self.cancelar = False
        self.catalogo = None
        w = self.win = tk.Toplevel(raiz)
        w.title("Criar emulador")
        if icone:
            icone(w)
        w.configure(bg=visual.BG)
        w.resizable(False, False)
        w.transient(raiz)
        f = self.f = visual.fontes(w)
        tk.Label(w, text="Criar emulador", bg=visual.BG, fg=visual.FG, font=(f["forte"], 14)).pack(anchor="w", padx=20, pady=(18, 10))
        tk.Label(w, text="Perfil", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).pack(anchor="w", padx=20, pady=(0, 6))
        linha = tk.Frame(w, bg=visual.BG)
        linha.pack(fill="x", padx=20)
        self.perfil = "smartpos"
        self.cartoes = {}
        for chave, p in A.PERFIS.items():
            c = tk.Frame(linha, bg=visual.BG2, highlightthickness=2, highlightbackground=visual.BORDA, padx=12, pady=10, width=200)
            c.pack(side="left", fill="both", expand=True, padx=(0, 8))
            t = tk.Label(c, text=p["nome"], bg=visual.BG2, fg=visual.FG, font=(f["forte"], 11), anchor="w")
            t.pack(anchor="w")
            s = tk.Label(c, text="%d×%d" % (p["largura"], p["altura"]), bg=visual.BG2, fg=visual.FG2, font=(f["texto"], 9), anchor="w")
            s.pack(anchor="w")
            for wd in (c, t, s):
                wd.bind("<Button-1>", lambda e, k=chave: self._perfil(k))
            self.cartoes[chave] = c
        self.desc = tk.Label(w, text="", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9), justify="left", wraplength=560, anchor="w")
        self.desc.pack(fill="x", padx=20, pady=(8, 0))

        grade = tk.Frame(w, bg=visual.BG)
        grade.pack(fill="x", padx=20, pady=(12, 0))
        tk.Label(grade, text="Versão do Android", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).grid(row=0, column=0, sticky="w")
        self.var_api = tk.StringVar()
        self.cb_api = ttk.Combobox(grade, textvariable=self.var_api, state="readonly", width=40)
        self.cb_api.grid(row=1, column=0, sticky="w", pady=(4, 10))
        self.cb_api.bind("<<ComboboxSelected>>", lambda e: self._sugere_nome())
        tk.Label(grade, text="Nome", bg=visual.BG, fg=visual.FG, font=(f["forte"], 10)).grid(row=2, column=0, sticky="w")
        self.var_nome = tk.StringVar()
        ttk.Entry(grade, textvariable=self.var_nome, width=43).grid(row=3, column=0, sticky="w", pady=(4, 10))
        aj = tk.Frame(grade, bg=visual.BG)
        aj.grid(row=4, column=0, sticky="w")
        tk.Label(aj, text="Memória (GB)", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9)).pack(side="left")
        self.var_ram = tk.IntVar(value=3)
        ttk.Spinbox(aj, from_=2, to=8, textvariable=self.var_ram, width=4).pack(side="left", padx=(6, 18))
        tk.Label(aj, text="Armazenamento (GB)", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9)).pack(side="left")
        self.var_dados = tk.IntVar(value=6)
        ttk.Spinbox(aj, from_=4, to=64, textvariable=self.var_dados, width=4).pack(side="left", padx=(6, 0))

        self.req = tk.Frame(w, bg=visual.BG2, highlightthickness=1, highlightbackground=visual.BORDA, padx=12, pady=8)
        self.req.pack(fill="x", padx=20, pady=(14, 0))
        self.var_lic = tk.BooleanVar(value=False)
        self.lin_lic = tk.Frame(w, bg=visual.BG)
        self.ck_lic = ttk.Checkbutton(self.lin_lic, text="Li e aceito a licença do Android SDK", variable=self.var_lic)
        self.ck_lic.pack(side="left")
        ttk.Button(self.lin_lic, text="Ver licença", command=self._licenca).pack(side="left", padx=(8, 0))
        self.var_ligar = tk.BooleanVar(value=True)
        ttk.Checkbutton(w, text="Ligar e espelhar ao criar", variable=self.var_ligar).pack(anchor="w", padx=20, pady=(10, 0))
        self.prog = ttk.Progressbar(w, mode="determinate", maximum=100)
        self.status = tk.Label(w, text="consultando o repositório do Android…", bg=visual.BG, fg=visual.FG2,
                               font=(f["texto"], 9), anchor="w", justify="left", wraplength=560)
        self.status.pack(fill="x", padx=20, pady=(10, 0))
        tk.Frame(w, bg=visual.BORDA, height=1).pack(fill="x", pady=(12, 0))
        botoes = tk.Frame(w, bg=visual.BG)
        botoes.pack(fill="x", padx=20, pady=14)
        self.bt_ok = visual.Botao(botoes, "aplicar", "Criar", comando=self._criar, largura=150, altura=38)
        self.bt_ok.define(ativo=True)
        self.bt_ok.pack(side="right")
        self.bt_cancelar = visual.Botao(botoes, "fechar", "Cancelar", comando=self._fecha, largura=120, altura=38)
        self.bt_cancelar.pack(side="right", padx=(0, 8))
        w.protocol("WM_DELETE_WINDOW", self._fecha)
        w.bind("<Destroy>", lambda e: setattr(self, "cancelar", True) if e.widget is w else None)  # tambem quando o pai fecha
        self._perfil("smartpos")
        threading.Thread(target=self._carrega, daemon=True).start()
        w.after(150, self._consome)

    # ---- montagem
    def _perfil(self, chave):
        if getattr(self, "trabalhando", False):
            return  # baixando/criando: o perfil escolhido nao muda mais
        self.perfil = chave
        p = A.PERFIS[chave]
        for k, c in self.cartoes.items():
            c.configure(highlightbackground=visual.ACENTO if k == chave else visual.BORDA)
        self.desc.configure(text=p["descricao"])
        self.var_ram.set(p["ram"] // 1024)
        self.var_dados.set(p["dados"])
        self._lista_versoes(preferida=p["api"])

    def _versoes(self):
        """[(api, tag, rotulo, bytes a baixar)] na ordem do combo."""
        raiz = self.g.raiz
        imgs = self.catalogo[1] if self.catalogo else {}
        saida = []
        for api in sorted(A.ANDROIDS, reverse=True):
            if S.imagem_completa(raiz, api, "google_apis"):
                saida.append((api, "google_apis", "%s  ·  já baixado" % A.ANDROIDS[api], 0))
            elif S.imagem_completa(raiz, api, "google_apis_playstore"):
                saida.append((api, "google_apis_playstore", "%s (com Play Store)  ·  já baixado" % A.ANDROIDS[api], 0))
            elif api in imgs:
                saida.append((api, "google_apis", "%s  ·  baixar %s" % (A.ANDROIDS[api], tamanho(imgs[api]["size"])), imgs[api]["size"]))
        return saida

    def _lista_versoes(self, preferida=None):
        self.versoes = self._versoes()
        self.cb_api.configure(values=[v[2] for v in self.versoes])
        if self.versoes:
            idx = next((i for i, v in enumerate(self.versoes) if v[0] == preferida), 0)
            self.cb_api.current(idx)
        self._sugere_nome()

    def _escolhida(self):
        i = self.cb_api.current()
        return self.versoes[i] if 0 <= i < len(self.versoes) else None

    def _sugere_nome(self):
        v = self._escolhida()
        atual = self.var_nome.get().strip()
        if v and (not atual or atual == getattr(self, "_sugerido", None)):  # so troca o nome que o Vision sugeriu
            self._sugerido = A.sugere_nome(self.perfil, v[0], {a["nome"] for a in A.lista(com_tamanho=False)})
            self.var_nome.set(self._sugerido)
        self._mostra_requisitos()

    def _a_baixar(self):
        v = self._escolhida()
        emu = 0 if os.path.isfile(S.exe_emulador(self.g.raiz)) else (self.catalogo[0]["size"] if self.catalogo and self.catalogo[0] else 0)
        return emu, (v[3] if v else 0)

    @staticmethod
    def _precisa_gb(emu, img, dados):
        """Zip + descompactado durante a troca (~2,2x o download), mais o armazenamento do emulador."""
        return 2.2 * (emu + img) / (1 << 30) + dados + 1

    def _mostra_requisitos(self):
        for c in self.req.winfo_children():
            c.destroy()
        emu, img = self._a_baixar()
        itens = list(getattr(self, "reqs", None) or [(None, "Verificando", "aceleração e memória…")])
        try:
            dados = int(self.var_dados.get())
        except (ValueError, tk.TclError):
            dados = 6
        livre, precisa = S.disco_livre_gb(self.g.raiz), self._precisa_gb(emu, img, dados)
        itens = [x for x in itens if x[1] != "Disco"]
        if livre is not None:
            itens.append((livre >= precisa, "Disco", "%.0f GB livres (precisa de uns %.0f GB)" % (livre, precisa)))
        for ok, item, det in itens:
            cor = visual.VERDE if ok else (visual.FG2 if ok is None else visual.PERIGO)
            sinal = "✔" if ok else ("•" if ok is None else "✕")
            tk.Label(self.req, text="%s  %s: %s" % (sinal, item, det), bg=visual.BG2, fg=cor, font=(self.f["texto"], 9),
                     anchor="w", justify="left", wraplength=540).pack(anchor="w")
        baixar = emu + img
        tk.Label(self.req, text=("⬇  Vai baixar %s do repositório oficial do Google" % tamanho(baixar)) if baixar
                 else "✔  Nada a baixar: emulador e imagem já estão no PC",
                 bg=visual.BG2, fg=visual.FG, font=(self.f["texto"], 9), anchor="w").pack(anchor="w", pady=(4, 0))
        if baixar:
            self.lin_lic.pack(fill="x", padx=20, pady=(10, 0), before=self.status)
        else:
            self.lin_lic.pack_forget()

    def _licenca(self):
        texto = (self.catalogo[2].get("android-sdk-license") if self.catalogo else "") or "Licença indisponível sem internet."
        t = tk.Toplevel(self.win)
        t.title("Licença do Android SDK")
        t.configure(bg=visual.BG)
        box = tk.Text(t, wrap="word", bg=visual.BG2, fg=visual.FG, relief="flat", padx=10, pady=8, width=90, height=30)
        box.insert("1.0", texto)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True, padx=10, pady=10)

    # ---- trabalho em segundo plano
    def _carrega(self):
        try:
            cat = S.catalogo()
        except Exception as e:  # noqa: BLE001
            cat, erro = None, str(e)[:120]
        else:
            erro = ""
        self.q.put(("catalogo", cat, erro))
        self.q.put(("reqs", S.requisitos(self.g.raiz, 2.5)))

    def _consome(self):
        try:
            while not self.q.empty():
                m = self.q.get_nowait()
                if m[0] == "catalogo":
                    self.catalogo = m[1]
                    self.status.configure(text="" if m[1] else "Sem acesso ao repositório (%s): só as versões já baixadas." % m[2])
                    self._lista_versoes(preferida=(self._escolhida() or (A.PERFIS[self.perfil]["api"],))[0])
                elif m[0] == "reqs":
                    self.reqs = m[1]
                    self._mostra_requisitos()
                elif m[0] == "prog":
                    self.prog.configure(value=m[1])
                    self.status.configure(text=m[2], fg=visual.ACENTO)
                elif m[0] == "fim":
                    nome, erro = m[1], m[2]
                    if erro:
                        self.trabalhando = False
                        self.status.configure(text=erro, fg=visual.PERIGO)
                        self.bt_ok.define(desativado=False)
                        self.prog.pack_forget()
                    else:
                        ligar = self.var_ligar.get()
                        self.criado = True
                        self.win.destroy()
                        if self.ao_criar:
                            self.ao_criar(nome, ligar)
                        return
            self.win.after(150, self._consome)
        except tk.TclError:
            pass

    def _criar(self):
        v = self._escolhida()
        nome = self.var_nome.get().strip()
        if not v:
            return self.status.configure(text="Escolha a versão do Android.", fg=visual.PERIGO)
        if not A.nome_valido(nome):
            return self.status.configure(text="Nome: só letras, números, ponto, hífen ou sublinhado.", fg=visual.PERIGO)
        if nome in {a["nome"] for a in A.lista()}:
            return self.status.configure(text="Já existe um emulador com esse nome.", fg=visual.PERIGO)
        try:
            ram, dados = int(self.var_ram.get()) * 1024, int(self.var_dados.get())
            if not (2 <= ram // 1024 <= 16 and 2 <= dados <= 256):
                raise ValueError()
        except (ValueError, tk.TclError):
            return self.status.configure(text="Mem\u00f3ria (2 a 16 GB) e armazenamento (2 a 256 GB) precisam ser n\u00fameros.", fg=visual.PERIGO)
        emu, img = self._a_baixar()
        livre = S.disco_livre_gb(self.g.raiz)
        precisa = self._precisa_gb(emu, img, dados)
        if livre is not None and livre < precisa:
            return self.status.configure(text="Falta espa\u00e7o: precisa de uns %.0f GB e h\u00e1 %.0f GB livres." % (precisa, livre), fg=visual.PERIGO)
        if (emu or img) and not self.var_lic.get():
            return self.status.configure(text="Para baixar, aceite a licença do Android SDK.", fg=visual.PERIGO)
        if (emu or img) and not self.catalogo:
            return self.status.configure(text="Sem acesso ao repositório para baixar.", fg=visual.PERIGO)
        self.bt_ok.define(desativado=True)
        self.prog.pack(fill="x", padx=20, pady=(8, 0), before=self.status)
        api, tag = v[0], v[1]
        self.trabalhando = True
        threading.Thread(target=self._trabalho, args=(nome, self.perfil, api, tag, ram, dados, emu, img), daemon=True).start()

    def _trabalho(self, nome, perfil, api, tag, ram, dados, emu, img):
        raiz = self.g.raiz
        total = emu + img
        try:
            feito_antes = 0
            pacotes = []
            if emu:
                pacotes.append(("o emulador", self.catalogo[0], os.path.join(raiz, "emulator")))
            if img:
                pacotes.append(("o %s" % A.ANDROIDS[api], self.catalogo[1][api], S.pasta_imagem(raiz, api, tag)))
            for rotulo, pac, destino in pacotes:
                zipf = os.path.join(raiz, ".vision-downloads", os.path.basename(pac["url"]))

                def prog(feito, tot, rotulo=rotulo, base=feito_antes):
                    pct = 100 * (base + feito) / max(1, total)
                    self.q.put(("prog", pct * 0.9, "Baixando %s: %s de %s" % (rotulo, tamanho(feito), tamanho(tot))))

                S.baixa(pac["url_completa"], zipf, pac["sha1"], pac["size"], prog, lambda: self.cancelar)
                self.q.put(("prog", 100 * (feito_antes + pac["size"]) / max(1, total) * 0.9, "Instalando %s…" % rotulo))
                S.extrai(zipf, destino, lambda: self.cancelar)
                os.remove(zipf)
                feito_antes += pac["size"]
            if emu:
                self.g.raiz = raiz  # agora este SDK tem emulador
            self.q.put(("prog", 95, "Criando o emulador…"))
            A.cria(nome, perfil, api, ram=ram, dados=dados, tag=tag)
            self.q.put(("fim", nome, ""))
        except S.Cancelado:
            self.q.put(("fim", nome, "Cancelado. O que já foi baixado fica guardado e o próximo download continua dali."))
        except Exception as e:  # noqa: BLE001
            self.q.put(("fim", nome, "Não consegui criar: %s" % str(e)[:200]))

    def _fecha(self):
        self.cancelar = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass

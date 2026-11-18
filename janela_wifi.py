# -*- coding: utf-8 -*-
"""Janela "Conectar pelo Wi-Fi": pelo IP (adb connect, porta 5555) ou parear com codigo (Android 11+,
Depuracao por Wi-Fi: adb pair + descoberta da porta de conexao pelo mDNS)."""

import queue
import re
import threading
import time
import tkinter as tk
from tkinter import ttk

import visual

RX_ENDERECO = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(:\d{1,5})?$")
RX_CODIGO = re.compile(r"^\d{6}$")


def endereco_valido(txt, exige_porta=False):
    txt = (txt or "").strip()
    if not RX_ENDERECO.match(txt):
        return False
    if exige_porta and ":" not in txt:
        return False
    return all(0 <= int(p) <= 255 for p in txt.split(":")[0].split("."))


def pareou(saida):
    """`adb pair` deu certo? (ex.: 'Successfully paired to 192.168.1.6:37451 [guid=adb-...]')."""
    return "successfully paired" in (saida or "").lower()


def servicos_mdns(saida):
    """Linhas do `adb mdns services` -> [(nome, tipo, 'ip:porta')]."""
    itens = []
    for linha in (saida or "").splitlines():
        partes = linha.split()
        if len(partes) >= 3 and partes[1].startswith("_adb") and re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", partes[-1]):
            itens.append((partes[0], partes[1].rstrip("."), partes[-1]))
    return itens


def porta_de_conexao(saida_mdns, ip):
    """Endereco de conexao (servico _adb-tls-connect) anunciado pelo aparelho com esse IP."""
    for _, tipo, end in servicos_mdns(saida_mdns):
        if tipo.startswith("_adb-tls-connect") and end.split(":")[0] == ip:
            return end
    return None


def conectou(saida):
    baixo = (saida or "").lower()
    return "connected to" in baixo and "cannot" not in baixo and "failed" not in baixo


def parear_e_conectar(rodar, adb, end_pareamento, codigo, end_conexao="", avisa=lambda t: None, tentativas=6):
    """Pareia e conecta. Devolve (endereco_conectado | None, mensagem)."""
    avisa("pareando com %s…" % end_pareamento)
    _, out, err = rodar([adb, "pair", end_pareamento, codigo], timeout=30)
    saida = (out + "\n" + err).strip()
    if not pareou(saida):
        linha = [l for l in saida.splitlines() if l.strip()]
        return None, "o pareamento falhou: %s" % (linha[-1] if linha else "sem resposta")
    ip = end_pareamento.split(":")[0]
    alvo = end_conexao.strip()
    if not alvo:
        avisa("pareado. Procurando a porta de conexão na rede…")
        for _ in range(tentativas):
            _, out, _ = rodar([adb, "mdns", "services"], timeout=15)
            alvo = porta_de_conexao(out, ip)
            if alvo:
                break
            time.sleep(1.5)
    if not alvo:
        return None, ("pareado, mas não achei a porta de conexão. Preencha “IP e porta de conexão” com o que "
                      "aparece na tela Depuração por Wi-Fi do aparelho e clique de novo")
    avisa("conectando em %s…" % alvo)
    _, out, err = rodar([adb, "connect", alvo], timeout=20)
    saida = (out + "\n" + err).strip()
    if conectou(saida):
        return alvo, "conectado em %s" % alvo
    return None, "pareado, mas a conexão em %s falhou: %s" % (alvo, saida[-200:] or "sem resposta")


def sonda_porta(ip, porta, espera=4.0):
    """'aberta', 'recusada' (o aparelho respondeu, mas nada escuta na porta) ou 'sem_resposta' (fora da rede,
    IP errado ou roteador isolando os aparelhos). O Windows so diz "recusada" depois de ~2 s (ele repete a
    tentativa), por isso a espera passa disso."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(espera)
    try:
        codigo = s.connect_ex((ip, int(porta)))
    except OSError:
        return "sem_resposta"
    finally:
        s.close()
    if codigo == 0:
        return "aberta"
    return "recusada" if codigo in (10061, 111, 61) else "sem_resposta"  # ECONNREFUSED no Windows, Linux e macOS


def explica_falha(ip, porta, estado, saida=""):
    """Mensagem do que fazer quando o `adb connect` nao conectou."""
    if estado == "recusada":
        return ("O aparelho %s está na rede, mas não aceita conexão na porta %s: a depuração por rede está desligada nele. "
                "Ligue de um destes jeitos:\n"
                "•  Com o cabo USB ligado: use “Ligar o Wi-Fi pelo cabo” abaixo (qualquer Android).\n"
                "•  Android 11 ou mais novo: Opções do desenvolvedor › Depuração por Wi-Fi, e use a aba “Parear com código”."
                % (ip, porta))
    if estado == "sem_resposta":
        return ("O aparelho %s não respondeu. Confira o IP (Configurações › Wi-Fi › rede conectada) e se o PC e o "
                "aparelho estão na mesma rede: redes de visitante costumam isolar os aparelhos." % ip)
    linha = [l for l in (saida or "").splitlines() if l.strip()]
    return "Não consegui conectar em %s:%s: %s" % (ip, porta, linha[-1] if linha else "sem resposta")


def conectar_por_ip(rodar, adb, txt, sonda=sonda_porta, avisa=lambda t: None):
    """Conecta pelo IP. Sem porta, procura antes a da Depuracao por Wi-Fi (Android 11+) anunciada na rede e
    so depois tenta a 5555. Devolve (endereco | None, mensagem, pendente_de_autorizacao)."""
    ip, _, porta = txt.strip().partition(":")
    alvos = ["%s:%s" % (ip, porta)] if porta else []
    if not porta:
        avisa("procurando o aparelho %s na rede…" % ip)
        try:
            _, out, _ = rodar([adb, "mdns", "services"], timeout=15)
            achado = porta_de_conexao(out, ip)
            if achado:
                alvos.append(achado)
        except Exception:  # noqa: BLE001
            pass
        alvos.append(ip + ":5555")
    saida = ""
    for alvo in alvos:
        avisa("conectando em %s…" % alvo)
        _, out, err = rodar([adb, "connect", alvo], timeout=20)
        saida = (out + "\n" + err).strip()
        baixo = saida.lower()
        if "failed to authenticate" in baixo or "unauthorized" in baixo:
            return alvo, ("O aparelho %s pediu autorização: aceite “Permitir depuração” na tela dele (marque “Sempre "
                          "permitir”). Ele entra na lista assim que você aceitar." % alvo), True
        if conectou(saida):
            return alvo, "conectado em %s" % alvo, False
    alvo = alvos[-1]
    return None, explica_falha(ip, alvo.split(":")[1], sonda(ip, alvo.split(":")[1]), saida), False


def ip_do_wifi(saida):
    """IPv4 do wlan0 na saida de `ip -f inet addr show wlan0`."""
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/", saida or "")
    return m.group(1) if m else None


def ligar_wifi_pelo_cabo(rodar, adb, serial, avisa=lambda t: None, tentativas=6, pausa=1.0):
    """Aparelho no cabo USB: liga a depuracao por rede (adb tcpip 5555) e conecta pelo IP do Wi-Fi dele.
    Vale ate o aparelho reiniciar. Devolve (endereco | None, mensagem)."""
    avisa("lendo o IP do Wi-Fi de %s…" % serial)
    _, out, _ = rodar([adb, "-s", serial, "shell", "ip -f inet addr show wlan0"], timeout=10)
    ip = ip_do_wifi(out)
    if not ip:
        return None, "%s não está conectado a um Wi-Fi: ligue o Wi-Fi dele na mesma rede do PC e tente de novo." % serial
    avisa("ligando a depuração por rede de %s (porta 5555)…" % serial)
    _, out, err = rodar([adb, "-s", serial, "tcpip", "5555"], timeout=15)
    if "error" in (out + err).lower():
        return None, "o aparelho recusou ligar a depuração por rede: %s" % (out + err).strip()[-150:]
    alvo, saida = ip + ":5555", ""
    for _ in range(tentativas):  # o adb do aparelho reinicia em modo rede: leva um instante
        time.sleep(pausa)
        avisa("conectando em %s…" % alvo)
        _, out, err = rodar([adb, "connect", alvo], timeout=15)
        saida = (out + "\n" + err).strip()
        if conectou(saida):
            return alvo, "conectado em %s pelo Wi-Fi: pode tirar o cabo (vale até o aparelho reiniciar)" % alvo
    return None, "liguei a depuração por rede, mas não conectei em %s: %s" % (alvo, saida[-150:] or "sem resposta")


class JanelaWifi:
    """`ao_conectado(endereco, mensagem)` quando conectou (pelo IP, pareando ou pelo cabo): o app guarda o
    endereco para reconectar sozinho. `aparelhos_usb`: [(serial, rotulo)] dos aparelhos no cabo agora."""

    def __init__(self, raiz, adb, rodar, config, ao_conectado, icone=None, aparelhos_usb=()):
        self.adb, self.rodar, self.config = adb, rodar, config
        self.ao_conectado = ao_conectado
        self.usb = list(aparelhos_usb)
        self.q = queue.Queue()
        w = self.win = tk.Toplevel(raiz)
        w.title("Conectar pelo Wi-Fi")
        if icone:
            icone(w)
        w.configure(bg=visual.BG)
        w.resizable(False, False)
        w.transient(raiz)
        f = self.f = visual.fontes(w)
        self.modo = config.get("modo_wifi") if config.get("modo_wifi") in ("ip", "codigo") else "ip"

        tk.Label(w, text="Conectar pelo Wi-Fi", bg=visual.BG, fg=visual.FG, font=(f["forte"], 14)).pack(anchor="w", padx=20, pady=(18, 0))
        tk.Label(w, text="O aparelho e o PC precisam estar na mesma rede.", bg=visual.BG, fg=visual.FG2,
                 font=(f["texto"], 9)).pack(anchor="w", padx=20, pady=(2, 12))
        abas = tk.Frame(w, bg=visual.BG)
        abas.pack(fill="x", padx=20)
        self.bt_ip = visual.Botao(abas, "rede", "Pelo IP", comando=lambda: self._troca("ip"), largura=200, altura=36)
        self.bt_ip.pack(side="left", padx=(0, 8))
        self.bt_cod = visual.Botao(abas, "seletor", "Parear com código", comando=lambda: self._troca("codigo"), largura=200, altura=36)
        self.bt_cod.pack(side="left")
        self.corpo = tk.Frame(w, bg=visual.BG)
        self.corpo.pack(fill="x", padx=20, pady=(14, 0))

        ips = [x for x in (config.get("ips") or []) if isinstance(x, str)]
        self.var_ip = tk.StringVar(value=ips[0] if ips else "")
        self.var_par = tk.StringVar(value=config.get("ultimo_pareamento", ""))
        self.var_cod = tk.StringVar()
        self.var_con = tk.StringVar()
        self.ips = ips

        self.status = tk.Label(w, text="", bg=visual.BG, fg=visual.FG2, font=(f["texto"], 9), anchor="w", justify="left", wraplength=440)
        self.status.pack(fill="x", padx=20, pady=(10, 0))
        tk.Frame(w, bg=visual.BORDA, height=1).pack(fill="x", pady=(12, 0))
        botoes = tk.Frame(w, bg=visual.BG)
        botoes.pack(fill="x", padx=20, pady=14)
        self.bt_ok = visual.Botao(botoes, "aplicar", "Conectar", comando=self._acao, largura=180, altura=38)
        self.bt_ok.define(ativo=True)
        self.bt_ok.pack(side="right")
        visual.Botao(botoes, "fechar", "Fechar", comando=w.destroy, largura=110, altura=38).pack(side="right", padx=(0, 8))
        w.bind("<Return>", lambda e: self._acao())
        w.bind("<Escape>", lambda e: w.destroy())
        self._troca(self.modo)
        w.update_idletasks()
        x = raiz.winfo_rootx() + max(0, (raiz.winfo_width() - w.winfo_reqwidth()) // 2)
        y = raiz.winfo_rooty() + max(0, (raiz.winfo_height() - w.winfo_reqheight()) // 3)
        w.geometry("+%d+%d" % (x, y))
        w.grab_set()
        w.after(150, self._consome)

    # ---- montagem
    def _rotulo(self, texto, topo=0):
        tk.Label(self.corpo, text=texto, bg=visual.BG, fg=visual.FG, font=(self.f["forte"], 10)).pack(anchor="w", pady=(topo, 6))

    def _dica(self, texto):
        tk.Label(self.corpo, text=texto, bg=visual.BG, fg=visual.FG2, font=(self.f["texto"], 9), justify="left",
                 wraplength=440).pack(anchor="w", pady=(4, 0))

    def _troca(self, modo):
        self.modo = modo
        self.bt_ip.define(ativo=modo == "ip")
        self.bt_cod.define(ativo=modo == "codigo")
        for filho in self.corpo.winfo_children():
            filho.destroy()
        self.status.configure(text="", fg=visual.FG2)
        if modo == "ip":
            self._rotulo("Endereço do aparelho")
            cb = ttk.Combobox(self.corpo, textvariable=self.var_ip, values=self.ips, width=42)
            cb.pack(anchor="w", fill="x", ipady=2)
            self._dica("IP do Wi-Fi do aparelho (Configurações › Wi-Fi › rede conectada), ou IP:porta. Sem porta, o Vision "
                       "procura a da Depuração por Wi-Fi e depois tenta a 5555. O endereço fica salvo e é reconectado sozinho.")
            if self.usb:
                self._rotulo("Ou ligue o Wi-Fi de um aparelho que está no cabo USB", 14)
                for serial, rotulo in self.usb[:4]:
                    visual.Botao(self.corpo, "rede", "Ligar o Wi-Fi pelo cabo: %s" % rotulo,
                                 comando=lambda s=serial: self._pelo_cabo(s), largura=440, altura=34).pack(anchor="w", pady=2)
                self._dica("Liga a depuração por rede (adb tcpip 5555) e conecta pelo Wi-Fi: depois dá para tirar o cabo. "
                           "Vale até o aparelho reiniciar.")
            self.bt_ok.define(texto="Conectar")
            cb.focus_set()
        else:
            passos = tk.Frame(self.corpo, bg=visual.BG2, highlightthickness=1, highlightbackground=visual.BORDA, padx=12, pady=10)
            passos.pack(fill="x")
            for n, t in enumerate(("No aparelho: Opções do desenvolvedor › Depuração por Wi-Fi › ligar.",
                                   "Toque em “Parear o dispositivo com um código de pareamento”.",
                                   "Digite abaixo o IP e a porta e o código de 6 dígitos que aparecem."), 1):
                tk.Label(passos, text="%d.  %s" % (n, t), bg=visual.BG2, fg=visual.FG, font=(self.f["texto"], 9), anchor="w",
                         justify="left", wraplength=420).pack(anchor="w", pady=1)
            self._rotulo("IP e porta de pareamento", 12)
            e1 = ttk.Entry(self.corpo, textvariable=self.var_par)
            e1.pack(fill="x", ipady=2)
            self._rotulo("Código de pareamento", 10)
            ttk.Entry(self.corpo, textvariable=self.var_cod, width=12, font=(self.f["forte"], 12)).pack(anchor="w", ipady=2)
            self._rotulo("IP e porta de conexão (opcional)", 10)
            ttk.Entry(self.corpo, textvariable=self.var_con).pack(fill="x", ipady=2)
            self._dica("Em branco, o Vision acha sozinho. Se não achar, use o “Endereço IP e porta” da tela "
                       "Depuração por Wi-Fi (é diferente do de pareamento). Precisa de Android 11 ou mais novo.")
            self.bt_ok.define(texto="Parear e conectar")
            e1.focus_set()
        self.config["modo_wifi"] = modo

    # ---- acoes
    def _acao(self):
        if getattr(self, "ocupado", False):
            return  # Enter de novo durante o pareamento: nao dispara outro adb pair
        if self.modo == "ip":
            txt = self.var_ip.get().strip()
            if not endereco_valido(txt):
                return self._mostra("Endereço inválido: use algo como 192.168.1.20 ou 192.168.1.20:5555", visual.PERIGO)
            return self._trabalha(lambda avisa: conectar_por_ip(self.rodar, self.adb, txt, avisa=avisa))
        par, cod, con = self.var_par.get().strip(), re.sub(r"\D", "", self.var_cod.get()), self.var_con.get().strip()
        if not endereco_valido(par, exige_porta=True):
            return self._mostra("Informe o IP e a porta de pareamento, como 192.168.1.20:37451", visual.PERIGO)
        if not RX_CODIGO.match(cod):
            return self._mostra("O código tem 6 dígitos", visual.PERIGO)
        if con and not endereco_valido(con, exige_porta=True):
            return self._mostra("IP e porta de conexão inválidos, como 192.168.1.20:41235", visual.PERIGO)
        self.config["ultimo_pareamento"] = par.split(":")[0] + ":"
        self._trabalha(lambda avisa: parear_e_conectar(self.rodar, self.adb, par, cod, con, avisa=avisa))

    def _pelo_cabo(self, serial):
        if getattr(self, "ocupado", False):
            return
        self._trabalha(lambda avisa: ligar_wifi_pelo_cabo(self.rodar, self.adb, serial, avisa=avisa))

    def _trabalha(self, funcao):
        """Roda `funcao(avisa)` fora da interface; ela devolve (endereco | None, mensagem[, aguardando])."""
        self.bt_ok.define(desativado=True)
        self.ocupado = True

        def trabalho():
            try:
                fim = funcao(lambda t: self.q.put(("aviso", t)))
            except Exception as e:  # noqa: BLE001
                fim = (None, str(e)[:200])
            self.q.put(("fim", fim))

        threading.Thread(target=trabalho, daemon=True).start()

    def _mostra(self, texto, cor=None):
        self.status.configure(text=texto, fg=cor or visual.FG2)

    def _consome(self):
        try:
            while not self.q.empty():
                tipo, dado = self.q.get_nowait()
                if tipo == "aviso":
                    self._mostra(dado, visual.ACENTO)
                else:
                    end, msg = dado[0], dado[1]
                    aguardando = len(dado) > 2 and dado[2]
                    self.bt_ok.define(desativado=False)
                    self.ocupado = False
                    if end:
                        self._mostra(("" if aguardando else "✔  ") + msg, visual.ACENTO if aguardando else visual.VERDE)
                        self.ao_conectado(end, msg)
                        if not aguardando:  # pedindo autorizacao: a janela fica com a instrucao
                            self.win.after(1500, self.win.destroy)
                    else:
                        self._mostra(msg, visual.PERIGO)
            self.win.after(150, self._consome)
        except tk.TclError:
            pass  # janela fechada

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Vision - visualizador e controle desktop da tela de um Android.

Abre uma janela propria (sem navegador, sem servidor, sem porta de rede) com a tela do
aparelho. Feito para conviver com a automação Maestro.

POR QUE EXISTE
    O espelho antigo subia o adb 1.0.39 do Minimal ADB. Dois adb de versoes diferentes
    derrubam o servidor um do outro (o cliente mais novo mata o servidor mais velho e
    sobe o seu), e o Maestro perdia a sessão com "protocol fault" no meio do flow.

COMO EVITA ISSO
    - Usa o MESMO adb do Android SDK que o Maestro usa (platform-tools). Nunca o do
      Minimal ADB, salvo se não houver outro, e mesmo assim avisa.
    - NAO sobe nem derruba servidor adb: não chama start-server nem kill-server.
    - So captura com a janela visivel e não pausada (minimizada = aparelho em paz).
    - O controle (toque, teclado, Voltar/Início/Recentes, volume) esta sempre ligado: o
      que você faz na janela acontece no aparelho. Nunca mexe no servidor adb.

Estilo Vysor: barra lateral com ações, tela do aparelho no centro, rodape com status.
Uso:
    python espelha_tela.py                    # abre a janela
    python espelha_tela.py --serial 0123abcd  # aparelho especifico
Atalhos: Ctrl+V cola no aparelho o texto do PC, Ctrl+C traz o texto copiado no aparelho, Ctrl+S salva
a captura, F11 tela cheia, F9 barra lateral.
"""

import argparse
import datetime
import json
import os
import posixpath
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import tempfile
import webbrowser
import zlib
from urllib.parse import quote, unquote

# No .exe sem console (--windowed) nao ha stdout/stderr; evita quebrar em print/argparse.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

try:
    import av  # decodificador H.264 (FFmpeg) do modo video
except Exception:
    av = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adb_servidor  # noqa: E402  (porta do servidor adb, aviso de wrapper)
import seletor  # noqa: E402  (seletor de identificador para o Maestro)
import visual  # noqa: E402  (botoes, icones do Windows, barra lateral e rodape)
import atualizacao  # noqa: E402  (busca de versoes novas no GitHub)
import apk  # noqa: E402  (pacote e versao de um APK, sem o Android SDK)
import diagnostico_video  # noqa: E402  (registro das travadas do video)

VERSAO = "1.6"
ATUALIZACAO = {  # onde o Vision busca versoes novas (Releases do GitHub)
    "repo": "beterraba409/EspelhaTela", "tag": "v", "arquivo": "Vision-Setup-", "token": False,
}
SEM_JANELA = 0x08000000 if os.name == "nt" else 0


def ambiente_limpo():
    """Ambiente para abrir outro programa a partir do Vision empacotado (PyInstaller, arquivo unico).

    Sem isso, um Vision aberto daqui herda as variaveis internas do PyInstaller, tenta usar a pasta
    temporaria deste processo e, quando ela some (este Vision fechou), falha com "Failed to load Python DLL".
    """
    amb = {k: v for k, v in os.environ.items() if not (k.startswith("_PYI_") or k.startswith("_MEI"))}
    amb["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return amb


def caminho_recurso(nome):
    """Arquivo ao lado do script ou, no .exe, dentro do pacote extraido."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, nome)


def aplica_icone(janela):
    """Troca o icone padrão (pena do Tk / Python) pelo do Vision."""
    try:
        ico = caminho_recurso("icone.ico")
        if os.path.isfile(ico):
            janela.iconbitmap(ico)
    except Exception:
        pass


def q(caminho):
    """Aspas simples seguras para o shell do aparelho."""
    return "'" + caminho.replace("'", "'\\''") + "'"


def tamanho_legivel(n):
    n = float(n)
    for un in ("B", "KB", "MB", "GB"):
        if n < 1024 or un == "GB":
            return ("%d %s" % (n, un)) if un == "B" else ("%.1f %s" % (n, un))
        n /= 1024.0


# --------------------------------------------------------------------------- adb
def achar_adb(informado=None):
    """Mesma ordem de preferencia do Maestro: SDK primeiro, Minimal ADB so por ultimo."""
    candidatos = []
    if informado:
        candidatos.append(informado)
    if os.environ.get("ADB"):
        candidatos.append(os.environ["ADB"])
    no_path = shutil.which("adb")
    if no_path:
        candidatos.append(no_path)
    aqui = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    candidatos += [os.path.join(aqui, "adb.exe"), os.path.join(aqui, "platform-tools", "adb.exe")]  # versao portatil
    for var in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if os.environ.get(var):
            candidatos.append(os.path.join(os.environ[var], "platform-tools", "adb.exe"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidatos.append(os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe"))
    vistos = []
    for c in candidatos:
        if c and os.path.isfile(c) and c not in vistos:
            vistos.append(c)
    if not vistos:
        return None
    bons = [c for c in vistos if "minimal adb" not in c.lower()]
    return (bons or vistos)[0]


def rodar(cmd, timeout=15, binario=False):
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=SEM_JANELA)
    return r.returncode, (r.stdout if binario else r.stdout.decode("utf-8", "replace")), r.stderr.decode("utf-8", "replace")


def versao_adb(adb):
    try:
        _, out, _ = rodar([adb, "version"], timeout=8)
        m = re.search(r"Android Debug Bridge version ([\d.]+)", out)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def adb_em_execucao():
    """Caminhos dos adb.exe já rodando (so no Windows). Serve para avisar de conflito."""
    if os.name != "nt":
        return []
    try:
        _, out, _ = rodar(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='adb.exe'\" | "
                "ForEach-Object { $_.ExecutablePath }",
            ],
            timeout=15,
        )
        return sorted({l.strip() for l in out.splitlines() if l.strip()})
    except Exception:
        return []


def listar_aparelhos(adb):
    """Somente leitura. Não inicia servidor de proposito; se não houver, o proprio cliente
    adb sobe o dele (mesma versão do cliente), como qualquer adb faria."""
    try:
        _, out, _ = rodar([adb, "devices", "-l"], timeout=10)
    except Exception:
        return []
    itens = []
    for linha in out.splitlines()[1:]:
        p = linha.split()
        if len(p) >= 2:
            campos = dict(x.split(":", 1) for x in p[2:] if ":" in x)
            modelo = " ".join(campos.get("model", "").replace("_", " ").split())
            itens.append({"serial": p[0], "estado": p[1], "modelo": modelo})
    return itens


ESTADOS = {"device": "", "unauthorized": "n\u00e3o autorizado", "offline": "offline", "recovery": "em recovery",
           "sideload": "em sideload", "bootloader": "em bootloader", "authorizing": "autorizando"}


def rotulo_aparelho(a):
    """Como o aparelho aparece na lista: serial primeiro (o resto do programa le o serial até o espaco)."""
    partes = [a["serial"]]
    if a.get("modelo"):
        partes.append(a["modelo"])
    txt = "  \u00b7  ".join(partes)
    estado = ESTADOS.get(a["estado"], a["estado"])
    return txt + ("  (%s)" % estado if estado else "")


# --------------------------------------------------------------------- captura
MODOS_CAPTURA = {
    "V\u00eddeo r\u00e1pido": ("video", "rapido"),
    "V\u00eddeo equilibrado": ("video", "equilibrado"),
    "V\u00eddeo n\u00edtido": ("video", "nitido"),
    "Quadros (leve)": ("quadros", "rapido"),
}
NOMES_ANTIGOS_CAPTURA = {"Video - Rápido": "V\u00eddeo r\u00e1pido", "Video - Equilibrado": "V\u00eddeo equilibrado",
                         "Video - Nitido": "V\u00eddeo n\u00edtido"}
PERFIS_VIDEO = {  # lado maior em pixels (0 = nativo) e taxa de bits
    "rapido": (640, "4M"),  # 4 Mbps: telas que mudam inteiras (transicoes, veus) nao borram nem engasgam
    "equilibrado": (960, "4M"),
    "nitido": (0, "8M"),
}


def parar_gravacao_remota(adb, serial):
    """Encerra um screenrecord que tenha ficado vivo no aparelho (matar o adb local não basta)."""
    try:
        rodar([adb, "-s", serial, "shell", "pids=$(pidof screenrecord 2>/dev/null); [ -n \"$pids\" ] && kill $pids; true"], timeout=8)
    except Exception:
        pass


class Injetor:
    """Canal de entrada sempre aberto: um processo Java minusculo (injetor/) rodando no aparelho.

    Cada toque vira uma linha de texto numa conexão já aberta, em vez de um `adb shell input tap`
    (processo novo + JVM a cada clique, de 0,5 a 1 s em aparelhos fracos). Funciona em qualquer
    aparelho Android 4.1+ em que o usuario shell possa injetar eventos (mesma tecnica do scrcpy).
    Se não subir, o app cai para o `adb shell input`, mais lento mas universal."""

    REMOTO = "/data/local/tmp/espelha-input.jar"

    def __init__(self, adb):
        self.adb = adb
        self.serial = ""
        self.proc = None
        self.pronto = False
        self.erro = ""
        self.ultimo_erro = ""
        self.t_erro = 0.0
        self.iniciando = False
        self.lock = threading.Lock()
        self.respostas = queue.Queue()  # linhas "CLIP ..." e "CLIPSET ..." do injetor

    def ok(self, serial):
        return bool(self.pronto and self.serial == serial and self.proc is not None and self.proc.poll() is None)

    def garantir(self, serial):
        """Sobe o injetor em segundo plano, sem travar a interface."""
        if not serial or self.iniciando or self.ok(serial):
            return
        if self.erro and self.serial == serial and time.time() - self.t_erro < 30:
            return  # falhou ha pouco neste aparelho: tenta de novo so depois de 30 s
        self.iniciando = True
        threading.Thread(target=self._inicia, args=(serial,), daemon=True).start()

    def _inicia(self, serial):
        try:
            self.parar()
            self.serial, self.erro, self.pronto = serial, "", False
            jar = caminho_recurso("espelha-input.jar")
            if not os.path.isfile(jar):
                self.erro = "espelha-input.jar ausente"
                return
            try:
                rc, _, err = rodar([self.adb, "-s", serial, "push", jar, self.REMOTO], timeout=30)
            except Exception as e:  # noqa: BLE001
                self.erro = "push do injetor falhou: %s" % str(e)[:60]
                return
            if rc != 0:
                self.erro = "push do injetor falhou: " + err.strip()[:80]
                return
            proc = subprocess.Popen(
                [self.adb, "-s", serial, "shell", "CLASSPATH=%s exec app_process / espelhatela.Injector" % self.REMOTO],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=SEM_JANELA,
            )
            self.proc = proc

            def leitor():
                for bruto in proc.stdout:
                    linha = bruto.decode("utf-8", "replace").strip()
                    if linha == "READY":
                        self.pronto = True
                    elif linha.startswith("ERR init"):
                        self.erro = linha[:120]
                        self.t_erro = time.time()
                    elif linha.startswith("ERR"):
                        self.ultimo_erro = linha[:120]
                    elif linha.split(" ", 1)[0] in ("CLIP", "CLIPSET"):
                        self.respostas.put(linha)

            threading.Thread(target=leitor, daemon=True).start()
            t0 = time.time()
            while not self.pronto and not self.erro and proc.poll() is None and time.time() - t0 < 10:
                time.sleep(0.05)
            if not self.pronto and not self.erro:
                self.erro = "injetor não respondeu"
        finally:
            if self.erro:
                self.t_erro = time.time()
            self.iniciando = False

    def envia(self, linha, serial):
        if not self.ok(serial):
            return False
        try:
            with self.lock:
                self.proc.stdin.write((linha + "\n").encode("utf-8"))
                self.proc.stdin.flush()
            return True
        except Exception:
            self.pronto = False
            return False

    def pergunta(self, linha, serial, tipo, espera=2.0):
        """Envia um comando e espera a resposta `tipo` (ex.: "CLIP"). Devolve o resto da linha ou None."""
        while not self.respostas.empty():
            self.respostas.get_nowait()  # resposta velha de um pedido que expirou
        if not self.envia(linha, serial):
            return None
        fim = time.time() + espera
        while time.time() < fim:
            try:
                r = self.respostas.get(timeout=max(0.01, fim - time.time()))
            except queue.Empty:
                return None
            cab, _, resto = r.partition(" ")
            if cab == tipo:
                return resto
        return None

    def parar(self):
        p, self.proc, self.pronto = self.proc, None, False
        if p is not None:
            try:
                p.stdin.write(b"q\n")
                p.stdin.flush()
            except Exception:
                pass
            try:
                p.kill()
            except Exception:
                pass


class Captura(threading.Thread):
    """Entrega a tela em segundo plano. So mexe no aparelho quando `ativo` e verdadeiro.

    Dois modos: "video" (screenrecord H.264 decodificado aqui, fluido) e "quadros" (screencap
    quadro a quadro, mais leve). Se o video não funcionar no aparelho, cai para quadros sozinho."""

    def __init__(self, adb, serial, intervalo_min, modo="video", perfil="rapido"):
        super().__init__(daemon=True)
        self.adb = adb
        self.serial = serial
        self.intervalo_min = intervalo_min
        self.modo = modo
        self.perfil = perfil
        self.ativo = True
        self.parar = False
        self._img = None  # PIL.Image RGB: quadro do modo quadros, ou o do video convertido sob demanda
        self._av = None  # ultimo quadro do video (av.VideoFrame), ainda em YUV
        self._img_de = None  # quadro do video de onde _img saiu
        self.seq = 0
        self.ms = 0
        self.erro = ""
        self.gzip_ok = True
        self.video_ok = av is not None
        self.falhas_video = 0  # falhas seguidas do video; com falha, os quadros seguram a imagem ate a nova tentativa
        self.diag = diagnostico_video.RegistroVideo(os.path.join(pasta_dados(), "video.log"))
        self._fluxo_ativo = None  # a gravacao cujos quadros vao para a tela
        self._sem_sobreposicao = set()  # aparelhos que nao aceitam duas gravacoes ao mesmo tempo
        self.t_falha_video = 0.0
        self.via = "quadros"
        self.nota = ""
        self.dev_size = None  # resolucao real do aparelho (para mapear cliques)
        self._dev_serial = ""
        self.aparelhos = []
        self.ips = []  # aparelhos de rede (ip:porta) a reconectar se o servidor adb reiniciar
        self._ult_lista = 0.0
        self.t_frame = 0.0

    # O video chega a ate 60 qd/s e a janela desenha uns 20: o quadro so vira RGB quando alguem o
    # usa, e para a janela ja sai no tamanho certo (`imagem`). Converter todo quadro era o maior
    # custo de CPU e o que deixava o clique esperando em notebook fraco.
    @property
    def frame(self):
        """Ultimo quadro como PIL.Image RGB, no tamanho em que chegou (convertido so quando pedido)."""
        fr = self._av
        if fr is None:
            return self._img
        if self._img_de is not fr:
            self._img, self._img_de = fr.to_image(), fr
        return self._img

    @frame.setter
    def frame(self, img):
        self._av, self._img, self._img_de = None, img, None

    @property
    def tamanho(self):
        """(largura, altura) do ultimo quadro sem converter nada; None sem imagem."""
        fr = self._av
        if fr is not None:
            return fr.width, fr.height
        img = self._img
        return img.size if img is not None else None

    def imagem(self, w, h):
        """Ultimo quadro já no tamanho da janela. No video, cor e escala saem numa passada so (swscale)."""
        fr = self._av
        if fr is None:
            img = self._img
            if img is None or img.size == (w, h):
                return img
            return img.resize((w, h), Image.BILINEAR)
        modo = "AREA" if w < fr.width * 0.8 else "FAST_BILINEAR"  # reduzir muito pede media de area (sem serrilhado)
        return fr.reformat(width=w, height=h, format="rgb24", interpolation=modo).to_image()

    def trocar(self, serial):
        self.serial = serial
        self.frame = None
        self.video_ok, self.falhas_video = av is not None, 0  # a falha era do aparelho anterior
        self.seq = 0
        self.erro = ""
        self.dev_size = None

    # ---- resolucao do aparelho
    def dims(self):
        if self.dev_size and self._dev_serial == self.serial:
            return self.dev_size
        try:
            _, out, _ = rodar([self.adb, "-s", self.serial, "shell", "wm size"], timeout=10)
            achados = re.findall(r"(Override|Physical) size:\s*(\d+)x(\d+)", out)
            if achados:
                pref = [a for a in achados if a[0] == "Override"] or achados
                self.dev_size = (int(pref[-1][1]), int(pref[-1][2]))
                self._dev_serial = self.serial
        except Exception:
            pass
        return self.dev_size

    # ---- modo quadros
    def _comando(self):
        base = [self.adb] + (["-s", self.serial] if self.serial else [])
        if self.gzip_ok:
            return base + ["exec-out", "screencap | gzip -1"]
        return base + ["exec-out", "screencap"]

    def _decodifica(self, dados):
        if self.gzip_ok:
            dados = zlib.decompress(dados, 16 + zlib.MAX_WBITS)
        w, h, fmt = struct.unpack("<III", dados[:12])
        corpo = len(dados) - 4 * w * h
        if corpo not in (12, 16) or fmt != 1:
            raise ValueError("formato de screencap inesperado (w=%d h=%d fmt=%d)" % (w, h, fmt))
        return Image.frombuffer("RGBA", (w, h), dados[corpo:], "raw", "RGBA", 0, 1).convert("RGB")

    def _passo_quadros(self):
        self.via = "quadros"
        t0 = time.time()
        try:
            rc, out, err = rodar(self._comando(), timeout=20, binario=True)
            if rc != 0 or not out:
                msg = err.strip() or "captura vazia"
                if self.gzip_ok and "gzip" in msg.lower():
                    self.gzip_ok = False  # ROM sem gzip: usa o bruto
                    return
                raise RuntimeError(msg)
            try:
                img = self._decodifica(out)
            except zlib.error:
                self.gzip_ok = False
                return
            self.frame = img
            self.t_frame = time.time()
            self.ms = int((time.time() - t0) * 1000)
            self.erro = ""
            self.seq += 1
        except Exception as e:  # noqa: BLE001
            self.erro = str(e)[:160]
            time.sleep(2.0)
        resto = self.intervalo_min - (time.time() - t0)
        if resto > 0:
            time.sleep(resto)

    # ---- modo video
    LIMITE_GRAVACAO = 180  # s: o screenrecord do Android grava no maximo isso de uma vez
    ANTECEDENCIA = 6  # s antes do fim em que a proxima gravacao ja e aberta (troca sem pausa)

    def _abre_fluxo(self, serial, size, taxa, candidato=False):
        """Uma gravacao (screenrecord) com seu decodificador. Os quadros so vao para a tela se ela for
        a gravacao ativa; uma candidata assume no primeiro quadro (troca sem pausa)."""
        cmd = [self.adb, "-s", serial, "exec-out", "screenrecord", "--output-format=h264", "--bit-rate", taxa,
               "--time-limit", str(self.LIMITE_GRAVACAO)]
        if size:
            cmd += ["--size", size]
        cmd.append("-")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=SEM_JANELA, bufsize=0)
        f = {"proc": proc, "frames": 0, "erro": "", "stderr": b"", "inicio": time.time(), "candidato": candidato,
             "t_primeiro": None, "t_fim": None}

        def drena_erro():  # sem isso o pipe de erro pode encher e travar o screenrecord
            try:
                while True:
                    bloco = proc.stderr.read(1024)
                    if not bloco:
                        break
                    f["stderr"] = (f["stderr"] + bloco)[-2048:]
            except Exception:
                pass

        def leitor():
            try:
                codec = av.CodecContext.create("h264", "r")
                try:
                    codec.thread_count = 1  # sem fila de threads: menos atraso
                except Exception:
                    pass
                while True:
                    dados = proc.stdout.read(65536)
                    if not dados:
                        break
                    try:
                        for pkt in codec.parse(dados):
                            t0 = time.perf_counter()
                            for fr in codec.decode(pkt):
                                f["frames"] += 1
                                if f["t_primeiro"] is None:
                                    f["t_primeiro"] = time.time()
                                if self._fluxo_ativo is not f:
                                    if not f["candidato"]:
                                        continue  # gravacao antiga, ja substituida
                                    self._fluxo_ativo = f  # a proxima gravacao assume sem pausa
                                self._av = fr  # sem converter: so o quadro desenhado vira RGB
                                self.t_frame = time.time()
                                self.erro = ""
                                self.seq += 1
                                self.diag.quadro((time.perf_counter() - t0) * 1000, diagnostico_video.bytes_na_fila(proc))
                    except Exception as e:  # noqa: BLE001  pacote corrompido: segue com o proximo
                        f["erro"] = str(e)[:120]
            except Exception as e:  # noqa: BLE001
                f["erro"] = str(e)[:120]

        f["leitor"] = threading.Thread(target=leitor, daemon=True)
        f["leitor"].start()
        threading.Thread(target=drena_erro, daemon=True).start()
        return f

    @staticmethod
    def _fecha_fluxo(f):
        if f is None:
            return
        try:
            f["proc"].kill()
        except Exception:
            pass
        f["leitor"].join(timeout=1.0)

    def _stream(self, size, taxa):
        """Video continuo: gravacoes de ate 180 s emendadas sem pausa (a proxima abre antes do fim da
        atual). Devolve 'interrompido', 'ok' (acabou e o ciclo reinicia) ou 'falhou'."""
        serial, estado0 = self.serial, (self.modo, self.perfil)
        parar_gravacao_remota(self.adb, serial)
        atual = self._abre_fluxo(serial, size, taxa)
        self._fluxo_ativo = atual
        proximo = None
        self.diag.evento("gravacao iniciada: %s, %s, %s" % (serial, size or "tamanho nativo", taxa))
        self.via = "video"
        motivo, teve_quadro = "fim", False
        while True:
            agora = time.time()
            self.diag.periodico()
            if self.parar or not self.ativo or (self.modo, self.perfil) != estado0 or self.serial != serial:
                motivo = "interrompido"
                break
            if atual["frames"] and not teve_quadro:
                teve_quadro = True
                self.diag.evento("primeiro quadro em %.1f s" % (atual["t_primeiro"] - atual["inicio"]))
            # perto do fim da gravacao: abre a proxima para emendar sem pausa
            if (proximo is None and atual["frames"] and serial not in self._sem_sobreposicao
                    and agora - atual["inicio"] > self.LIMITE_GRAVACAO - self.ANTECEDENCIA):
                proximo = self._abre_fluxo(serial, size, taxa, candidato=True)
            if proximo is not None:
                if self._fluxo_ativo is proximo:  # a proxima ja mostrou o primeiro quadro
                    self.diag.evento("troca de gravacao sem pausa (a nova assumiu %.1f s depois de aberta)" % (
                        proximo["t_primeiro"] - proximo["inicio"]))
                    self._fecha_fluxo(atual)
                    atual, proximo = proximo, None
                    atual["candidato"] = False
                    continue
                if proximo["proc"].poll() is not None and not proximo["frames"]:
                    self._sem_sobreposicao.add(serial)
                    self.diag.evento("o aparelho nao aceita duas gravacoes ao mesmo tempo: reinicio normal a cada %d s" % self.LIMITE_GRAVACAO)
                    self._fecha_fluxo(proximo)
                    proximo = None
            if atual["proc"].poll() is not None or not atual["leitor"].is_alive():
                atual["t_fim"] = atual["t_fim"] or agora
                # a proxima ainda nao mostrou quadro: espera um pouco por ela antes de reiniciar tudo
                if proximo is None or proximo["proc"].poll() is not None or agora - atual["t_fim"] > 4:
                    break
            if atual["frames"] == 0 and agora - atual["inicio"] > 12:
                motivo = "falhou"
                break
            if atual["frames"]:
                self.falhas_video = 0
            elif self.falhas_video:  # nova tentativa depois de uma falha: a imagem segue por quadros
                self._passo_quadros()
                self.via = "video"
                continue
            time.sleep(0.1)
        self._fecha_fluxo(proximo)
        self._fecha_fluxo(atual)
        threading.Thread(target=parar_gravacao_remota, args=(self.adb, serial), daemon=True).start()
        if motivo == "interrompido":
            return "interrompido"
        if atual["frames"] > 0 or teve_quadro:
            self.diag.evento("gravacao terminou (reinicio com pausa curta)")
            return "ok"
        detalhe = atual["stderr"].decode("utf-8", "replace").strip().splitlines()
        self.erro_video = (detalhe[-1] if detalhe else atual["erro"] or "sem imagem")[:120]
        self.diag.evento("gravacao falhou: %s" % self.erro_video)
        return "falhou"

    def _ciclo_video(self):
        dims = self.dims()
        maxd, taxa = PERFIS_VIDEO.get(self.perfil, PERFIS_VIDEO["rapido"])
        tentativas = []
        if dims and maxd and max(dims) > maxd:
            w, h = dims
            k = maxd / float(max(w, h))
            tentativas.append("%dx%d" % (max(16, int(round(w * k / 16.0)) * 16), max(16, int(round(h * k / 16.0)) * 16)))
        tentativas.append(None)  # tamanho nativo, para encoders que recusam o reduzido
        for size in tentativas:
            if self.parar or not self.ativo or self.modo != "video":
                return
            r = self._stream(size, taxa)
            if r in ("ok", "interrompido"):
                return
        self.video_ok = False
        self.falhas_video += 1
        self.t_falha_video = time.time()
        self.nota = "video indisponivel: %s (nova tentativa em %d s)" % (getattr(self, "erro_video", "?"), self.espera_video())

    def espera_video(self):
        """Pausa até tentar o video de novo: 30 s, 1 min, 2 min, 4 min e depois a cada 5 min."""
        return min(300, 30 * 2 ** max(0, self.falhas_video - 1))

    def _hora_de_tentar_video(self):
        return (self.modo == "video" and not self.video_ok and av is not None and self.falhas_video > 0
                and time.time() - self.t_falha_video >= self.espera_video())

    # ---- laco principal
    def _lista_loop(self):
        """Atualiza a lista de aparelhos em paralelo (o modo video prende o laco principal)."""
        ultimo = 0.0
        while not self.parar:
            self.aparelhos = listar_aparelhos(self.adb)
            if self.ips and time.time() - ultimo > 30:  # servidor reiniciado = aparelhos de rede somem da lista
                ultimo = time.time()
                presentes = {a["serial"] for a in self.aparelhos}
                for ip in list(self.ips):
                    if ip not in presentes and not self.parar:
                        try:
                            rodar([self.adb, "connect", ip], timeout=8)
                        except Exception:  # noqa: BLE001
                            pass
            for _ in range(50):
                if self.parar:
                    return
                time.sleep(0.1)

    def run(self):
        threading.Thread(target=self._lista_loop, daemon=True).start()
        while not self.parar:
            if not self.ativo:
                time.sleep(0.2)
                continue
            if not self.serial:
                ok = [a for a in self.aparelhos if a["estado"] == "device"]
                if len(ok) == 1:
                    self.serial = ok[0]["serial"]
                else:
                    self.erro = "V\u00e1rios aparelhos conectados. Escolha um na lista acima." if ok else (
                        motivo_sem_aparelho(self.aparelhos) or "Nenhum aparelho conectado. Ligue a depura\u00e7\u00e3o USB e conecte o cabo, ou use o Wi-Fi.")
                    time.sleep(1.5)
                    continue
            try:
                if self._hora_de_tentar_video():  # a falha pode ter sido passageira (rede, aparelho ocupado)
                    self.video_ok, self.nota = True, ""
                if self.modo == "video" and self.video_ok:
                    self._ciclo_video()
                else:
                    self._passo_quadros()
            except Exception as e:  # noqa: BLE001
                self.erro = str(e)[:160]
                time.sleep(2.0)


class Dica:
    """Balao ao passar o mouse sobre um widget: titulo em negrito e uma linha de detalhe."""

    def __init__(self, widget, titulo, detalhe="", atraso=350):
        self.w, self.titulo, self.detalhe, self.atraso = widget, titulo, detalhe, atraso
        self.job = None
        self.top = None
        widget.bind("<Enter>", self._entra, add="+")
        widget.bind("<Leave>", self._sai, add="+")
        widget.bind("<ButtonPress>", self._sai, add="+")

    def _entra(self, _e=None):
        self._sai()
        self.job = self.w.after(self.atraso, self._mostra)

    def _mostra(self):
        self.job = None
        try:
            top = tk.Toplevel(self.w)
            top.wm_overrideredirect(True)
            top.attributes("-topmost", True)
            caixa = tk.Frame(top, bg="#0f0f10", highlightthickness=1, highlightbackground="#4a4a50")
            caixa.pack()
            tk.Label(caixa, text=self.titulo, bg="#0f0f10", fg="#ffffff", font=("Segoe UI", 9, "bold"), padx=10, pady=(5 if self.detalhe else 5)).pack(anchor="w")
            if self.detalhe:
                tk.Label(caixa, text=self.detalhe, bg="#0f0f10", fg="#a9a9b0", font=("Segoe UI", 8), padx=10, wraplength=260, justify="left").pack(anchor="w", pady=(0, 5))
            top.update_idletasks()
            x = self.w.winfo_rootx() + self.w.winfo_width() + 8
            y = self.w.winfo_rooty() + max(0, (self.w.winfo_height() - top.winfo_height()) // 2)
            if x + top.winfo_width() > self.w.winfo_screenwidth():  # sem espaco a direita
                x = self.w.winfo_rootx() - top.winfo_width() - 8
            top.geometry("+%d+%d" % (x, y))
            self.top = top
        except tk.TclError:
            self.top = None

    def _sai(self, _e=None):
        if self.job:
            try:
                self.w.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        if self.top is not None:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
            self.top = None


def kb_para_mb(kb):
    return kb / 1024.0


def parse_amostra(saida):
    """Saída de `cat /proc/meminfo | head -6; echo ---; ps -A -o PID,RSS,NAME || ps`.

    Le o cabecalho do ps (PID, RSS, NAME), entao serve ao toybox (Android 7+) e ao toolbox antigo."""
    antes, _, depois = saida.partition("---")
    mem = {}
    for l in antes.splitlines():
        m = re.match(r"\s*(\w+):\s+(\d+)\s*kB", l)
        if m:
            mem[m.group(1)] = int(m.group(2))
    if mem and "MemAvailable" not in mem:  # kernels antigos nao trazem MemAvailable
        mem["MemAvailable"] = mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0)
    procs = {}
    ip = ir = None
    for l in depois.splitlines():
        cols = l.split()
        if not cols:
            continue
        if ip is None:
            if "PID" in cols and "RSS" in cols:
                ip, ir = cols.index("PID"), cols.index("RSS")
            continue
        if len(cols) <= max(ip, ir) or not (cols[ip].isdigit() and cols[ir].isdigit()):
            continue
        rss, nome = int(cols[ir]), cols[-1]  # NAME e a ultima coluna
        if rss > 0 and not nome.startswith("["):
            antigo = procs.get(nome)
            if antigo:  # varios processos com o mesmo nome: soma
                procs[nome] = (antigo[0], antigo[1] + rss, antigo[2] + 1)
            else:
                procs[nome] = (int(cols[ip]), rss, 1)
    return mem, procs


def parse_pss(saida):
    """Secao 'Total PSS by process' do `dumpsys meminfo` (valores em K, separador de milhar variavel)."""
    res = {}
    dentro = False
    for l in saida.splitlines():
        if l.startswith("Total PSS by process"):
            dentro = True
            continue
        if dentro:
            if not l.strip():
                break
            m = re.match(r"\s*([\d.,]+)\s*(?:K|kB):\s+(.+?)\s+\(pid (\d+)", l)
            if m:
                res[m.group(2).strip()] = int(re.sub(r"\D", "", m.group(1)))
    return res


def parse_detalhe(saida):
    linhas = saida.splitlines()
    out, ativo = [], False
    for l in linhas:
        if "App Summary" in l or l.strip() == "Objects":
            ativo = True
        if ativo and l.strip():
            out.append(l.rstrip())
    return "\n".join(out[:40]) if out else "\n".join(linhas[:40])


class MonitorMemoria:
    """Gerenciador de tarefas do aparelho: memória por processo, histórico e detalhe.

    Modo rápido (padrão): `ps` + /proc/meminfo, cerca de 0,8 s por leitura, quase sem custo no
    aparelho. PSS preciso (dumpsys meminfo, ~6 s num POS de entrada) e detalhe por app so sob demanda."""

    INTERVALOS = {"2 s": 2, "3 s": 3, "5 s": 5, "10 s": 10, "30 s": 30}

    def __init__(self, app):
        self.app = app
        self.cap = app.cap
        self.q = queue.Queue()
        self.hist = {}      # nome -> [(t, rss_kb)]
        self.base = {}      # nome -> primeiro rss visto (para o delta)
        self.pss = {}       # nome -> pss_kb (medicao precisa)
        self.dados = {}     # nome -> (pid, rss_kb, n)
        self.sist = []      # [(t, usada_kb)]
        self.mem = {}
        self.intervalo = 3
        self.pausado = False
        self.parar = False
        self.ordem = ("mem", True)
        self.selecionado = None
        self.ocupado = False

        w = self.win = tk.Toplevel(app.root)
        w.title("Monitor de memória - %s" % (self.cap.serial or "aparelho"))
        aplica_icone(w)
        w.configure(bg=BG)
        w.geometry("820x700")
        w.minsize(640, 520)
        w.protocol("WM_DELETE_WINDOW", self.fechar)

        # --- resumo do aparelho
        cima = tk.Frame(w, bg=BG)
        cima.pack(fill="x", padx=12, pady=(10, 4))
        self.lb_resumo = tk.Label(cima, text="lendo...", bg=BG, fg=FG, anchor="w", font=("Segoe UI", 10, "bold"))
        self.lb_resumo.pack(fill="x")
        self.barra = tk.Canvas(cima, height=14, bg=BG2, highlightthickness=0)
        self.barra.pack(fill="x", pady=(4, 0))

        # --- controles
        ctl = tk.Frame(w, bg=BG)
        ctl.pack(fill="x", padx=12, pady=6)
        self.filtro = tk.StringVar()
        ent = tk.Entry(ctl, textvariable=self.filtro, bg=BG2, fg=FG, insertbackground=FG, relief="flat", width=22)
        ent.pack(side="left", ipady=3)
        Dica(ent, "Filtro", "Digite parte do nome do processo")
        self.filtro.trace_add("write", lambda *_: self.redesenha_tabela())
        self.cb_int = ttk.Combobox(ctl, state="readonly", width=6, values=list(self.INTERVALOS))
        self.cb_int.set("3 s")
        self.cb_int.pack(side="left", padx=(8, 0))
        self.cb_int.bind("<<ComboboxSelected>>", lambda e: setattr(self, "intervalo", self.INTERVALOS[self.cb_int.get()]))
        Dica(self.cb_int, "Intervalo de leitura", "Leituras rapidas (ps), baixo impacto no aparelho")
        self.var_ativa = tk.BooleanVar(value=bool(app.config.get("memoria_ativa", True)))
        self.ck = ttk.Checkbutton(ctl, text="Medição ligada", variable=self.var_ativa, command=self.liga_desliga)
        self.ck.pack(side="left", padx=(8, 0))
        Dica(self.ck, "Habilitar / desabilitar a medição", "Desligada: nenhuma leitura e feita no aparelho. A escolha fica lembrada")
        self.bt_pss = ttk.Button(ctl, text="Medir PSS", command=self.mede_pss)
        self.bt_pss.pack(side="left", padx=(8, 0))
        Dica(self.bt_pss, "Medição precisa (PSS)", "dumpsys meminfo: mais exato que o RSS, mas leva uns 6 s e pesa no aparelho")
        self.bt_det = ttk.Button(ctl, text="Detalhar app", command=self.detalha)
        self.bt_det.pack(side="left", padx=(8, 0))
        Dica(self.bt_det, "Detalhar app selecionado", "Java heap, nativo, gráficos, Views e Activities (util para achar vazamento)")
        self.bt_kill = ttk.Button(ctl, text="Encerrar app", command=self.encerra)
        self.bt_kill.pack(side="left", padx=(8, 0))
        Dica(self.bt_kill, "Encerrar app", "am force-stop no pacote selecionado (pede confirmacao)")
        bt_csv = ttk.Button(ctl, text="Exportar CSV", command=self.exporta)
        bt_csv.pack(side="right")
        Dica(bt_csv, "Exportar histórico", "Salva todas as leituras em Imagens\\Vision")

        # --- tabela
        corpo = tk.Frame(w, bg=BG)
        corpo.pack(fill="both", expand=True, padx=12)
        cols = ("nome", "pid", "mem", "pss", "pct", "delta")
        self.tv = ttk.Treeview(corpo, columns=cols, show="headings", selectmode="browse", height=12)
        titulos = {"nome": "Processo", "pid": "PID", "mem": "RSS (MB)", "pss": "PSS (MB)", "pct": "% RAM", "delta": "Variação (MB)"}
        larg = {"nome": 300, "pid": 60, "mem": 90, "pss": 90, "pct": 70, "delta": 110}
        for c in cols:
            self.tv.heading(c, text=titulos[c], command=lambda c=c: self.ordena(c))
            self.tv.column(c, width=larg[c], anchor="w" if c == "nome" else "e")
        sb = ttk.Scrollbar(corpo, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv.tag_configure("favorito", foreground=visual.ACENTO)
        self.tv.tag_configure("cresce", foreground=visual.AMBAR)
        self.tv.bind("<<TreeviewSelect>>", self.escolheu)

        # --- graficos e detalhe
        base = tk.Frame(w, bg=BG)
        base.pack(fill="x", padx=12, pady=(8, 4))
        self.g_sis = tk.Canvas(base, height=110, bg=BG2, highlightthickness=0)
        self.g_sis.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.g_app = tk.Canvas(base, height=110, bg=BG2, highlightthickness=0)
        self.g_app.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.txt = tk.Text(w, height=9, bg=BG2, fg=FG, relief="flat", font=("Consolas", 9), padx=8, pady=6)
        self.txt.pack(fill="x", padx=12, pady=(0, 6))
        self.txt.insert("1.0", "Selecione um app e clique em Detalhar para ver heap, gráficos, Views e Activities.")
        self.txt.configure(state="disabled")
        self.rodape = tk.Label(w, text="", bg=BG, fg=FG2, anchor="w", font=("Segoe UI", 9), padx=12)
        self.rodape.pack(fill="x", pady=(0, 8))

        self.liga_desliga(inicial=True)
        threading.Thread(target=self._coleta, daemon=True).start()
        w.after(250, self._consome)

    # ---- coleta (thread) -> fila -> UI
    def _adb(self, *args, timeout=15):
        return rodar([self.cap.adb, "-s", self.cap.serial] + list(args), timeout=timeout)

    def _coleta(self):
        while not self.parar:
            t0 = time.time()
            if not self.pausado and self.cap.serial:
                try:
                    _, out, err = self._adb("shell", "cat /proc/meminfo | head -6; echo ---; ps -A -o PID,RSS,NAME 2>/dev/null || ps")
                    if "---" in out:
                        self.q.put(("amostra", t0, out))
                    else:
                        self.q.put(("erro", (err or out or "sem resposta")[:120]))
                except Exception as e:  # noqa: BLE001
                    self.q.put(("erro", str(e)[:120]))
            fim = t0 + self.intervalo
            while not self.parar and time.time() < fim:
                time.sleep(0.2)

    def _consome(self):
        if self.parar:
            return
        try:
            while not self.q.empty():
                tipo, *resto = self.q.get_nowait()
                if tipo == "amostra":
                    self._amostra(resto[0], resto[1])
                elif tipo == "erro":
                    self.rodape.configure(text="erro: " + resto[0], fg=PERIGO)
                elif tipo == "pss":
                    self.pss = resto[0]
                    self.ocupado = False
                    self.bt_pss.configure(state="normal", text="Medir PSS")
                    self.rodape.configure(text="PSS medido para %d processos" % len(self.pss), fg=FG2)
                    self.redesenha_tabela()
                elif tipo == "detalhe":
                    self._mostra_texto(resto[0])
                    self.bt_det.configure(state="normal", text="Detalhar app")
        except Exception as e:  # noqa: BLE001
            self.rodape.configure(text="erro: %s" % e, fg=PERIGO)
        self.win.after(250, self._consome)

    def _amostra(self, t, saida):
        mem, procs = parse_amostra(saida)
        self.mem, self.dados = mem, procs
        total, disp = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
        usada = max(0, total - disp)
        self.sist = (self.sist + [(t, usada)])[-600:]
        for nome, (pid, rss, n) in procs.items():
            self.base.setdefault(nome, rss)
            self.hist.setdefault(nome, []).append((t, rss))
            if len(self.hist[nome]) > 600:
                del self.hist[nome][:-600]
        if total:
            pct = usada * 100.0 / total
            self.lb_resumo.configure(text="RAM: %.0f MB usados de %.0f MB (%.0f%%)  -  disponível %.0f MB  -  livre %.0f MB" % (kb_para_mb(usada), kb_para_mb(total), pct, kb_para_mb(disp), kb_para_mb(mem.get("MemFree", 0))))
            self.barra.update_idletasks()
            w = max(self.barra.winfo_width(), 10)
            self.barra.delete("all")
            cor = PERIGO if pct > 90 else ("#ffb454" if pct > 75 else ACENTO)
            self.barra.create_rectangle(0, 0, w * pct / 100.0, 14, fill=cor, width=0)
        self.rodape.configure(text="atualizado %s  -  %d processos  -  RSS conta memória compartilhada; use Medir PSS para o valor exato" % (time.strftime("%H:%M:%S", time.localtime(t)), len(procs)), fg=FG2)
        self.redesenha_tabela()
        self.grafico(self.g_sis, [v for _, v in self.sist], "RAM usada do aparelho (MB)", ACENTO)
        self.grafico_app()

    # ---- tabela
    def ordena(self, col):
        atual, desc = self.ordem
        self.ordem = (col, (not desc) if atual == col else (col != "nome"))
        self.redesenha_tabela()

    def redesenha_tabela(self):
        total = self.mem.get("MemTotal", 0) or 1
        f = self.filtro.get().strip().lower()
        linhas = []
        for nome, (pid, rss, n) in self.dados.items():
            if f and f not in nome.lower():
                continue
            pss = self.pss.get(nome)
            delta = rss - self.base.get(nome, rss)
            linhas.append({"nome": nome, "pid": pid, "mem": rss, "pss": pss if pss is not None else -1, "pct": rss, "delta": delta, "n": n})
        col, desc = self.ordem
        linhas.sort(key=lambda r: (r["nome"].lower() if col == "nome" else r[col]), reverse=desc)
        existentes = set(self.tv.get_children())
        for r in linhas[:300]:
            nome = r["nome"]
            tags = []
            if nome.split(":")[0] in favoritos(self.app.config):
                tags.append("favorito")
            if r["delta"] > 20 * 1024:
                tags.append("cresce")
            vals = (nome + (" (x%d)" % r["n"] if r["n"] > 1 else ""), r["pid"], "%.1f" % kb_para_mb(r["mem"]), "-" if r["pss"] < 0 else "%.1f" % kb_para_mb(r["pss"]), "%.1f%%" % (r["mem"] * 100.0 / total), "%+.1f" % kb_para_mb(r["delta"]))
            if nome in existentes:
                self.tv.item(nome, values=vals, tags=tags)
                existentes.discard(nome)
            else:
                self.tv.insert("", "end", iid=nome, values=vals, tags=tags)
        for sobra in existentes:
            self.tv.delete(sobra)
        for i, r in enumerate(linhas[:300]):
            self.tv.move(r["nome"], "", i)

    def escolheu(self, _e=None):
        sel = self.tv.selection()
        self.selecionado = sel[0] if sel else None
        self.grafico_app()

    # ---- graficos
    def grafico(self, cv, serie_kb, titulo, cor):
        cv.update_idletasks()
        w, h = max(cv.winfo_width(), 50), max(cv.winfo_height(), 50)
        cv.delete("all")
        cv.create_text(8, 8, anchor="nw", text=titulo, fill=FG2, font=("Segoe UI", 8))
        if len(serie_kb) < 2:
            return
        mb = [kb_para_mb(v) for v in serie_kb]
        lo, hi = min(mb), max(mb)
        if hi - lo < 1:
            hi = lo + 1
        x0, y0, x1, y1 = 8, 26, w - 8, h - 8
        pts = []
        for i, v in enumerate(mb):
            pts += [x0 + (x1 - x0) * i / (len(mb) - 1), y1 - (y1 - y0) * (v - lo) / (hi - lo)]
        cv.create_line(*pts, fill=cor, width=2)
        cv.create_text(w - 8, 8, anchor="ne", text="%.0f - %.0f MB" % (lo, hi), fill=FG2, font=("Segoe UI", 8))

    def grafico_app(self):
        nome = self.selecionado
        serie = [v for _, v in self.hist.get(nome, [])] if nome else []
        self.grafico(self.g_app, serie, ("RSS de %s (MB)" % nome) if nome else "Selecione um processo na tabela", "#ffb454")

    # ---- acoes
    def liga_desliga(self, inicial=False):
        ativa = bool(self.var_ativa.get())
        self.pausado = not ativa
        self.ck.configure(text="Medição ligada" if ativa else "Medição desligada")
        for b in (self.bt_pss, self.bt_det):
            b.configure(state="normal" if ativa else "disabled")
        if not inicial:
            self.app.config["memoria_ativa"] = ativa
            salvar_config(self.app.config)
        self.rodape.configure(text="medição ligada" if ativa else "medição desligada: nenhuma leitura e feita no aparelho", fg=FG2)

    def _mostra_texto(self, texto):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", texto)
        self.txt.configure(state="disabled")

    def mede_pss(self):
        if self.ocupado:
            return
        self.ocupado = True
        self.bt_pss.configure(state="disabled", text="Medindo (~6 s)...")

        def trabalho():
            try:
                _, out, _ = self._adb("shell", "dumpsys", "meminfo", timeout=90)
                self.q.put(("pss", parse_pss(out)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("pss", {}))
                self.q.put(("erro", "PSS: %s" % str(e)[:100]))

        threading.Thread(target=trabalho, daemon=True).start()

    def detalha(self):
        nome = self.selecionado
        if not nome:
            return messagebox.showinfo("Monitor de memória", "Selecione um processo na tabela.", parent=self.win)
        pid = self.dados.get(nome, (None,))[0]
        self.bt_det.configure(state="disabled", text="Lendo...")

        def trabalho():
            try:
                _, out, _ = self._adb("shell", "dumpsys", "meminfo", str(pid), timeout=30)
                self.q.put(("detalhe", "%s (pid %s)\n%s" % (nome, pid, parse_detalhe(out))))
            except Exception as e:  # noqa: BLE001
                self.q.put(("detalhe", "falha: %s" % e))

        threading.Thread(target=trabalho, daemon=True).start()

    def encerra(self):
        nome = self.selecionado
        if not nome:
            return messagebox.showinfo("Monitor de memória", "Selecione um processo na tabela.", parent=self.win)
        pacote = nome.split(":")[0]
        if "." not in pacote or not re.fullmatch(r"[A-Za-z0-9._]+", pacote):
            return messagebox.showwarning("Monitor de memória", "%s não parece um app (sem nome de pacote)." % nome, parent=self.win)
        if not messagebox.askyesno("Encerrar app", "Encerrar %s no aparelho %s?\n\n(am force-stop)" % (pacote, self.cap.serial), parent=self.win):
            return

        def trabalho():
            try:
                self._adb("shell", "am", "force-stop", pacote, timeout=15)
                self.q.put(("erro", "enviado force-stop para " + pacote))
            except Exception as e:  # noqa: BLE001
                self.q.put(("erro", str(e)[:100]))

        threading.Thread(target=trabalho, daemon=True).start()

    def exporta(self):
        if not self.hist:
            return messagebox.showinfo("Monitor de memória", "Ainda não há leituras.", parent=self.win)
        pasta = os.path.join(os.path.expanduser("~"), "Pictures", "Vision")
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, "memória-%s-%s.csv" % (self.cap.serial or "aparelho", datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
        with open(caminho, "w", encoding="utf-8", newline="") as f:
            f.write("horario;processo;rss_kb\n")
            for nome, serie in self.hist.items():
                for t, kb in serie:
                    f.write("%s;%s;%d\n" % (datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"), nome, kb))
            for t, kb in self.sist:
                f.write("%s;%s;%d\n" % (datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"), "[RAM usada do aparelho]", kb))
        self.rodape.configure(text="exportado: " + caminho, fg=FG2)

    def fechar(self):
        self.parar = True
        self.app.mem = None
        self.win.destroy()


RX_LS = re.compile(r"^([\-dlbcps])([rwxsStT\-]{9})[.+@]?\s+(?:\d+\s+)?(\S+)\s+(\S+)\s+(?:(\d+)\s+)?(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})(?::\d{2})?\s+(.*)$")  # tolera o ls do toolbox (sem contagem de links)
ATALHOS = [
    ("Armazenamento (/sdcard)", "/sdcard"),
    ("Download", "/sdcard/Download"),
    ("Imagens (DCIM)", "/sdcard/DCIM"),
    ("Fotos (Pictures)", "/sdcard/Pictures"),
    ("Dados dos apps (Android/data)", "/sdcard/Android/data"),
    ("Temporario (/data/local/tmp)", "/data/local/tmp"),
    ("Raiz (/)", "/"),
]
SEGUROS = ("/sdcard", "/storage", "/data/local/tmp")  # onde excluir/renomear e permitido


def parse_ls(saida):
    """Linhas de `ls -la` do toybox -> [(nome, tipo, tamanho, data, perm)]."""
    itens = []
    for l in saida.splitlines():
        m = RX_LS.match(l.strip())
        if not m:
            continue
        tp, perm, _dono, _grupo, tam, dia, hora, resto = m.groups()
        nome = resto.split(" -> ")[0].strip()
        if nome in (".", ".."):
            continue
        tipo = {"d": "dir", "l": "link", "-": "file"}.get(tp)
        if tipo is None:
            continue
        itens.append((nome, tipo, int(tam or 0), "%s %s" % (dia, hora), tp + perm))
    return itens


class GerenciadorArquivos:
    """Navegador de arquivos do aparelho: listar, baixar, enviar, abrir, criar pasta, renomear, excluir."""

    def __init__(self, app):
        self.app = app
        self.cap = app.cap
        self.q = queue.Queue()
        self.caminho = "/sdcard"
        self.hist = []
        self.itens = {}
        self.ocupado = ""
        self.parar = False
        self.ordem = ("nome", False)

        w = self.win = tk.Toplevel(app.root)
        w.title("Arquivos - %s" % (self.cap.serial or "aparelho"))
        aplica_icone(w)
        w.configure(bg=BG)
        w.geometry("900x620")
        w.minsize(700, 440)
        w.protocol("WM_DELETE_WINDOW", self.fechar)

        barra = tk.Frame(w, bg=BG)
        barra.pack(fill="x", padx=10, pady=(10, 4))
        self.bt_volta = self._bt(barra, "\u25C0", "Voltar", "Volta para a pasta anterior", self.volta, 3)
        self._bt(barra, "\u2B06", "Subir", "Vai para a pasta de cima", self.sobe, 3)
        self._bt(barra, "\u27F3", "Atualizar", "Lista a pasta de novo", lambda: self.vai(self.caminho, False), 3)
        self.var_cam = tk.StringVar(value=self.caminho)
        ent = tk.Entry(barra, textvariable=self.var_cam, bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        ent.pack(side="left", fill="x", expand=True, padx=8, ipady=4)
        ent.bind("<Return>", lambda e: self.vai(self.var_cam.get().strip() or "/", True))
        Dica(ent, "Caminho", "Digite uma pasta do aparelho e tecle Enter")
        self.cb = ttk.Combobox(barra, state="readonly", width=28, values=[a for a, _ in ATALHOS])
        self.cb.pack(side="left")
        self.cb.set("Atalhos...")
        self.cb.bind("<<ComboboxSelected>>", self.atalho)
        Dica(self.cb, "Atalhos", "Pastas comuns do aparelho")

        acoes = tk.Frame(w, bg=BG)
        acoes.pack(fill="x", padx=10, pady=4)
        self._bt(acoes, "Baixar", "Baixar para o PC", "Copia os itens marcados para uma pasta do PC (adb pull)", self.baixar)
        self._bt(acoes, "Enviar", "Enviar para o aparelho", "Escolhe arquivos do PC e coloca nesta pasta (adb push)", self.enviar)
        self._bt(acoes, "Abrir no PC", "Abrir no PC", "Baixa para a pasta temporaria e abre com o programa padrão", self.abrir)
        self._bt(acoes, "Nova pasta", "Nova pasta", "Cria uma pasta aqui", self.nova_pasta)
        self._bt(acoes, "Renomear", "Renomear", "Muda o nome do item marcado", self.renomear)
        self._bt(acoes, "Excluir", "Excluir", "Apaga os itens marcados do aparelho (pede confirmacao)", self.exclui)
        self.lb_esp = tk.Label(acoes, text="", bg=BG, fg=FG2, font=("Segoe UI", 9))
        self.lb_esp.pack(side="right")

        corpo = tk.Frame(w, bg=BG)
        corpo.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        cols = ("nome", "tam", "data", "perm")
        self.tv = ttk.Treeview(corpo, columns=cols, show="headings", selectmode="extended")
        for c, tt, lg, an in (("nome", "Nome", 460, "w"), ("tam", "Tamanho", 90, "e"), ("data", "Modificado", 130, "w"), ("perm", "Permissões", 100, "w")):
            self.tv.heading(c, text=tt, command=lambda c=c: self.ordena(c))
            self.tv.column(c, width=lg, anchor=an)
        sb = ttk.Scrollbar(corpo, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv.bind("<Double-Button-1>", self.duplo)
        self.tv.bind("<Return>", self.duplo)
        self.tv.bind("<BackSpace>", lambda e: self.sobe())
        self.tv.bind("<Delete>", lambda e: self.exclui())
        self.tv.bind("<F5>", lambda e: self.vai(self.caminho, False))

        self.rodape = tk.Label(w, text="", bg=BG, fg=FG2, anchor="w", font=("Segoe UI", 9), padx=10)
        self.rodape.pack(fill="x", pady=(4, 8))

        threading.Thread(target=self._espaco, daemon=True).start()
        self.vai(self.caminho, True)
        w.after(150, self._consome)

    def _bt(self, pai, texto, titulo, detalhe, cmd, largura=None):
        b = ttk.Button(pai, text=texto, command=cmd, width=largura) if largura else ttk.Button(pai, text=texto, command=cmd)
        b.pack(side="left", padx=(0, 6))
        Dica(b, titulo, detalhe)
        return b

    # ---- adb
    def _adb(self, *args, timeout=30):
        return rodar([self.cap.adb, "-s", self.cap.serial] + list(args), timeout=timeout)

    def _espaco(self):
        try:
            _, out, _ = self._adb("shell", "df -k /sdcard | tail -1", timeout=15)
            c = out.split()
            if len(c) >= 4 and c[1].isdigit():
                self.q.put(("espaco", "armazenamento: %s livres de %s" % (tamanho_legivel(int(c[3]) * 1024), tamanho_legivel(int(c[1]) * 1024))))
        except Exception:
            pass

    # ---- navegacao
    def vai(self, caminho, grava_hist=True):
        caminho = posixpath.normpath("/" + caminho.strip().lstrip("/")) if caminho.strip("/") else "/"  # resolve ".." antes de checar a area permitida
        if grava_hist and caminho != self.caminho:
            self.hist.append(self.caminho)
        self.caminho = caminho
        self.var_cam.set(caminho)
        self.rodape.configure(text="listando %s ..." % caminho, fg=FG2)

        def trabalho():
            try:
                _, out, err = self._adb("shell", "ls -la %s 2>&1" % q(caminho.rstrip("/") + "/"), timeout=30)
                itens = parse_ls(out)
                msg = ""
                if not itens and out.strip():
                    primeira = out.strip().splitlines()[-1]
                    if "total" not in primeira and not RX_LS.match(primeira):
                        msg = primeira
                self.q.put(("lista", caminho, itens, msg))
            except Exception as e:  # noqa: BLE001
                self.q.put(("lista", caminho, [], str(e)[:120]))

        threading.Thread(target=trabalho, daemon=True).start()

    def volta(self):
        if self.hist:
            self.vai(self.hist.pop(), False)

    def sobe(self):
        if self.caminho != "/":
            self.vai(self.caminho.rsplit("/", 1)[0] or "/", True)

    def atalho(self, _e=None):
        for nome, cam in ATALHOS:
            if nome == self.cb.get():
                self.vai(cam, True)
        self.cb.set("Atalhos...")

    def duplo(self, _e=None):
        sel = self.tv.selection()
        if not sel:
            return
        nome, tipo = self.itens[sel[0]][0], self.itens[sel[0]][1]
        if tipo in ("dir", "link"):
            self.vai(self.caminho.rstrip("/") + "/" + nome, True)
        else:
            self.abrir()

    def ordena(self, col):
        atual, desc = self.ordem
        self.ordem = (col, (not desc) if atual == col else False)
        self.mostra()

    def mostra(self):
        col, desc = self.ordem
        chave = {"nome": lambda i: i[0].lower(), "tam": lambda i: i[2], "data": lambda i: i[3], "perm": lambda i: i[4]}[col]
        itens = sorted(self.itens.values(), key=chave, reverse=desc)
        itens.sort(key=lambda i: 0 if i[1] in ("dir", "link") else 1)  # pastas primeiro
        self.tv.delete(*self.tv.get_children())
        self.ordem_ids = {}
        for n, it in enumerate(itens):
            nome, tipo, tam, data, perm = it
            marca = "\U0001F4C1 " if tipo in ("dir", "link") else "\U0001F4C4 "
            iid = "i%d" % n
            self.ordem_ids[iid] = it
            self.tv.insert("", "end", iid=iid, values=(marca + nome, "" if tipo != "file" else tamanho_legivel(tam), data, perm))
        self.itens = dict(self.ordem_ids)

    # ---- selecao
    def marcados(self):
        return [self.itens[i] for i in self.tv.selection() if i in self.itens]

    def _remoto(self, nome):
        return self.caminho.rstrip("/") + "/" + nome

    # ---- operacoes (em segundo plano, resultado pela fila)
    def tarefa(self, texto, comandos, depois=None):
        if self.ocupado:
            return messagebox.showinfo("Arquivos", "Aguarde: %s" % self.ocupado, parent=self.win)
        self.ocupado = texto
        self.rodape.configure(text=texto, fg=ACENTO)

        def trabalho():
            falhas = []
            for cmd in comandos:
                try:
                    rc, out, err = self._adb(*cmd, timeout=1800)
                    if rc != 0:
                        falhas.append((out + " " + err).strip().splitlines()[-1] if (out + err).strip() else "falhou")
                except Exception as e:  # noqa: BLE001
                    falhas.append(str(e)[:100])
            self.q.put(("fim", texto, falhas, depois))

        threading.Thread(target=trabalho, daemon=True).start()

    def baixar(self):
        sel = self.marcados()
        if not sel:
            return messagebox.showinfo("Arquivos", "Marque o que deseja baixar.", parent=self.win)
        destino = filedialog.askdirectory(title="Salvar no PC em...", initialdir=os.path.join(os.path.expanduser("~"), "Downloads"), parent=self.win)
        if not destino:
            return
        cmds = [["pull", self._remoto(i[0]), destino] for i in sel]
        self.tarefa("baixando %d item(ns) para %s ..." % (len(sel), destino), cmds, lambda: os.startfile(destino) if os.name == "nt" else None)

    def enviar(self):
        arqs = filedialog.askopenfilenames(title="Escolha os arquivos para enviar", parent=self.win)
        if not arqs:
            return
        cmds = [["push", a, self.caminho.rstrip("/") + "/"] for a in arqs]
        self.tarefa("enviando %d arquivo(s) para %s ..." % (len(arqs), self.caminho), cmds, lambda: self.vai(self.caminho, False))

    def abrir(self):
        sel = [i for i in self.marcados() if i[1] == "file"]
        if not sel:
            return messagebox.showinfo("Arquivos", "Marque um arquivo para abrir.", parent=self.win)
        pasta = tempfile.mkdtemp(prefix="vision-")
        alvo = os.path.join(pasta, sel[0][0])
        self.tarefa("baixando %s para abrir ..." % sel[0][0], [["pull", self._remoto(sel[0][0]), pasta]], lambda: os.startfile(alvo) if os.name == "nt" and os.path.exists(alvo) else None)

    def _protegido(self, caminho):
        return not any(caminho == s or caminho.startswith(s + "/") for s in SEGUROS)

    def nova_pasta(self):
        nome = simpledialog.askstring("Nova pasta", "Nome da pasta em %s:" % self.caminho, parent=self.win)
        if not nome or "/" in nome:
            return
        dest = self._remoto(nome.strip())
        if self._protegido(dest):
            return messagebox.showwarning("Arquivos", "Alteracoes so sao permitidas em /sdcard, /storage e /data/local/tmp.", parent=self.win)
        self.tarefa("criando pasta ...", [["shell", "mkdir -p " + q(dest)]], lambda: self.vai(self.caminho, False))

    def renomear(self):
        sel = self.marcados()
        if len(sel) != 1:
            return messagebox.showinfo("Arquivos", "Marque um único item para renomear.", parent=self.win)
        antigo = self._remoto(sel[0][0])
        novo_nome = simpledialog.askstring("Renomear", "Novo nome:", initialvalue=sel[0][0], parent=self.win)
        if not novo_nome or "/" in novo_nome or novo_nome == sel[0][0]:
            return
        if self._protegido(antigo):
            return messagebox.showwarning("Arquivos", "Alteracoes so sao permitidas em /sdcard, /storage e /data/local/tmp.", parent=self.win)
        self.tarefa("renomeando ...", [["shell", "mv %s %s" % (q(antigo), q(self._remoto(novo_nome.strip())))]], lambda: self.vai(self.caminho, False))

    def exclui(self):
        sel = self.marcados()
        if not sel:
            return
        alvos = [self._remoto(i[0]) for i in sel]
        if any(self._protegido(a) for a in alvos):
            return messagebox.showwarning("Arquivos", "Exclusão so e permitida em /sdcard, /storage e /data/local/tmp.", parent=self.win)
        lista = "\n".join(a for a in alvos[:8]) + ("\n... (+%d)" % (len(alvos) - 8) if len(alvos) > 8 else "")
        if not messagebox.askyesno("Excluir", "Apagar do aparelho %s:\n\n%s\n\nEsta acao não pode ser desfeita." % (self.cap.serial, lista), icon="warning", parent=self.win):
            return
        self.tarefa("excluindo %d item(ns) ..." % len(alvos), [["shell", "rm -rf " + q(a)] for a in alvos], lambda: self.vai(self.caminho, False))

    # ---- fila -> UI
    def _consome(self):
        if self.parar:
            return
        try:
            while not self.q.empty():
                m = self.q.get_nowait()
                if m[0] == "lista":
                    _, cam, itens, msg = m
                    if cam != self.caminho:
                        continue
                    self.itens = {"x%d" % n: it for n, it in enumerate(itens)}
                    self.mostra()
                    if msg:
                        self.rodape.configure(text="%s: %s" % (cam, msg), fg=PERIGO)
                    else:
                        pastas = sum(1 for i in itens if i[1] != "file")
                        self.rodape.configure(text="%s  -  %d pasta(s), %d arquivo(s)" % (cam, pastas, len(itens) - pastas), fg=FG2)
                elif m[0] == "espaco":
                    self.lb_esp.configure(text=m[1])
                elif m[0] == "fim":
                    _, texto, falhas, depois = m
                    self.ocupado = ""
                    if falhas:
                        self.rodape.configure(text="falhou: %s" % falhas[0][:160], fg=PERIGO)
                        messagebox.showerror("Arquivos", "Houve falha:\n\n%s" % "\n".join(falhas[:6]), parent=self.win)
                    else:
                        self.rodape.configure(text="concluido: %s" % texto.replace(" ...", ""), fg=FG2)
                        if depois:
                            depois()
        except Exception as e:  # noqa: BLE001
            self.rodape.configure(text="erro: %s" % e, fg=PERIGO)
        self.win.after(150, self._consome)

    def fechar(self):
        self.parar = True
        self.app.arq = None
        self.win.destroy()


# ================================================================= Exportar logcat
JANELAS_LOG = (2, 5, 10)  # minutos oferecidos no menu
RX_HORA_LOG = re.compile(r"^(\d\d)-(\d\d)\s+(\d\d):(\d\d):(\d\d)\.(\d+)")


def pasta_logcat():
    base = os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.isdir(base):
        base = os.path.expanduser("~")
    pasta = os.path.join(base, "Vision", "Logcat")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _data_linha(m, ref):
    """Data da linha. O logcat não traz o ano: usa o do relogio do aparelho e recua um ano se cair no futuro."""
    mes, dia, h, mi, s = (int(m.group(k)) for k in range(1, 6))
    ms = int(m.group(6).ljust(3, "0")[:3])
    try:
        d = datetime.datetime(ref.year, mes, dia, h, mi, s, ms * 1000)
        if d > ref + datetime.timedelta(days=1):
            d = d.replace(year=ref.year - 1)
    except ValueError:
        return None
    return d


def filtra_janela(texto, minutos, agora=None):
    """Mantem so as linhas dos últimos `minutos` minutos.
    `agora` e o relogio do aparelho; sem ele, vale a linha mais nova do proprio log.
    Devolve (linhas, primeira_hora, ultima_hora, agora)."""
    ref = agora or datetime.datetime.now()
    marcadas = []
    for ln in texto.splitlines():
        m = RX_HORA_LOG.match(ln)
        marcadas.append((_data_linha(m, ref) if m else None, ln))
    datas = [d for d, _ in marcadas if d]
    if not datas:
        return [], None, None, agora
    if agora is None:
        agora = max(datas)
    corte = agora - datetime.timedelta(minutes=minutos)
    saida, manter = [], False
    for d, ln in marcadas:
        if d is not None:
            manter = d >= corte
        if manter:  # linha sem hora (continuacao) acompanha a anterior
            saida.append(ln)
    return saida, min(datas), max(datas), agora


def exportar_logcat(adb, serial, minutos, pasta=None):
    """Salva o logcat dos últimos `minutos` minutos. Devolve (caminho, total_de_linhas, aviso).
    Levanta RuntimeError com mensagem legivel."""
    agora = None
    try:  # o logcat usa a hora do aparelho, nao a do PC
        _, d, _ = rodar([adb, "-s", serial, "shell", "date '+%Y-%m-%d %H:%M:%S'"], timeout=10)
        agora = datetime.datetime.strptime(d.strip().splitlines()[-1].strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        agora = None
    try:
        rc, out, err = rodar([adb, "-s", serial, "logcat", "-d", "-v", "threadtime"], timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError("o aparelho demorou demais para entregar o log")
    if not any(RX_HORA_LOG.match(l) for l in out.splitlines()):
        if rc != 0:
            raise RuntimeError("o adb recusou o logcat: %s" % ((err or out).strip()[:200] or "sem detalhes"))
        raise RuntimeError(
            "o logcat do aparelho veio vazio. Alguns firmwares de usuario restringem o log ao shell; "
            "nesse caso não há o que exportar."
        )
    linhas, primeira, ultima, agora = filtra_janela(out, minutos, agora)
    if not linhas:
        raise RuntimeError(
            "nenhuma linha nos últimos %d min (o log do aparelho vai de %s a %s)"
            % (minutos, primeira.strftime("%d/%m %H:%M:%S"), ultima.strftime("%d/%m %H:%M:%S"))
        )
    corte = agora - datetime.timedelta(minutes=minutos)
    aviso = ""
    if primeira - corte > datetime.timedelta(seconds=30):
        aviso = "o buffer do aparelho so guarda desde %s (cerca de %.1f min), menos que os %d pedidos" % (
            primeira.strftime("%H:%M:%S"), (agora - primeira).total_seconds() / 60.0, minutos)
    pasta = pasta or pasta_logcat()
    nome = "logcat-%s-%dmin-%s.txt" % (re.sub(r"[^A-Za-z0-9._-]", "_", serial), minutos, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    caminho = os.path.join(pasta, nome)
    cab = [
        "# Vision - logcat dos últimos %d min" % minutos,
        "# aparelho: %s" % serial,
        "# relogio do aparelho: %s" % (agora.strftime("%Y-%m-%d %H:%M:%S")),
        "# linhas: %d" % len(linhas),
    ]
    if aviso:
        cab.append("# atenção: " + aviso)
    with open(caminho, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(cab + [""] + linhas) + "\n")
    return caminho, len(linhas), aviso


RX_IP = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(:\d{1,5})?$")


def motivo_sem_aparelho(aparelhos):
    """Texto do rodape quando há aparelho na lista, mas nenhum utilizavel (unauthorized, offline...)."""
    msgs = []
    for a in aparelhos:
        if a["estado"] == "unauthorized":
            msgs.append("%s n\u00e3o autorizado: aceite \u201cPermitir depura\u00e7\u00e3o\u201d na tela do aparelho (marque \u201cSempre permitir\u201d)" % a["serial"])
        elif a["estado"] == "offline":
            msgs.append("%s est\u00e1 offline: reconecte o cabo ou conecte pelo Wi-Fi" % a["serial"])
        elif a["estado"] != "device":
            msgs.append("%s est\u00e1 %s" % (a["serial"], ESTADOS.get(a["estado"], a["estado"])))
    return "; ".join(msgs)


# ================================================================= Painel do app e do aparelho
PERMISSOES = [
    "android.permission.CAMERA", "android.permission.ACCESS_FINE_LOCATION", "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.READ_EXTERNAL_STORAGE", "android.permission.WRITE_EXTERNAL_STORAGE", "android.permission.READ_PHONE_STATE",
    "android.permission.RECORD_AUDIO", "android.permission.POST_NOTIFICATIONS", "android.permission.BLUETOOTH_CONNECT",
    "android.permission.BLUETOOTH_SCAN", "android.permission.NEARBY_WIFI_DEVICES",
]
# preparo para automacao: (rotulo, namespace, chave, valor desejado)
PREPARO = [
    ("Animação de janelas", "global", "window_animation_scale", "0"),
    ("Animação de transição", "global", "transition_animation_scale", "0"),
    ("Duração de animadores", "global", "animator_duration_scale", "0"),
    ("Tela sempre ligada (carregando)", "global", "stay_on_while_plugged_in", "7"),
    ("Tempo para apagar a tela", "system", "screen_off_timeout", "1800000"),
    ("Rotação automatica", "system", "accelerometer_rotation", "0"),
    ("Orientação fixa em retrato", "system", "user_rotation", "0"),
]


def valor_igual(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


class PainelApp:
    """Informações do aparelho e de um app escolhido, ações rapidas e preparo para automação."""

    def __init__(self, app):
        self.app = app
        self.cap = app.cap
        self.q = queue.Queue()
        self.parar = False
        favs = favoritos(app.config)
        self.pacote = app.config.get("pacote_painel") or (favs[0] if favs else "")
        self.valores = {}      # campo -> label
        self.estado = {}       # chave de PREPARO -> valor atual
        self.instalados = []

        w = self.win = tk.Toplevel(app.root)
        w.title("App e aparelho - %s" % (self.cap.serial or "aparelho"))
        aplica_icone(w)
        w.configure(bg=BG)
        w.geometry("860x720")
        w.minsize(760, 600)
        w.protocol("WM_DELETE_WINDOW", self.fechar)

        topo = tk.Frame(w, bg=BG)
        topo.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(topo, text="Pacote do app:", bg=BG, fg=FG).pack(side="left")
        self.cb = ttk.Combobox(topo, state="readonly", width=34, values=favoritos(app.config))
        self.cb.set(self.pacote)
        self.cb.pack(side="left", padx=8)
        self.cb.bind("<<ComboboxSelected>>", self.escolheu)
        Dica(self.cb, "Pacote do app", "Apps instalados pelo usuario; os favoritos aparecem primeiro (marcados com *)")
        self.bt_fav = ttk.Button(topo, text="\u2606 Favorito", command=self.alterna_favorito, width=11)
        self.bt_fav.pack(side="left", padx=(0, 8))
        Dica(self.bt_fav, "Favorito", "Fixa este app no topo da lista (aqui, no monitor de memória e no Desinstalar)")
        self._marca_favorito()
        ttk.Button(topo, text="Atualizar", command=self.atualiza).pack(side="left")

        cols = tk.Frame(w, bg=BG)
        cols.pack(fill="x", padx=14, pady=6)
        esq = self._cartao(cols, "Aplicativo")
        dir_ = self._cartao(cols, "Aparelho")
        for nome in ("Instalado", "Versão", "Código da versão", "Primeira instalação", "Última atualização", "Instalado por", "Em execução (PID)"):
            self._campo(esq, nome)
        for nome in ("Modelo", "Android", "Tela", "Bateria", "IP Wi-Fi", "ANDROID_ID (sistema)", "Serial de hardware", "Hora do aparelho"):
            self._campo(dir_, nome)
        esq.master.pack(side="left", fill="both", expand=True, padx=(0, 6))
        dir_.master.pack(side="left", fill="both", expand=True, padx=(6, 0))
        linha = tk.Frame(dir_.master, bg=BG)
        linha.pack(fill="x", pady=(0, 6), padx=10)
        b = ttk.Button(linha, text="Copiar ANDROID_ID", command=lambda: self.copia("ANDROID_ID (sistema)"))
        b.pack(side="left")
        Dica(b, "Copiar ANDROID_ID", "Valor lido pelo shell. No Android 8+ cada app recebe um ANDROID_ID proprio, entao o ID que o app exibe pode ser outro: confira na tela do app")
        ttk.Button(linha, text="Copiar serial", command=lambda: self.copia("Serial de hardware")).pack(side="left", padx=6)

        acoes = ttk.LabelFrame(w, text=" Ações no app ")
        acoes.pack(fill="x", padx=14, pady=6)
        for txt, tit, det, cmd in (
            ("Abrir", "Abrir o app", "Inicia o app (monkey)", self.abrir),
            ("Forçar parada", "Forçar parada", "am force-stop", self.parar_app),
            ("Reiniciar", "Reiniciar o app", "Para e abre de novo", self.reiniciar),
            ("Limpar dados", "Limpar dados", "pm clear: apaga login, configuracoes e arquivos do app (pede confirmacao)", self.limpar),
            ("Conceder permissões", "Conceder permissões", "Concede camera, localização, armazenamento etc. quando o app pede", self.conceder),
        ):
            b = ttk.Button(acoes, text=txt, command=cmd)
            b.pack(side="left", padx=6, pady=8)
            Dica(b, tit, det)

        prep = ttk.LabelFrame(w, text=" Preparar o aparelho para a automação ")
        prep.pack(fill="both", expand=True, padx=14, pady=6)
        self.lista = tk.Frame(prep, bg=BG)
        self.lista.pack(fill="x", padx=10, pady=(8, 4))
        self.marcas = {}
        for rot, ns, chave, alvo in PREPARO:
            fr = tk.Frame(self.lista, bg=BG)
            fr.pack(fill="x")
            tk.Label(fr, text=rot, bg=BG, fg=FG, width=34, anchor="w").pack(side="left")
            lb = tk.Label(fr, text="...", bg=BG, fg=FG2, anchor="w")
            lb.pack(side="left")
            self.marcas[chave] = lb
        bt = tk.Frame(prep, bg=BG)
        bt.pack(fill="x", padx=10, pady=8)
        b1 = ttk.Button(bt, text="Preparar para automação", command=self.prepara)
        b1.pack(side="left")
        Dica(b1, "Preparar para automação", "Desliga animações, mantem a tela ligada e trava a rotação. Guarda os valores antigos para restaurar")
        b2 = ttk.Button(bt, text="Restaurar valores anteriores", command=self.restaura)
        b2.pack(side="left", padx=8)
        Dica(b2, "Restaurar", "Volta ao que o aparelho tinha antes do preparo")
        self.rodape = tk.Label(w, text="", bg=BG, fg=FG2, anchor="w", font=("Segoe UI", 9), padx=14)
        self.rodape.pack(fill="x", pady=(2, 10))

        self.atualiza()
        w.after(150, self._consome)

    # ---- widgets
    def _cartao(self, pai, titulo):
        caixa = tk.Frame(pai, bg=BG)
        quadro = ttk.LabelFrame(caixa, text=" %s " % titulo)
        quadro.pack(fill="x", pady=(0, 6))
        return quadro

    def _campo(self, quadro, nome):
        fr = tk.Frame(quadro, bg=BG)
        fr.pack(fill="x", padx=10, pady=1)
        tk.Label(fr, text=nome, bg=BG, fg=FG2, width=22, anchor="w", font=("Segoe UI", 9)).pack(side="left")
        lb = tk.Label(fr, text="-", bg=BG, fg=FG, anchor="w", font=("Segoe UI", 9, "bold"))
        lb.pack(side="left")
        self.valores[nome] = lb

    # ---- coleta
    def _adb(self, *args, timeout=30):
        return rodar([self.cap.adb, "-s", self.cap.serial] + list(args), timeout=timeout)

    def escolheu(self, _e=None):
        pk = self.cb.get().lstrip("* ").strip()
        if not re.fullmatch(r"[A-Za-z0-9._]+", pk):
            return
        self.pacote = pk
        self.cb.set(pk)
        self.app.config["pacote_painel"] = pk
        salvar_config(self.app.config)
        self._marca_favorito()
        self.atualiza()

    def _marca_favorito(self):
        fav = self.pacote in favoritos(self.app.config)
        self.bt_fav.configure(text=("\u2605 Favorito" if fav else "\u2606 Favorito"))

    def alterna_favorito(self):
        if not self.pacote:
            return
        favs = favoritos(self.app.config)
        if self.pacote in favs:
            favs.remove(self.pacote)
        else:
            favs.insert(0, self.pacote)
        self.app.config["favoritos"] = favs
        salvar_config(self.app.config)
        self._marca_favorito()
        self._lista_pacotes()

    def _lista_pacotes(self):
        favs = favoritos(self.app.config)
        resto = sorted(x for x in self.instalados if x not in favs and re.fullmatch(r"[A-Za-z0-9._]+", x))
        self.cb.configure(values=["* " + x for x in favs] + resto)

    def atualiza(self):
        self.rodape.configure(text="lendo o aparelho ...", fg=ACENTO)
        pk = self.pacote or "android"
        chaves = " ".join("%s:%s" % (ns, ch) for _, ns, ch, _ in PREPARO)

        def trabalho():
            try:
                script = (
                    "echo '##model'; getprop ro.product.manufacturer; getprop ro.product.model; "
                    "echo '##android'; getprop ro.build.version.release; getprop ro.build.version.sdk; "
                    "echo '##serial'; getprop ro.serialno; getprop ro.boot.serialno; "
                    "echo '##androidid'; settings get secure android_id; "
                    "echo '##wm'; wm size; wm density; "
                    "echo '##battery'; dumpsys battery | grep -E 'level|temperature|status'; "
                    "echo '##ip'; ip -f inet addr show wlan0 2>/dev/null | grep inet; "
                    "echo '##date'; date '+%%Y-%%m-%%d %%H:%%M:%%S'; getprop persist.sys.timezone; "
                    "echo '##pkgs'; pm list packages -3; "
                    "echo '##pkg'; dumpsys package %s | grep -E 'versionName|versionCode|firstInstallTime|lastUpdateTime|installerPackageName'; echo '##pid'; pidof %s; "
                    "echo '##cfg'; for k in %s; do ns=${k%%%%:*}; ch=${k#*:}; echo $ch=$(settings get $ns $ch); done"
                ) % (pk, pk, chaves)
                _, out, err = self._adb("shell", script, timeout=40)
                self.q.put(("info", pk, out))
            except Exception as e:  # noqa: BLE001
                self.q.put(("erro", str(e)[:160]))

        threading.Thread(target=trabalho, daemon=True).start()

    def _aplica_info(self, pk, out):
        secoes, atual = {}, None
        for l in out.splitlines():
            l = l.rstrip()
            if l.startswith("##"):
                atual = l[2:]
                secoes[atual] = []
            elif atual:
                secoes[atual].append(l)
        s = lambda k: [x for x in secoes.get(k, []) if x.strip()]
        v = self.valores
        m = s("model")
        v["Modelo"].configure(text=" ".join(m) or "-")
        a = s("android")
        v["Android"].configure(text=("%s (API %s)" % (a[0], a[1])) if len(a) > 1 else "-")
        v["Serial de hardware"].configure(text=(s("serial") or ["-"])[0])
        aid = (s("androidid") or ["-"])[0].strip().upper()
        v["ANDROID_ID (sistema)"].configure(text=aid)
        wm = " ".join(x.replace("Physical size:", "").replace("Override size:", "-> ").replace("Physical density:", "@").strip() for x in s("wm"))
        v["Tela"].configure(text=wm or "-")
        bat = {x.split(":")[0].strip(): x.split(":", 1)[1].strip() for x in s("battery") if ":" in x}
        temp = bat.get("temperature")
        v["Bateria"].configure(text=("%s%%%s" % (bat.get("level", "?"), (", %.1f C" % (int(temp) / 10.0)) if temp and temp.lstrip("-").isdigit() else "")) if bat else "-")
        ip = re.search(r"inet\s+([\d.]+)", " ".join(s("ip")))
        v["IP Wi-Fi"].configure(text=ip.group(1) if ip else "sem Wi-Fi")
        d = s("date")
        v["Hora do aparelho"].configure(text="%s  %s" % (d[0] if d else "-", d[1] if len(d) > 1 else ""))
        pacs = [x.split(":", 1)[1] for x in s("pkgs") if x.startswith("package:")]
        self.instalados = pacs
        self._lista_pacotes()
        if not self.pacote and pacs:  # primeira vez: comeca pelo primeiro app instalado
            self.pacote = sorted(pacs)[0]
            self.cb.set(self.pacote)
            self._marca_favorito()
            return self.atualiza()
        info = {}
        for x in s("pkg"):
            if "=" in x:
                ch, val = x.strip().split("=", 1)
                info[ch.strip()] = val.strip()
        instalado = pk in pacs or "versionName" in info
        v["Instalado"].configure(text=("sim" if instalado else "não"), fg=FG if instalado else PERIGO)
        v["Versão"].configure(text=info.get("versionName", "-"))
        cod = info.get("versionCode", "-")
        v["Código da versão"].configure(text=cod.split()[0] if cod != "-" else "-")
        v["Primeira instalação"].configure(text=info.get("firstInstallTime", "-"))
        v["Última atualização"].configure(text=info.get("lastUpdateTime", "-"))
        v["Instalado por"].configure(text=info.get("installerPackageName", "-"))
        pid = (s("pid") or [""])[0].strip()
        v["Em execução (PID)"].configure(text=pid or "parado")
        cfg = {}
        for x in s("cfg"):
            if "=" in x:
                ch, val = x.split("=", 1)
                cfg[ch.strip()] = val.strip()
        self.estado = cfg
        for rot, ns, chave, alvo in PREPARO:
            atualv = cfg.get(chave, "null")
            ok = valor_igual(atualv, alvo) or (chave == "screen_off_timeout" and atualv.isdigit() and int(atualv) >= int(alvo))
            self.marcas[chave].configure(text="%s   (atual: %s, ideal: %s)" % ("OK" if ok else "ajustar", atualv, alvo), fg=visual.VERDE if ok else visual.AMBAR)
        self.rodape.configure(text="atualizado %s" % time.strftime("%H:%M:%S"), fg=FG2)

    def _consome(self):
        if self.parar:
            return
        try:
            while not self.q.empty():
                m = self.q.get_nowait()
                if m[0] == "info":
                    self._aplica_info(m[1], m[2])
                elif m[0] == "erro":
                    self.rodape.configure(text=m[1], fg=PERIGO)
                elif m[0] == "msg":
                    self.rodape.configure(text=m[1], fg=FG2)
                    if len(m) > 2 and m[2]:
                        self.atualiza()
        except Exception as e:  # noqa: BLE001
            self.rodape.configure(text="erro: %s" % e, fg=PERIGO)
        self.win.after(150, self._consome)

    # ---- acoes
    def _roda(self, texto, comandos, depois_atualiza=True):
        self.rodape.configure(text=texto + " ...", fg=ACENTO)

        def trabalho():
            falhas = []
            for cmd in comandos:
                try:
                    rc, out, err = self._adb("shell", cmd, timeout=60)
                    txt = (out + " " + err)
                    if rc != 0 or "Exception" in txt or "No activities found" in txt or ("Error" in txt and "Success" not in txt):
                        falhas.append(txt.strip().splitlines()[-1][:100] if txt.strip() else "falhou")
                except Exception as e:  # noqa: BLE001
                    falhas.append(str(e)[:100])
            self.q.put(("msg", ("%s: %s" % (texto, falhas[0])) if falhas else ("concluido: " + texto), depois_atualiza))

        threading.Thread(target=trabalho, daemon=True).start()

    def abrir(self):
        if not self.pacote:
            return messagebox.showinfo("App e aparelho", "Escolha um app na lista.", parent=self.win)
        self._roda("abrindo %s" % self.pacote, ["monkey -p %s -c android.intent.category.LAUNCHER 1" % self.pacote])

    def parar_app(self):
        if not self.pacote:
            return messagebox.showinfo("App e aparelho", "Escolha um app na lista.", parent=self.win)
        self._roda("forcando parada de %s" % self.pacote, ["am force-stop %s" % self.pacote])

    def reiniciar(self):
        if not self.pacote:
            return messagebox.showinfo("App e aparelho", "Escolha um app na lista.", parent=self.win)
        self._roda("reiniciando %s" % self.pacote, ["am force-stop %s" % self.pacote, "sleep 1", "monkey -p %s -c android.intent.category.LAUNCHER 1" % self.pacote])

    def limpar(self):
        if not self.pacote:
            return messagebox.showinfo("App e aparelho", "Escolha um app na lista.", parent=self.win)
        if not messagebox.askyesno("Limpar dados", "Apagar TODOS os dados de %s no aparelho %s?\n\nLogin, configuracoes e arquivos do app serao perdidos." % (self.pacote, self.cap.serial), icon="warning", parent=self.win):
            return
        self._roda("limpando dados de %s" % self.pacote, ["pm clear %s" % self.pacote])

    def conceder(self):
        if not self.pacote:
            return messagebox.showinfo("App e aparelho", "Escolha um app na lista.", parent=self.win)
        self._roda("concedendo permissões a %s" % self.pacote, ["pm grant %s %s 2>/dev/null; true" % (self.pacote, p) for p in PERMISSOES])

    def copia(self, campo):
        txt = self.valores[campo].cget("text")
        if txt and txt != "-":
            self.win.clipboard_clear()
            self.win.clipboard_append(txt)
            self.rodape.configure(text="copiado: %s" % txt, fg=FG2)

    def _arq_original(self):
        return os.path.join(pasta_dados(), "preparo-%s.json" % (self.cap.serial or "aparelho"))

    def prepara(self):
        mudancas = [(rot, ns, ch, self.estado.get(ch, "null"), alvo) for rot, ns, ch, alvo in PREPARO if not valor_igual(self.estado.get(ch, "null"), alvo)]
        if not mudancas:
            return messagebox.showinfo("Preparar", "O aparelho já esta preparado.", parent=self.win)
        lista = "\n".join("- %s: %s -> %s" % (rot, atual, alvo) for rot, _ns, _ch, atual, alvo in mudancas)
        if not messagebox.askyesno("Preparar para automação", "Alterar no aparelho %s:\n\n%s\n\nOs valores atuais ficam guardados para restaurar." % (self.cap.serial, lista), parent=self.win):
            return
        try:
            arq = self._arq_original()
            antigos = {}
            if os.path.exists(arq):
                with open(arq, encoding="utf-8") as f:
                    antigos = json.load(f)  # nao sobrescreve o original se ja preparou antes
            for _rot, ns, ch, atual, _alvo in mudancas:
                antigos.setdefault("%s:%s" % (ns, ch), atual)
            os.makedirs(os.path.dirname(arq), exist_ok=True)
            with open(arq, "w", encoding="utf-8") as f:
                json.dump(antigos, f)
        except Exception as e:  # noqa: BLE001
            return messagebox.showerror("Preparar", "Não consegui guardar os valores originais: %s" % e, parent=self.win)
        self._roda("preparando o aparelho", ["settings put %s %s %s" % (ns, ch, alvo) for _rot, ns, ch, _atual, alvo in mudancas])

    def restaura(self):
        arq = self._arq_original()
        if not os.path.exists(arq):
            return messagebox.showinfo("Restaurar", "Não há valores anteriores guardados para este aparelho.", parent=self.win)
        with open(arq, encoding="utf-8") as f:
            antigos = json.load(f)
        if not messagebox.askyesno("Restaurar", "Voltar %d configuração(oes) aos valores anteriores?" % len(antigos), parent=self.win):
            return
        cmds = []
        for chave, val in antigos.items():
            ns, ch = chave.split(":", 1)
            cmds.append("settings delete %s %s" % (ns, ch) if val in ("null", "") else "settings put %s %s %s" % (ns, ch, val))
        self._roda("restaurando configuracoes", cmds)
        try:
            os.remove(arq)
        except OSError:
            pass

    def fechar(self):
        self.parar = True
        self.app.painel = None
        self.win.destroy()


# ----------------------------------------------------------------- preferencias
def pasta_dados():
    """%APPDATA%\\Vision. Na primeira abertura, traz a configuração da pasta antiga (EspelhaTela):
    porta do adb, favoritos, aparelhos de rede e os valores guardados pelo "Preparar para automação"."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    nova = os.path.join(base, "Vision")
    antiga = os.path.join(base, "EspelhaTela")
    if not os.path.isdir(nova) and os.path.isdir(antiga):
        try:
            shutil.copytree(antiga, nova)
        except Exception:  # noqa: BLE001  sem a copia o programa so comeca com a configuracao padrao
            pass
    return nova


def _arq_config():
    return os.path.join(pasta_dados(), "config.json")


def carregar_config():
    try:
        with open(_arq_config(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_config(cfg):
    try:
        os.makedirs(os.path.dirname(_arq_config()), exist_ok=True)
        with open(_arq_config(), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass


# ------------------------------------------------------------------------- UI
BG = "#1c1c1e"      # fundo da janela
BG2 = "#2a2a2d"     # botoes
HOVER = "#3a3a3f"
FG = "#e6e6e6"
FG2 = "#8e8e93"
ACENTO = "#7c4dff"  # toggles ligados
PERIGO = "#e5484d"


def aplica_tema(cfg):
    """Tema e cor de destaque escolhidos em Aparencia: valem para todas as janelas (antes de monta-las)."""
    global BG, BG2, HOVER, FG, FG2, ACENTO, PERIGO
    tema = visual.aplica_tema(cfg.get("tema", "escuro"), cfg.get("destaque", "roxo"))
    BG, BG2, HOVER, FG, FG2 = visual.BG, visual.BG2, visual.HOVER, visual.FG, visual.FG2
    ACENTO, PERIGO = visual.ACENTO, visual.PERIGO
    return tema


def favoritos(cfg):
    """Pacotes que o usuario marcou como favoritos no painel do app (guardados no config.json)."""
    return [p for p in (cfg.get("favoritos") or []) if isinstance(p, str) and re.fullmatch(r"[A-Za-z0-9._]+", p)]


def resumo_texto(txt, limite=40):
    """Texto de uma linha, cortado, para os avisos de copiar e colar."""
    t = " ".join(txt.split())
    return t if len(t) <= limite else t[: limite - 3] + "..."


CHAVES = {  # teclas de navegacao que o Android entende
    "BackSpace": "67", "Return": "66", "Tab": "61", "Escape": "111",
    "Up": "19", "Down": "20", "Left": "21", "Right": "22", "Delete": "112",
}


class App:
    def __init__(self, root, cap, versao, aviso):
        self.root, self.cap, self.versao = root, cap, versao
        self.config = carregar_config()
        self.visto = -1
        self.pausado = False
        self.cheia = False
        self.foto = None
        self.exibido = (0, 0)  # tamanho da imagem na tela, para mapear o clique
        self.janela = []
        self.msg = ("", 0.0)
        self.dica_txt = ""
        self.dica_ate = 0.0
        self.arq = None  # janela do gerenciador de arquivos
        self.painel = None  # janela do painel do app
        self.toque = None
        self.fila = queue.Queue()
        self.inj = Injetor(cap.adb)
        self.via_inj = False
        self.ult_mov = 0.0
        self.fps_hist = []
        self.resultados = queue.Queue()  # respostas das tarefas longas (instalar/desinstalar)
        self.mem = None  # janela do monitor de memoria
        self.ocupado = ""
        self.adb_porta = adb_servidor.porta_do_ambiente()
        self.sel_on = False  # seletor de identificador ligado
        self.sel_nos = None  # arvore da ultima leitura da tela
        self.sel_lendo = False
        self.sel_hover = None
        self.sel_fixo = None
        threading.Thread(target=self._envia_comandos, daemon=True).start()

        root.title("Vision")
        aplica_icone(root)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        h = int(sh * 0.84)
        root.geometry("%dx%d+%d+%d" % (int(h * 0.56) + 200, h, int(sw * 0.08), int(sh * 0.04)))
        root.minsize(340, 420)
        root.configure(bg=BG)
        visual.estilo_ttk(root)  # botoes, campos, tabelas e molduras no tema escolhido

        # ---- barra lateral: secoes, botoes com contorno e icones do Windows (rola se a tela for baixa)
        larg = 172
        lado = self.lado = visual.Rolavel(root, larg)
        lado.pack(side="left", fill="y", padx=(8, 0), pady=8)
        lado.pack_propagate(False)
        col = lado.dentro
        visual.titulo_secao(col, "Tela")
        self.bt_pausa, b_cap, b_cheia = visual.linha_de_icones(col, [
            ("pausar", self.alterna_pausa), ("captura", self.salva), ("tela_cheia", self.tela_cheia)], larg)
        self._dica(self.bt_pausa, "Pausar ou retomar|Congela a imagem do aparelho")
        self._dica(b_cap, "Salvar captura|Grava a tela em PNG na pasta Imagens\\Vision (Ctrl+S)")
        self._dica(b_cheia, "Tela cheia|Liga e desliga a tela cheia (F11)")
        visual.titulo_secao(col, "Aparelho")
        for b, d in zip(visual.linha_de_icones(col, [
                ("voltar", lambda: self.tecla("4")), ("inicio", lambda: self.tecla("3")), ("recentes", lambda: self.tecla("187"))], larg),
                ("Voltar|Tecla Voltar do Android", "In\u00edcio|Tecla In\u00edcio do Android", "Apps recentes|Mostra os apps abertos")):
            self._dica(b, d)
        for b, d in zip(visual.linha_de_icones(col, [
                ("volume_menos", lambda: self.tecla("25")), ("volume_mais", lambda: self.tecla("24")), ("energia", lambda: self.tecla("26"))], larg),
                ("Volume \u2212|Diminui o volume", "Volume +|Aumenta o volume", "Tela|Liga ou desliga a tela do aparelho")):
            self._dica(b, d)
        visual.titulo_secao(col, "Ferramentas")
        self.bt_sel = self._ferramenta(col, "seletor", "Seletor", "Seletor|Clique num elemento da tela para copiar o seletor do Maestro (id/testID ou texto). N\u00e3o use com um flow rodando (F6)", self.alterna_seletor)
        self.bt_instala = self._ferramenta(col, "instalar", "Instalar APK", "Instalar APK|Escolha um ou mais APKs para instalar no aparelho", self.instalar_apk)
        self.bt_desinstala = self._ferramenta(col, "desinstalar", "Desinstalar APK", "Desinstalar APK|Escolha os apps para remover (os favoritos t\u00eam atalho)", self.desinstalar_apk)
        self.bt_log = self._ferramenta(col, "logcat", "Exportar logcat", "Exportar logcat|Salva em arquivo o log dos \u00faltimos 2, 5 ou 10 minutos", self.menu_logcat)
        self.bt_painel = self._ferramenta(col, "aparelho", "App e aparelho", "App e aparelho|Vers\u00e3o de qualquer app, abrir, parar, limpar dados, permiss\u00f5es e preparo para automa\u00e7\u00e3o", self.abre_painel)
        self.bt_arq = self._ferramenta(col, "arquivos", "Arquivos", "Arquivos|Pastas do aparelho: baixar, enviar, abrir e excluir", self.abre_arquivos)
        self.bt_mem = self._ferramenta(col, "memoria", "Mem\u00f3ria", "Mem\u00f3ria|Quanto cada app do aparelho est\u00e1 usando", self.abre_memoria)
        visual.titulo_secao(col, "Vision")
        self._ferramenta(col, "aparencia", "Apar\u00eancia", "Apar\u00eancia|Tema claro ou escuro e cor de destaque", self.abre_aparencia)
        self._ferramenta(col, "logcat", "Registro do vídeo", "Registro do vídeo|Abre a pasta do video.log: travadas, trocas de gravação e um resumo a cada 10 s. Mande este arquivo quando o vídeo travar", self.abre_registro_video)
        self.bt_atualiza = self._ferramenta(col, "atualizar", "Buscar atualiza\u00e7\u00f5es", "Buscar atualiza\u00e7\u00f5es|Procura uma vers\u00e3o nova do Vision e instala com um clique", self.buscar_atualizacoes)

        # ---- coluna principal
        centro = self.centro = tk.Frame(root, bg=BG)
        centro.pack(side="left", fill="both", expand=True)
        topo = tk.Frame(centro, bg=BG)
        topo.pack(fill="x", padx=8, pady=(8, 4))
        self.bt_lado = visual.Botao(topo, "menu", comando=self.alterna_lateral, largura=36, altura=30)
        self.bt_lado.pack(side="left", padx=(0, 8))
        Dica(self.bt_lado, "Barra lateral", "Mostra ou esconde as op\u00e7\u00f5es (F9)")
        self.combo = ttk.Combobox(topo, state="readonly", width=10)
        self.combo.pack(side="left", fill="x", expand=True)  # encolhe junto com a janela
        self.combo.bind("<<ComboboxSelected>>", self.escolheu)
        self.combo.bind("<Button-3>", lambda e: self.menu_aparelho(self.cap.serial, e.x_root, e.y_root))
        self._liga_menu_da_lista()
        Dica(self.combo, "Aparelho", "Abra a lista e clique com o bot\u00e3o direito num aparelho para mais op\u00e7\u00f5es")
        self.bt_ip = visual.Botao(topo, "rede", comando=self.conectar_ip, largura=36, altura=30, cor_icone=visual.AZUL)
        self.bt_ip.pack(side="left", padx=(6, 0))
        Dica(self.bt_ip, "Conectar pelo Wi-Fi", "Conecta um aparelho pela rede. O endere\u00e7o fica salvo e \u00e9 reconectado sozinho")
        self.cb_cap = ttk.Combobox(topo, state="readonly", width=16, values=list(MODOS_CAPTURA))
        self.cb_cap.pack(side="left", padx=(8, 0))
        self.cb_cap.set(next((k for k, v in MODOS_CAPTURA.items() if v == (cap.modo, cap.perfil)), "Quadros (leve)"))
        self.cb_cap.bind("<<ComboboxSelected>>", self.mudou_captura)
        Dica(self.cb_cap, "Modo de captura", "V\u00eddeo: imagem fluida. Quadros: mais leve para o aparelho")

        if aviso:
            av = tk.Label(centro, text=aviso, bg="#fdf3d6", fg="#5c4300", wraplength=440, justify="left", anchor="w", padx=8, pady=4, cursor="arrow", font=("Segoe UI", 8))
            av.pack(fill="x", padx=8, pady=(0, 4))
            av.bind("<Button-1>", lambda e: av.destroy())

        self.area = tk.Frame(centro, bg=visual.TELA_FUNDO)
        self.area.pack(fill="both", expand=True, padx=8)
        self.area.pack_propagate(False)
        self.espera = tk.Label(self.area, bg=visual.TELA_FUNDO, text="Aguardando o aparelho\u2026", fg=FG2, font=(visual.fontes(root)["texto"], 11))
        self.espera.place(relx=0.5, rely=0.5, anchor="center")
        self.tela = tk.Canvas(self.area, bg=visual.TELA_FUNDO, bd=0, highlightthickness=0, width=10, height=10, cursor="arrow")
        self.img_id = self.tela.create_image(0, 0, anchor="nw")
        self.tela.bind("<ButtonPress-1>", self.pressionou)
        self.tela.bind("<B1-Motion>", self.moveu)
        self.tela.bind("<ButtonRelease-1>", self.soltou)
        self.tela.bind("<MouseWheel>", self.rolou)
        self.tela.bind("<Motion>", self.passou)
        self.sel_painel = tk.Frame(centro, bg=BG2)

        self.rodape = visual.Rodape(centro, "Vision %s" % VERSAO)
        self.rodape.pack(fill="x", pady=(6, 0))

        root.bind("<Key>", self.tecla_digitada)
        root.bind("<Control-s>", lambda e: self.salva())
        root.bind("<F11>", lambda e: self.tela_cheia())
        root.bind("<F9>", lambda e: self.alterna_lateral())
        root.bind("<F6>", lambda e: self.alterna_seletor())
        root.bind("<Configure>", self.mudou_tamanho)
        root.bind("<Unmap>", lambda e: setattr(self.cap, "ativo", False) if e.widget is root else None)
        root.bind("<Map>", lambda e: setattr(self.cap, "ativo", not self.pausado) if e.widget is root else None)
        root.protocol("WM_DELETE_WINDOW", self.fechar)
        if not self.config.get("lateral", True):
            self.lado.pack_forget()
        self.tick()
        self.rodape_tick()
        self.root.after(8000, self._atualizacao_automatica)

    # ---- widgets
    def _dica(self, widget, dica):
        titulo, _, detalhe = dica.partition("|")
        Dica(widget, titulo, detalhe)

    def _ferramenta(self, pai, icone, texto, dica, cmd):
        b = visual.Botao(pai, icone, texto, comando=cmd, largura=172, altura=38)
        b.pack(fill="x", pady=(0, 6))
        self._dica(b, dica)
        return b

    # ---- acoes de janela
    def alterna_pausa(self):
        self.pausado = not self.pausado
        self.cap.ativo = not self.pausado
        self.bt_pausa.define(icone="retomar" if self.pausado else "pausar")

    # ---- instalar / desinstalar APK (acoes de escrita: sempre com serial explicito)
    def _serial_ou_aviso(self):
        if not self.cap.serial:
            messagebox.showwarning("Vision", "Nenhum aparelho selecionado.")
            return None
        if self.ocupado:
            messagebox.showinfo("Vision", "Aguarde: %s" % self.ocupado)
            return None
        return self.cap.serial

    def tarefa(self, texto, args, ao_terminar, timeout=600):
        """Roda `adb -s <serial> <args>` em segundo plano e devolve o resultado pela fila."""
        serial = self.cap.serial
        self.ocupado = texto
        for b in (self.bt_instala, self.bt_desinstala):
            b.configure(state="disabled")

        def trabalho():
            try:
                if args and isinstance(args[0], list):  # varios comandos em sequencia
                    linhas, falhou = [], False
                    for cmd in args:
                        rc, out, err = rodar([self.cap.adb, "-s", serial] + cmd, timeout=timeout)
                        resp = (out + " " + err).strip().splitlines()
                        ok = rc == 0 and "Success" in (out + err)
                        falhou = falhou or not ok
                        linhas.append("%s: %s" % (cmd[-1], "removido" if ok else (resp[-1] if resp else "falhou")))
                    self.resultados.put((ao_terminar, 1 if falhou else 0, "\n".join(linhas)))
                else:
                    rc, out, err = rodar([self.cap.adb, "-s", serial] + args, timeout=timeout)
                    self.resultados.put((ao_terminar, rc, (out + "\n" + err).strip()))
            except Exception as e:  # noqa: BLE001
                self.resultados.put((ao_terminar, -1, str(e)))

        threading.Thread(target=trabalho, daemon=True).start()

    def _fim_tarefa(self):
        self.ocupado = ""
        for b in (self.bt_instala, self.bt_desinstala):
            b.configure(state="normal")

    def instalar_apk(self):
        serial = self._serial_ou_aviso()
        if not serial:
            return
        arqs = filedialog.askopenfilenames(title="Escolha a APK (ou as APKs de um app dividido)", filetypes=[("APK", "*.apk"), ("Todos os arquivos", "*.*")])
        if not arqs:
            return
        arqs = list(arqs)
        base = ["install-multiple"] if len(arqs) > 1 else ["install"]
        nome = os.path.basename(arqs[0]) + (" (+%d)" % (len(arqs) - 1) if len(arqs) > 1 else "")
        extra = self._confirma_instalacao(serial, arqs, nome)
        if extra is None:
            return
        self.tarefa("instalando %s em %s..." % (nome, serial), base + ["-r"] + extra + arqs, lambda rc, saida: self._apos_instalar(rc, saida, base, arqs, nome))

    def _nome_aparelho(self, serial):
        a = next((x for x in self.cap.aparelhos if x["serial"] == serial), None)
        return rotulo_aparelho(a) if a else serial

    def _confirma_instalacao(self, serial, arqs, nome):
        """Mostra o que vai ser instalado (versao do APK x versao no aparelho) e pede confirmacao.
        Devolve as opcoes extras do adb install ([] ou ["-d"] para downgrade) ou None se cancelado."""
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            info = apk.le_apks(arqs)
            atual = versoes_no_aparelho(self.cap.adb, serial, [info["pacote"]]).get(info["pacote"], (None, None)) if info and info["pacote"] else (None, None)
        finally:
            self.root.configure(cursor="")
        cab = "Aparelho: %s\nArquivo: %s\n\n" % (self._nome_aparelho(serial), nome)
        if not info or not info["pacote"]:
            ok = messagebox.askyesno("Instalar APK", cab + "N\u00e3o consegui ler a vers\u00e3o deste APK.\n\nInstalar mesmo assim?", parent=self.root)
            return [] if ok else None
        mudanca = "desconhecida" if atual[0] is False else apk.tipo_de_mudanca(info["codigo"], atual[1])
        resumo = {
            "nova": "Instala\u00e7\u00e3o nova: o app n\u00e3o est\u00e1 no aparelho.",
            "atualizacao": "Atualiza\u00e7\u00e3o: o APK \u00e9 mais novo que o instalado.",
            "mesma": "Mesma vers\u00e3o: o app ser\u00e1 reinstalado.",
            "downgrade": "Aten\u00e7\u00e3o: o APK \u00e9 MAIS ANTIGO que o instalado (downgrade).",
            "desconhecida": "N\u00e3o deu para comparar as vers\u00f5es.",
        }[mudanca]
        texto = cab + "Pacote: %s\nVers\u00e3o do APK: %s\nNo aparelho hoje: %s\n\n%s\n\n%s" % (
            info["pacote"], texto_versao(info["versao"], info["codigo"]), texto_versao(*atual), resumo,
            "Instalar a vers\u00e3o mais antiga mesmo assim?" if mudanca == "downgrade" else "Instalar?")
        ok = messagebox.askyesno("Instalar APK", texto, icon="warning" if mudanca == "downgrade" else "question", parent=self.root)
        if not ok:
            return None
        return ["-d"] if mudanca == "downgrade" else []

    def _apos_instalar(self, rc, saida, base, arqs, nome):
        self._fim_tarefa()
        if rc == 0 and "Success" in saida:
            self.aviso_rapido("instalado: " + nome)
            return messagebox.showinfo("Instalar APK", "Instalado com sucesso:\n%s" % nome)
        if "VERSION_DOWNGRADE" in saida:
            if messagebox.askyesno("Instalar APK", "O aparelho já tem uma versão MAIS NOVA desse app.\nInstalar mesmo assim (downgrade)?"):
                return self.tarefa("instalando (downgrade) %s..." % nome, base + ["-r", "-d"] + arqs, lambda r, s: self._apos_instalar(r, s, base, arqs, nome))
            return
        dica = ""
        if "UPDATE_INCOMPATIBLE" in saida or "SIGNATURES" in saida:
            dica = "\n\nA assinatura difere da instalada: desinstale o app antes (botao Desinstalar APK)."
        elif "INSUFFICIENT_STORAGE" in saida:
            dica = "\n\nSem espaco no aparelho."
        messagebox.showerror("Instalar APK", "Falha ao instalar %s:\n\n%s%s" % (nome, saida[-600:] or "sem detalhes", dica))

    def desinstalar_apk(self):
        serial = self._serial_ou_aviso()
        if not serial:
            return
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            _, out, _ = rodar([self.cap.adb, "-s", serial, "shell", "pm", "list", "packages", "-3"], timeout=20)
        except Exception as e:  # noqa: BLE001
            self.root.configure(cursor="")
            return messagebox.showerror("Desinstalar APK", "Não consegui listar os apps: %s" % e)
        self.root.configure(cursor="")
        pacotes = sorted(l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith("package:"))
        if not pacotes:
            return messagebox.showinfo("Desinstalar APK", "Nenhum app de terceiros encontrado no aparelho.")
        self._dialogo_desinstalar(serial, pacotes)

    def _dialogo_desinstalar(self, serial, pacotes):
        dlg = tk.Toplevel(self.root)
        dlg.title("Desinstalar APK - %s" % serial)
        aplica_icone(dlg)
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.geometry("440x480")
        tk.Label(dlg, text="Escolha os apps a desinstalar (Ctrl/Shift para varios):", bg=BG, fg=FG, anchor="w").pack(fill="x", padx=12, pady=(12, 4))
        filtro = tk.StringVar()
        ent = tk.Entry(dlg, textvariable=filtro, bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        ent.pack(fill="x", padx=12, ipady=4)
        lista = tk.Listbox(dlg, bg=BG2, fg=FG, selectbackground=ACENTO, selectforeground="#fff", relief="flat", activestyle="none", exportselection=False, selectmode="extended")
        lista.pack(fill="both", expand=True, padx=12, pady=8)
        manter = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text="Manter dados e cache do app (adb uninstall -k)", variable=manter, bg=BG, fg=FG, selectcolor=BG2, activebackground=BG, activeforeground=FG).pack(anchor="w", padx=12)

        def preenche(*_):
            f = filtro.get().strip().lower()
            lista.delete(0, "end")
            itens = [p for p in pacotes if f in p.lower()]
            for p in itens:
                lista.insert("end", p)

        def marca_favoritos():
            lista.selection_clear(0, "end")
            favs = favoritos(self.config)
            for i in range(lista.size()):
                if lista.get(i) in favs:
                    lista.selection_set(i)
                    lista.see(i)

        def confirma():
            escolhidos = [lista.get(i) for i in lista.curselection()]
            if not escolhidos:
                return
            dlg.configure(cursor="watch")
            dlg.update_idletasks()
            try:
                versoes = versoes_no_aparelho(self.cap.adb, serial, escolhidos)
            finally:
                dlg.configure(cursor="")
            linhas = ["%s  \u00b7  %s" % (pk, texto_versao(*versoes.get(pk, (None, None)))) for pk in escolhidos]
            aviso = "Desinstalar do aparelho %s:\n\n%s" % (self._nome_aparelho(serial), "\n".join(linhas))
            aviso += "\n\nOs dados dos apps serao mantidos." if manter.get() else "\n\nOs DADOS dos apps serao apagados."
            if not messagebox.askyesno("Desinstalar APK", aviso, parent=dlg):
                return
            dlg.destroy()
            cmds = [["uninstall"] + (["-k"] if manter.get() else []) + [pk] for pk in escolhidos]
            nome = escolhidos[0] if len(escolhidos) == 1 else "%d apps" % len(escolhidos)
            self.tarefa("desinstalando %s..." % nome, cmds, lambda rc, saida: self._apos_desinstalar(rc, saida, escolhidos))

        filtro.trace_add("write", preenche)
        preenche()
        rod = tk.Frame(dlg, bg=BG)
        rod.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(rod, text="Marcar favoritos", command=marca_favoritos).pack(side="left")
        ttk.Button(rod, text="Cancelar", command=dlg.destroy).pack(side="right")
        ttk.Button(rod, text="Desinstalar", command=confirma).pack(side="right", padx=(0, 8))
        lista.bind("<Double-Button-1>", lambda e: confirma())
        ent.focus_set()
        dlg.grab_set()

    def _apos_desinstalar(self, rc, saida, pacotes):
        self._fim_tarefa()
        if rc == 0:
            self.aviso_rapido("desinstalado: " + ", ".join(pacotes))
            return messagebox.showinfo("Desinstalar APK", "Desinstalado:\n%s" % "\n".join(pacotes))
        messagebox.showerror("Desinstalar APK", "Resultado por pacote:\n\n%s" % (saida[-800:] or "sem detalhes"))

    def menu_logcat(self):
        m = tk.Menu(self.root, tearoff=0, bg=BG2, fg=FG, activebackground=ACENTO, activeforeground="#ffffff", bd=0)
        for n in JANELAS_LOG:
            m.add_command(label="Exportar os últimos %d minutos" % n, command=lambda n=n: self.exporta_logcat(n))
        try:
            m.tk_popup(self.bt_log.winfo_rootx() + self.bt_log.winfo_width(), self.bt_log.winfo_rooty())
        finally:
            m.grab_release()

    def exporta_logcat(self, minutos):
        serial = self._serial_ou_aviso()
        if not serial:
            return
        self.ocupado = "exportando o logcat dos últimos %d min de %s..." % (minutos, serial)
        self.bt_log.define(desativado=True)

        def trabalho():
            try:
                caminho, n, aviso = exportar_logcat(self.cap.adb, serial, minutos)
                self.resultados.put((lambda rc, s: self._apos_logcat(rc, s, minutos), 0, "\n".join([caminho, str(n), aviso])))
            except Exception as e:  # noqa: BLE001
                self.resultados.put((lambda rc, s: self._apos_logcat(rc, s, minutos), 1, str(e)))

        threading.Thread(target=trabalho, daemon=True).start()

    def _apos_logcat(self, rc, saida, minutos):
        self.ocupado = ""
        self.bt_log.define(desativado=False)
        if rc != 0:
            return messagebox.showerror("Exportar logcat", saida)
        partes = saida.split("\n")
        caminho, n, aviso = partes[0], partes[1], (partes[2] if len(partes) > 2 else "")
        self.aviso_rapido("logcat salvo: %s (%s linhas)" % (caminho, n), 8)
        texto = "Logcat dos últimos %d minutos salvo (%s linhas):\n\n%s" % (minutos, n, caminho)
        if aviso:
            texto += "\n\nAtencao: " + aviso
        if messagebox.askyesno("Exportar logcat", texto + "\n\nAbrir a pasta?"):
            try:
                subprocess.Popen(["explorer", "/select," + caminho])
            except Exception:  # noqa: BLE001
                pass

    def conectar_ip(self):
        ultimo = (self.config.get("ips") or [""])[0]
        txt = simpledialog.askstring("Conectar por IP", "Endereco do aparelho (IP ou IP:porta; a porta padrão e 5555):", initialvalue=ultimo, parent=self.root)
        if not txt:
            return
        txt = txt.strip()
        if not RX_IP.match(txt):
            return messagebox.showerror("Conectar por IP", "Endereco inválido: %s\nUse algo como 192.168.1.20 ou 192.168.1.20:5555" % txt)
        if ":" not in txt:
            txt += ":5555"
        self.ocupado = "conectando em %s..." % txt

        def trabalho():
            try:
                rc, out, err = rodar([self.cap.adb, "connect", txt], timeout=20)
                self.resultados.put((lambda r, s: self._apos_ip(txt, s), rc, (out + "\n" + err).strip()))
            except Exception as e:  # noqa: BLE001
                self.resultados.put((lambda r, s: self._apos_ip(txt, s), -1, str(e)))

        threading.Thread(target=trabalho, daemon=True).start()

    def _apos_ip(self, ip, saida):
        self.ocupado = ""
        baixo = saida.lower()
        nao_autorizado = "failed to authenticate" in baixo
        conectou = ("connected to" in baixo) and "cannot" not in baixo and "failed" not in baixo
        if conectou or nao_autorizado:
            ips = [x for x in (self.config.get("ips") or []) if x != ip]
            self.config["ips"] = ([ip] + ips)[:5]
            salvar_config(self.config)
            self.cap.ips = list(self.config["ips"])
        if nao_autorizado:
            return messagebox.showinfo("Conectar por IP", "O aparelho %s pediu autorizacao.\n\nAceite 'Permitir depuração' na tela dele (marque 'Sempre permitir'). Ele entra na lista assim que você aceitar." % ip)
        if conectou:
            return self.aviso_rapido("conectado em %s" % ip)
        messagebox.showerror("Conectar por IP", "Não consegui conectar em %s:\n\n%s\n\nConfira se o aparelho esta na mesma rede e com a depuração por rede (porta 5555) ligada." % (ip, saida[-300:] or "sem resposta"))

    def abre_painel(self):
        if not self.cap.serial:
            return messagebox.showwarning("Vision", "Nenhum aparelho selecionado.")
        if self.painel is not None:
            self.painel.win.deiconify()
            self.painel.win.lift()
            return
        self.painel = PainelApp(self)

    def abre_arquivos(self):
        if not self.cap.serial:
            return messagebox.showwarning("Vision", "Nenhum aparelho selecionado.")
        if self.arq is not None:
            self.arq.win.deiconify()
            self.arq.win.lift()
            return
        self.arq = GerenciadorArquivos(self)

    def abre_memoria(self):
        if not self.cap.serial:
            return messagebox.showwarning("Vision", "Nenhum aparelho selecionado.")
        if self.mem is not None:
            self.mem.win.deiconify()
            self.mem.win.lift()
            return
        self.mem = MonitorMemoria(self)

    def alterna_lateral(self):
        """Mostra/oculta a barra lateral e lembra a escolha para a próxima vez."""
        if self.lado.winfo_ismapped():
            self.lado.pack_forget()
            self.config["lateral"] = False
        else:
            self.lado.pack(side="left", fill="y", padx=(8, 0), pady=8, before=self.centro)
            self.config["lateral"] = True
        self.visto = -1
        salvar_config(self.config)

    def tela_cheia(self):
        self.cheia = not self.cheia
        self.root.attributes("-fullscreen", self.cheia)

    def escolheu(self, _e=None):
        self.sel_nos = self.sel_hover = self.sel_fixo = None
        self.cap.trocar(self.combo.get().split(" ")[0])
        self.visto = -1
        self.foto = None
        self.tela.itemconfig(self.img_id, image="")  # nao deixa a imagem do aparelho anterior na tela

    def salva(self):
        pasta = os.path.join(os.path.expanduser("~"), "Pictures", "Vision")
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, "captura-%s-%s.png" % (self.cap.serial or "aparelho", datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
        serial = self.cap.serial
        if self.cap.via == "video" and serial:
            # o video chega reduzido: a captura salva e feita em resolucao total
            reserva = self.cap.frame
            self.aviso_rapido("capturando em resolucao total ...", 4)

            def trabalho():
                try:
                    rc, out, err = rodar([self.cap.adb, "-s", serial, "exec-out", "screencap -p"], timeout=20, binario=True)
                    if rc != 0 or out[:4] != b"\x89PNG":
                        raise RuntimeError(err.strip() or "captura vazia")
                    with open(caminho, "wb") as f:
                        f.write(out)
                    self.aviso_rapido("salvo em " + caminho)
                except Exception as e:  # noqa: BLE001
                    if reserva is not None:
                        reserva.save(caminho, "PNG")
                        self.aviso_rapido("salvo (resolucao reduzida: %s) em %s" % (str(e)[:50], caminho))
                    else:
                        self.aviso_rapido("falha ao salvar: %s" % str(e)[:80])

            threading.Thread(target=trabalho, daemon=True).start()
            return
        img = self.cap.frame
        if img is None:
            return self.aviso_rapido("nada para salvar ainda")
        img.save(caminho, "PNG")
        self.aviso_rapido("salvo em " + caminho)

    def mostra_aviso(self, texto):
        av = tk.Label(self.centro, text=texto, bg="#fdf3d6", fg="#5c4300", wraplength=440, justify="left", anchor="w", padx=8, pady=4, cursor="arrow", font=("Segoe UI", 8))
        av.pack(fill="x", padx=8, pady=(0, 4), before=self.area)
        av.bind("<Button-1>", lambda e: av.destroy())

    def aviso_rapido(self, texto, segundos=6):
        self.msg = (texto, time.time() + segundos)

    def fechar(self):
        self.cap.parar = True
        for filha in (self.painel, self.arq, self.mem):
            try:
                if filha is not None:
                    filha.fechar()
            except Exception:
                pass
        self.inj.parar()
        if self.cap.serial and self.cap.via == "video":
            parar_gravacao_remota(self.cap.adb, self.cap.serial)
        self.root.destroy()

    LARGURA_COM_LATERAL = 560  # abaixo disso a barra lateral recolhe sozinha (o ☰ ainda a mostra)

    def mudou_tamanho(self, e):
        if e.widget is self.area or e.widget is self.root:
            self.visto = -1
        if e.widget is self.root:
            self._ajusta_lateral(e.width)

    def _ajusta_lateral(self, largura):
        """So age quando a largura cruza o limite: não briga com quem usa o ☰."""
        estreita = largura < self.LARGURA_COM_LATERAL
        if estreita == getattr(self, "_estreita", None):
            return
        self._estreita = estreita
        if estreita and self.lado.winfo_ismapped():
            self.lado.pack_forget()
        elif not estreita and self.config.get("lateral", True) and not self.lado.winfo_ismapped():
            self.lado.pack(side="left", fill="y", padx=(8, 0), pady=8, before=self.centro)
        self.visto = -1

    def _envia_comandos(self):
        while True:
            args = self.fila.get()
            try:
                serial = self.cap.serial
                if serial:
                    rodar([self.cap.adb, "-s", serial, "shell", "input"] + args, timeout=10)
            except Exception as e:  # noqa: BLE001
                self.aviso_rapido("falha ao enviar: %s" % str(e)[:80])

    def enviar(self, *args):
        """Caminho universal e lento: `adb shell input ...` (so quando o injetor não esta pronto)."""
        self.fila.put([str(x) for x in args])  # o adb so aceita texto

    def inj_envia(self, linha):
        return self.inj.envia(linha, self.cap.serial)

    def tecla(self, codigo):
        if not self.inj_envia("k %s" % codigo):
            self.enviar("keyevent", codigo)

    def _dims_dispositivo(self):
        """Tamanho real do aparelho (o video chega reduzido), na mesma orientacao da imagem."""
        tam = self.cap.tamanho
        if tam is None:
            return None
        fw, fh = tam
        dw, dh = self.cap.dev_size or (fw, fh)
        if (fw > fh) != (dw > dh):
            dw, dh = dh, dw
        return dw, dh

    def _ponto(self, e):
        """Posicao do mouse sobre a imagem -> pixel do aparelho."""
        d = self._dims_dispositivo()
        nw, nh = self.exibido
        if d is None or not nw or not nh:
            return None
        x = min(max(e.x, 0), nw - 1) * d[0] / nw
        y = min(max(e.y, 0), nh - 1) * d[1] / nh
        return int(x), int(y)

    def ripple(self, x, y):
        """Efeito visual imediato no ponto do clique: o usuario ve que o clique foi recebido."""
        r = self.tela.create_oval(x - 6, y - 6, x + 6, y + 6, outline="#ffffff", width=3)

        def passo(i=0):
            if i >= 7:
                self.tela.delete(r)
                return
            d = 6 + i * 4
            self.tela.coords(r, x - d, y - d, x + d, y + d)
            self.root.after(28, lambda: passo(i + 1))

        passo()

    def pressionou(self, e):
        self.tela.focus_set()
        if self.sel_on:  # seletor ligado: o clique escolhe o elemento e nao vai para o aparelho
            return self.sel_clique(e)
        self.cap.diag.toque()
        ponto = self._ponto(e)
        self.toque = (ponto, time.time(), e.x, e.y)
        self.ripple(e.x, e.y)
        self.via_inj = bool(ponto) and self.inj_envia("d %d %d" % ponto)

    def moveu(self, e):
        if not (self.toque and self.via_inj):
            return
        agora = time.time()
        if agora - self.ult_mov < 0.012:  # ~80 movimentos por segundo no maximo
            return
        self.ult_mov = agora
        ponto = self._ponto(e)
        if ponto:
            self.inj_envia("m %d %d" % ponto)

    def soltou(self, e):
        toque, self.toque = self.toque, None
        if not toque or not toque[0]:
            return
        ini, t0, x0, y0 = toque
        fim = self._ponto(e)
        if not fim:
            return
        if self.via_inj:
            self.inj_envia("u %d %d" % fim)
            self.via_inj = False
            return
        dt = int((time.time() - t0) * 1000)  # plano B: gesto completo de uma vez
        if abs(e.x - x0) > 8 or abs(e.y - y0) > 8:
            self.enviar("swipe", ini[0], ini[1], fim[0], fim[1], max(120, min(dt, 1500)))
        elif dt >= 500:
            self.enviar("swipe", ini[0], ini[1], ini[0], ini[1], dt)  # toque longo
        else:
            self.enviar("tap", ini[0], ini[1])

    def rolou(self, e):
        if self.sel_on:
            self.sel_nos, self.sel_hover = None, None  # a tela vai mudar: a arvore lida fica velha
            self._sel_desenha()
        d = self._dims_dispositivo()
        if d is None:
            return
        w, h = d
        passo = int(h * 0.25) * (1 if e.delta > 0 else -1)
        cx, cy = w // 2, h // 2
        if not self.inj_envia("s %d %d %d %d 220" % (cx, cy - passo // 2, cx, cy + passo // 2)):
            self.enviar("swipe", cx, cy - passo // 2, cx, cy + passo // 2, 250)

    def tecla_digitada(self, e):
        if isinstance(e.widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox)):
            return  # digitando num campo do proprio programa (filtro do logcat etc.): nao vai para o aparelho
        if self.sel_on and e.keysym == "Escape":
            return self.alterna_seletor()
        if e.state & 0x4 and e.keysym.lower() == "v":
            return self.colar_no_aparelho()
        if e.state & 0x4 and e.keysym.lower() == "c":
            return self.copiar_do_aparelho()
        if e.keysym in CHAVES:
            return self.tecla(CHAVES[e.keysym])
        c = e.char
        if c and c.isprintable() and not (e.state & 0x4):  # sem Ctrl
            if self.inj_envia("t " + quote(c, safe="")):
                return
            if c == " ":
                self.enviar("text", "%s")
            elif re.fullmatch(r"[A-Za-z0-9.,_@:/+=-]", c):
                self.enviar("text", c)

    def colar_no_aparelho(self):
        """Ctrl+V: o texto copiado no PC vai para a area de transferencia do aparelho e e colado
        no campo em foco (com acentos). Sem o injetor, digita so os caracteres que o adb aceita."""
        try:
            txt = self.root.clipboard_get()
        except tk.TclError:
            txt = ""
        txt = txt.replace("\r\n", "\n")
        if not txt:
            return self.aviso_rapido("nada para colar: a area de transferencia do PC esta vazia")
        if self.inj_envia("v " + quote(txt, safe="")):
            return self.aviso_rapido("colado no aparelho: %s" % resumo_texto(txt), 3)
        simples = "".join(c for c in txt.replace("\n", " ") if re.fullmatch(r"[A-Za-z0-9 .,_@:/+=-]", c))
        if simples:
            self.enviar("text", simples.replace(" ", "%s"))
        self.aviso_rapido("colado sem acentos e símbolos (clique via adb): %s" % resumo_texto(simples), 5)

    def copiar_do_aparelho(self):
        """Ctrl+C: copia a seleção no aparelho (KEYCODE_COPY) e traz o texto para o PC."""
        serial = self.cap.serial
        if not self.inj.ok(serial):
            return self.aviso_rapido("copiar do aparelho precisa do clique instantâneo (injetor), que não esta ativo", 5)

        def trabalho():
            self.inj_envia("k 278")  # KEYCODE_COPY: copia o texto selecionado no app
            time.sleep(0.3)
            r = self.inj.pergunta("g", serial, "CLIP")
            txt = unquote(r) if r else ""
            self.root.after(0, lambda: self._copiado_do_aparelho(txt, r is None))

        threading.Thread(target=trabalho, daemon=True).start()

    def _copiado_do_aparelho(self, txt, falhou):
        if not txt:
            return self.aviso_rapido("não foi possível ler a area de transferencia do aparelho" if falhou
                                     else "a area de transferencia do aparelho esta vazia (selecione um texto antes)", 5)
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        self.aviso_rapido("copiado do aparelho: %s" % resumo_texto(txt), 3)

    def mudou_captura(self, _e=None):
        nome = self.cb_cap.get()
        modo, perfil = MODOS_CAPTURA[nome]
        if modo == "video" and av is None:
            self.cb_cap.set("Quadros (leve)")
            return self.aviso_rapido("modo video indisponivel nesta versão (decodificador ausente)", 5)
        self.cap.modo, self.cap.perfil = modo, perfil
        self.cap.video_ok, self.cap.falhas_video = av is not None, 0
        self.cap.nota = ""
        self.cap.erro = ""
        self.config["captura"] = nome
        salvar_config(self.config)
        self.visto = -1

    # ---- seletor de identificador (Maestro)
    def alterna_seletor(self):
        self.sel_on = not self.sel_on
        self.bt_sel.define(ativo=self.sel_on)
        self.sel_hover = self.sel_fixo = None
        if self.sel_on:
            self.tela.configure(cursor="crosshair")
            self._sel_painel([])
            self.sel_painel.pack(fill="x", padx=8, pady=(4, 0), before=self.rodape)
            self.sel_ler()
        else:
            self.tela.configure(cursor="arrow")
            self.sel_painel.pack_forget()
            self.sel_nos = None
        self._sel_desenha()

    def sel_ler(self, ponto=None):
        """Le a arvore da tela em segundo plano; com `ponto`, escolhe o elemento ali ao terminar."""
        serial = self.cap.serial
        if not serial:
            return self.aviso_rapido("nenhum aparelho selecionado")
        if self.sel_lendo:
            self.sel_pendente = ponto
            return
        self.sel_lendo, self.sel_pendente = True, None
        self.aviso_rapido("lendo os elementos da tela do aparelho...", 30)
        adb = self.cap.adb

        def trabalho():
            nos, erro = seletor.ler_tela(rodar, adb, serial)
            self.resultados.put((lambda rc, s: self._sel_lido(serial, nos, erro, ponto), 0, ""))

        threading.Thread(target=trabalho, daemon=True).start()

    def _sel_lido(self, serial, nos, erro, ponto):
        self.sel_lendo = False
        if not self.sel_on or serial != self.cap.serial:
            return
        if nos is None:
            self.aviso_rapido("não deu para ler a tela: %s" % erro, 10)
            return
        self.sel_nos = nos
        self.aviso_rapido("%d elementos lidos. Passe o mouse e clique no que quer" % len(nos), 4)
        pendente = getattr(self, "sel_pendente", None)
        ponto = pendente or ponto
        if pendente:
            return self.sel_ler(pendente)
        if ponto:
            i = seletor.no_no_ponto(nos, *ponto)
            self.sel_fixo = i
            d = self._dims_dispositivo()
            self._sel_painel(seletor.seletores(nos, i, d) if i is not None else [], nos[i] if i is not None else None)
        self._sel_desenha()

    def passou(self, e):
        if not (self.sel_on and self.sel_nos):
            return
        p = self._ponto(e)
        i = seletor.no_no_ponto(self.sel_nos, *p) if p else None
        if i != self.sel_hover:
            self.sel_hover = i
            self._sel_desenha()
            if i is not None:
                self.aviso_rapido(seletor.resumo(self.sel_nos[i]), 3)

    def sel_clique(self, e):
        p = self._ponto(e)
        if not p:
            return
        self.ripple(e.x, e.y)
        if self.sel_nos:  # mostra ja com a leitura anterior e confere com uma leitura nova
            i = seletor.no_no_ponto(self.sel_nos, *p)
            if i is not None:
                self.sel_fixo = i
                self._sel_painel(seletor.seletores(self.sel_nos, i, self._dims_dispositivo()), self.sel_nos[i], lendo=True)
                self._sel_desenha()
        self.sel_ler(p)

    def _sel_desenha(self):
        self.tela.delete("sel")
        d = self._dims_dispositivo()
        nw, nh = self.exibido
        if not (self.sel_on and self.sel_nos and d and nw and nh):
            return
        kx, ky = nw / d[0], nh / d[1]
        for i, cor, larg in ((self.sel_hover, "#ffd60a", 2), (self.sel_fixo, ACENTO, 3)):
            if i is None or i >= len(self.sel_nos):
                continue
            b = self.sel_nos[i]["bounds"]
            self.tela.create_rectangle(b[0] * kx, b[1] * ky, b[2] * kx - 1, b[3] * ky - 1, outline=cor, width=larg, tags="sel")

    def _sel_painel(self, sugestoes, no=None, lendo=False):
        for filho in self.sel_painel.winfo_children():
            filho.destroy()
        cab = tk.Frame(self.sel_painel, bg=BG2)
        cab.pack(fill="x", padx=8, pady=(6, 2))
        titulo = seletor.resumo(no) if no else "Clique num elemento da tela (o clique não vai para o aparelho). Esc sai."
        tk.Label(cab, text=titulo, bg=BG2, fg=FG, font=("Segoe UI", 9, "bold" if no else "normal"), anchor="w", justify="left", wraplength=360).pack(side="left", fill="x", expand=True)
        tk.Button(cab, text="✕", command=self.alterna_seletor, bg=BG2, fg=FG2, activebackground=HOVER, bd=0, relief="flat", cursor="arrow", takefocus=0).pack(side="right")
        tk.Button(cab, text="Ler de novo", command=self.sel_ler, bg=BG, fg=FG, activebackground=HOVER, bd=0, relief="flat", cursor="arrow", takefocus=0, font=("Segoe UI", 8)).pack(side="right", padx=4, ipadx=4)
        if lendo:
            tk.Label(self.sel_painel, text="conferindo com uma leitura nova da tela...", bg=BG2, fg=FG2, font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=8)
        for rotulo, texto in sugestoes[:6]:
            linha = tk.Frame(self.sel_painel, bg=BG2)
            linha.pack(fill="x", padx=8, pady=2)
            tk.Button(linha, text="Copiar", command=lambda t=texto: self.copiar(t), bg=ACENTO, fg="#ffffff", activebackground=HOVER, bd=0, relief="flat", cursor="arrow", takefocus=0, font=("Segoe UI", 8)).pack(side="right", ipadx=6)
            tk.Label(linha, text=rotulo, bg=BG2, fg=FG2, font=("Segoe UI", 8), anchor="w").pack(fill="x")
            tk.Label(linha, text=texto, bg=BG, fg=FG, font=("Consolas", 9), anchor="w", justify="left", padx=6, pady=2).pack(fill="x", padx=(0, 6))
        tk.Frame(self.sel_painel, bg=BG2, height=4).pack()

    def copiar(self, texto):
        self.root.clipboard_clear()
        self.root.clipboard_append(texto)
        self.aviso_rapido("copiado: " + texto.replace("\n", " ")[:70], 4)

    # ---- servidor adb (wrapper em outra porta)
    def mostra_aviso_acao(self, texto, rotulo, acao):
        caixa = tk.Frame(self.centro, bg="#fdf3d6")
        caixa.pack(fill="x", padx=8, pady=(0, 4), before=self.area)

        def faz():
            caixa.destroy()
            acao()

        tk.Button(caixa, text="✕", command=caixa.destroy, bg="#fdf3d6", fg="#5c4300", bd=0, relief="flat", cursor="arrow", takefocus=0).pack(side="right", padx=(0, 4))
        tk.Button(caixa, text=rotulo, command=faz, bg="#5c4300", fg="#ffffff", activebackground="#7a5a00", bd=0, relief="flat", cursor="arrow", takefocus=0, font=("Segoe UI", 8, "bold")).pack(side="right", padx=4, pady=4, ipadx=6)
        tk.Label(caixa, text=texto, bg="#fdf3d6", fg="#5c4300", wraplength=330, justify="left", anchor="w", padx=8, pady=4, font=("Segoe UI", 8)).pack(side="left", fill="x", expand=True)

    def troca_adb(self, exe, porta):
        """Passa a usar o adb.exe real na porta indicada (vale para todos os comandos deste programa)."""
        os.environ["ADB_SERVER_PORT"] = str(porta)
        self.inj.parar()
        self.inj.adb, self.inj.erro = exe, ""
        self.cap.adb = exe
        self.cap.aparelhos = listar_aparelhos(exe)
        self.cap.trocar("")
        self.adb_porta = porta
        self.config["adb_exe"], self.config["adb_porta"] = exe, porta
        salvar_config(self.config)
        self.aviso_rapido("usando %s na porta %d (lembrado para as próximas vezes)" % (exe, porta), 8)

    # ---- varios aparelhos: menu de cada um e cada um na sua sessao
    def _liga_menu_da_lista(self):
        """Botao direito nos itens da lista aberta do combobox (a lista e uma janela interna do Tk)."""
        try:
            pop = self.root.tk.call("ttk::combobox::PopdownWindow", str(self.combo))
            self._lista_path = str(pop) + ".f.l"
            self.root.tk.call("bind", self._lista_path, "<Button-3>", self.root.register(self._direito_na_lista) + " %y %X %Y")
        except tk.TclError:
            self._lista_path = None  # Tk diferente: fica o botao direito no proprio combobox

    def _direito_na_lista(self, y, x_tela, y_tela):
        i = int(self.root.tk.call(self._lista_path, "nearest", y))
        valores = list(self.combo["values"])
        if not 0 <= i < len(valores):
            return
        self.root.tk.call("ttk::combobox::Unpost", str(self.combo))  # fecha a lista antes do menu
        serial = valores[i].split(" ")[0]
        self.root.after(1, lambda: self.menu_aparelho(serial, int(x_tela), int(y_tela)))

    def menu_aparelho(self, serial, x, y):
        m = tk.Menu(self.root, tearoff=0, bg=BG2, fg=FG, activebackground=ACENTO, activeforeground="#ffffff",
                    disabledforeground=FG2, bd=0)
        if not serial:
            m.add_command(label="Nenhum aparelho escolhido", state="disabled")
            return m.tk_popup(x, y)
        estado = next((a["estado"] for a in self.cap.aparelhos if a["serial"] == serial), "fora da lista")
        atual = serial == self.cap.serial
        pronto = estado == "device"
        info = next((a for a in self.cap.aparelhos if a["serial"] == serial), {"serial": serial, "estado": estado})
        m.add_command(label=rotulo_aparelho(info), state="disabled")
        m.add_separator()
        m.add_command(label="Em uso nesta janela" if atual else "Usar nesta janela",
                      state="disabled" if atual or not pronto else "normal", command=lambda: self._usa_aparelho(serial))
        m.add_command(label="Abrir em nova sess\u00e3o", state="disabled" if atual or not pronto else "normal",
                      command=lambda: self.abrir_em_outra_janela(serial))
        m.add_command(label="Copiar o serial", command=lambda: self.copiar(serial))
        m.add_separator()
        if ":" in serial:  # aparelho de rede: desconecta e esquece o IP
            m.add_command(label="Desconectar e esquecer", command=lambda: self.excluir_aparelho(serial))
        else:
            m.add_command(label="Para remover, desconecte o cabo", state="disabled")
        m.tk_popup(x, y)

    def _usa_aparelho(self, serial):
        item = next((v for v in self.combo["values"] if v.split(" ")[0] == serial), None)
        if item:
            self.combo.set(item)
            self.escolheu()

    def excluir_aparelho(self, serial):
        if not messagebox.askyesno("Excluir aparelho", "Desconectar %s e esquecer esse IP?\n\nEle deixa de ser reconectado sozinho. "
                                   "Para usar de novo, conecte pelo bot\u00e3o do Wi-Fi." % serial, parent=self.root):
            return
        self.config["ips"] = [x for x in (self.config.get("ips") or []) if x != serial]
        salvar_config(self.config)
        self.cap.ips = [x for x in self.cap.ips if x != serial]
        self.cap.aparelhos = [a for a in self.cap.aparelhos if a["serial"] != serial]
        if serial == self.cap.serial:
            self.inj.parar()
            self.cap.trocar("")
            self.foto = None
            self.tela.itemconfig(self.img_id, image="")
        adb = self.cap.adb
        threading.Thread(target=lambda: rodar([adb, "disconnect", serial], timeout=10), daemon=True).start()
        self.aviso_rapido("%s desconectado e esquecido" % serial, 5)

    @staticmethod
    def _comando_vision():
        """Como abrir outra instancia deste Vision (o .exe instalado ou o código-fonte, sem console)."""
        if getattr(sys, "frozen", False):
            return [sys.executable]
        py = sys.executable
        sem_console = os.path.join(os.path.dirname(py), "pythonw.exe")
        return [sem_console if os.path.isfile(sem_console) else py, os.path.abspath(__file__)]

    def abrir_em_outra_janela(self, serial):
        """Outra instancia do Vision já com o aparelho escolhido (mesmo adb e mesma porta)."""
        cmd = self._comando_vision()
        try:
            subprocess.Popen(cmd + ["--serial", serial, "--adb", self.cap.adb], close_fds=True, env=ambiente_limpo())
            self.aviso_rapido("abrindo %s em nova sessão..." % serial, 4)
        except Exception as e:  # noqa: BLE001
            self.aviso_rapido("não foi possível abrir nova sessão: %s" % str(e)[:80], 6)

    def abre_registro_video(self):
        """Mostra o video.log no Explorer (ja selecionado), para mandar quando o video travar."""
        caminho = self.cap.diag.caminho
        if not os.path.isfile(caminho):
            self.cap.diag.evento("registro aberto pelo botao (ainda sem video nesta sessao)")
        try:
            subprocess.Popen(["explorer", "/select," + caminho], env=ambiente_limpo())
        except Exception as e:  # noqa: BLE001
            self.aviso_rapido("não consegui abrir a pasta: %s" % str(e)[:80], 6)

    # ---- aparencia: tema e cor de destaque
    def abre_aparencia(self):
        w = tk.Toplevel(self.root)
        w.title("Apar\u00eancia")
        aplica_icone(w)
        w.configure(bg=BG)
        w.resizable(False, False)
        w.transient(self.root)
        f = visual.fontes(w)
        escolha = {"tema": self.config.get("tema", "escuro"), "destaque": self.config.get("destaque", "roxo")}
        temas, cores = {}, {}

        def marca():
            for nome, b in temas.items():
                b.define(ativo=escolha["tema"] == nome)
            for nome, (c, cor) in cores.items():
                c.delete("all")
                if escolha["destaque"] == nome:
                    c.create_oval(2, 2, 37, 37, outline=FG, width=2)
                c.create_oval(8, 8, 31, 31, fill=cor, outline="")

        tk.Label(w, text="Tema", bg=BG, fg=FG, font=(f["forte"], 11)).pack(anchor="w", padx=18, pady=(16, 6))
        linha = tk.Frame(w, bg=BG)
        linha.pack(fill="x", padx=18)
        for nome, rotulo in (("escuro", "Escuro"), ("claro", "Claro")):
            b = visual.Botao(linha, "tema_" + nome, rotulo, comando=lambda n=nome: (escolha.update(tema=n), marca()), largura=140, altura=38)
            b.pack(side="left", padx=(0, 8))
            temas[nome] = b
        tk.Label(w, text="Cor de destaque", bg=BG, fg=FG, font=(f["forte"], 11)).pack(anchor="w", padx=18, pady=(16, 6))
        linha = tk.Frame(w, bg=BG)
        linha.pack(fill="x", padx=18)
        for nome, (cor, _, _) in visual.DESTAQUES.items():
            c = tk.Canvas(linha, width=40, height=40, bg=BG, highlightthickness=0, cursor="arrow")
            c.pack(side="left", padx=(0, 6))
            c.bind("<Button-1>", lambda e, n=nome: (escolha.update(destaque=n), marca()))
            Dica(c, nome.capitalize())
            cores[nome] = (c, cor)
        tk.Label(w, text="O Vision reabre no mesmo aparelho para aplicar as cores.", bg=BG, fg=FG2,
                 font=(f["texto"], 9)).pack(anchor="w", padx=18, pady=(14, 0))
        botoes = tk.Frame(w, bg=BG)
        botoes.pack(fill="x", padx=18, pady=(12, 16))

        def aplicar():
            w.destroy()
            if (escolha["tema"], escolha["destaque"]) == (self.config.get("tema", "escuro"), self.config.get("destaque", "roxo")):
                return
            self.config.update(escolha)
            salvar_config(self.config)
            self.reabrir()

        ok = visual.Botao(botoes, "aplicar", "Aplicar", comando=aplicar, largura=120, altura=36)
        ok.define(ativo=True)
        ok.pack(side="right")
        visual.Botao(botoes, "fechar", "Cancelar", comando=w.destroy, largura=110, altura=36).pack(side="right", padx=(0, 8))
        marca()

    def reabrir(self):
        """Abre um Vision novo com os mesmos argumentos e o aparelho atual, e fecha este."""
        args, pula = [], False
        for a in sys.argv[1:]:
            if pula:
                pula = False
            elif a == "--serial":
                pula = True
            else:
                args.append(a)
        if self.cap.serial:
            args += ["--serial", self.cap.serial]
        try:
            subprocess.Popen(self._comando_vision() + args, close_fds=True, env=ambiente_limpo())
        except Exception as e:  # noqa: BLE001
            return messagebox.showerror("Vision", "N\u00e3o foi poss\u00edvel reabrir: %s\nFeche e abra o Vision para aplicar." % e, parent=self.root)
        self.fechar()

    # ---- atualizacoes (Releases do GitHub)
    def _token_github(self, pedir):
        if not ATUALIZACAO["token"]:
            return None
        token = (self.config.get("github_token") or "").strip()
        if not token and pedir:
            token = (simpledialog.askstring(
                "Token do GitHub",
                "Esta vers\u00e3o busca atualiza\u00e7\u00f5es no reposit\u00f3rio privado %s.\n"
                "Cole um token do GitHub com leitura desse reposit\u00f3rio (Contents: Read).\n"
                "Ele fica salvo s\u00f3 nesta m\u00e1quina, em %%APPDATA%%\\Vision." % ATUALIZACAO["repo"],
                show="*", parent=self.root) or "").strip()
            if token:
                self.config["github_token"] = token
                salvar_config(self.config)
        return token or None

    def _atualizacao_automatica(self):
        """Uma consulta por dia, em silencio: so aparece algo se houver versão nova."""
        if time.time() - float(self.config.get("atualizacao_checada") or 0) < 86400:
            return
        if ATUALIZACAO["token"] and not self.config.get("github_token"):
            return  # sem token, a busca fica so no botao
        self.buscar_atualizacoes(manual=False)

    def buscar_atualizacoes(self, manual=True):
        token = self._token_github(pedir=manual)
        if ATUALIZACAO["token"] and not token:
            return self.aviso_rapido("busca de atualizações cancelada: falta o token do GitHub", 5)
        if manual:
            self.ocupado = "buscando atualizações..."

        def trabalho():
            try:
                info, erro = atualizacao.ultima_versao(ATUALIZACAO["repo"], ATUALIZACAO["tag"], ATUALIZACAO["arquivo"], token), ""
            except RuntimeError as e:
                info, erro = None, str(e)
            self.root.after(0, lambda: self._atualizacao_resposta(info, erro, manual, token))

        threading.Thread(target=trabalho, daemon=True).start()

    def _atualizacao_resposta(self, info, erro, manual, token):
        if manual:
            self.ocupado = ""
        if erro:
            if "recusado" in erro:
                self.config.pop("github_token", None)  # na proxima vez o token e pedido de novo
                salvar_config(self.config)
            if manual:
                messagebox.showwarning("Vision", "N\u00e3o foi poss\u00edvel buscar atualiza\u00e7\u00f5es: %s." % erro, parent=self.root)
            return
        self.config["atualizacao_checada"] = time.time()
        salvar_config(self.config)
        if not info or not atualizacao.mais_nova(info["versao"], VERSAO):
            if manual:
                messagebox.showinfo("Vision", "Voc\u00ea j\u00e1 tem a vers\u00e3o mais recente (%s)." % VERSAO, parent=self.root)
            return
        if manual:
            return self._oferece_atualizacao(info, token)
        self.mostra_aviso_acao("Vision %s dispon\u00edvel (voc\u00ea tem a %s)." % (info["versao"], VERSAO), "Atualizar",
                               lambda: self._oferece_atualizacao(info, token))

    def _oferece_atualizacao(self, info, token):
        notas = info["notas"] if len(info["notas"]) <= 700 else info["notas"][:700] + "..."
        if not getattr(sys, "frozen", False):  # rodando pelo codigo-fonte: o instalador nao se aplica
            if messagebox.askyesno("Vision", "Vision %s dispon\u00edvel. Abrir a p\u00e1gina da vers\u00e3o?" % info["versao"], parent=self.root):
                webbrowser.open(info["pagina"])
            return
        pergunta = "Vision %s dispon\u00edvel (voc\u00ea tem a %s).\n\n%s\n\nBaixar e instalar agora? Todas as janelas do Vision ser\u00e3o fechadas, e ele abre de novo sozinho no fim." % (info["versao"], VERSAO, notas)
        if not messagebox.askyesno("Atualizar o Vision", pergunta, parent=self.root):
            return
        destino = os.path.join(tempfile.gettempdir(), info["arquivo"])
        self.ocupado = "baixando atualização..."

        def progresso(feito, total):
            self.ocupado = ("baixando atualização %d%%" % (feito * 100 // total)) if total else "baixando atualização %.1f MB" % (feito / 1e6)

        def trabalho():
            try:
                atualizacao.baixar(info, destino, token, progresso)
                erro = ""
            except Exception as e:  # noqa: BLE001
                erro = str(e)[:160]
            self.root.after(0, lambda: self._instala_atualizacao(destino, erro))

        threading.Thread(target=trabalho, daemon=True).start()

    def _instala_atualizacao(self, destino, erro):
        self.ocupado = ""
        if erro:
            return messagebox.showerror("Vision", "O download da atualiza\u00e7\u00e3o falhou: %s" % erro, parent=self.root)
        try:
            subprocess.Popen(comando_de_instalacao(destino, sys.executable, [os.getpid(), os.getppid()]), close_fds=True,
                             env=ambiente_limpo(), creationflags=SEM_JANELA | 0x00000200)  # sem janela, grupo proprio
        except Exception as e:  # noqa: BLE001
            return messagebox.showerror("Vision", "N\u00e3o foi poss\u00edvel abrir o instalador: %s" % e, parent=self.root)
        self.fechar()

    # ---- laco de desenho (so a thread da UI mexe no Tk)
    def tick(self):
        try:
            while not self.resultados.empty():
                cb, rc, saida = self.resultados.get_nowait()
                cb(rc, saida)
            cap = self.cap
            t0 = time.perf_counter()
            if cap.tamanho is not None and cap.seq != self.visto:
                self.visto = cap.seq
                self.desenha()
            custo = (time.perf_counter() - t0) * 1000
            if custo > 0.5:
                cap.diag.desenhou(custo)
        except Exception as e:  # noqa: BLE001
            self.aviso_rapido("erro ao desenhar: %s" % e)
            custo = 0
        # maquina lenta: se desenhar custa caro, espaca os quadros para o laco ficar livre para os cliques
        base = 33 if self.cap.via == "video" else 70
        self.root.after(max(base, int(custo * 2)), self.tick)

    def desenha(self):
        aw, ah = self.area.winfo_width(), self.area.winfo_height()
        tam = self.cap.tamanho
        if aw < 10 or ah < 10 or tam is None:
            return
        w, h = tam
        k = min(aw / w, ah / h)
        nw, nh = max(1, int(w * k)), max(1, int(h * k))
        mostrada = self.cap.imagem(nw, nh)
        if mostrada is None:
            return
        self.exibido = (nw, nh)
        if self.foto is not None and (self.foto.width(), self.foto.height()) == (nw, nh):
            self.foto.paste(mostrada)  # reaproveita a imagem do Tk: sem alocar nem refazer o layout
        else:
            self.foto = ImageTk.PhotoImage(mostrada)
            self.tela.itemconfig(self.img_id, image=self.foto)
        if self.espera is not None:
            self.espera.place_forget()
            self.espera = None
        if self.tela.winfo_reqwidth() != nw or self.tela.winfo_reqheight() != nh or not self.tela.winfo_ismapped():
            self.tela.configure(width=nw, height=nh)
            self.tela.place(relx=0.5, rely=0.5, anchor="center")
        if self.sel_on:
            self._sel_desenha()

    def rodape_tick(self):
        cap = self.cap
        lista = [rotulo_aparelho(a) for a in cap.aparelhos]
        if list(self.combo["values"]) != lista:
            self.combo["values"] = lista
        atual = next((x for x in lista if x.split(" ")[0] == cap.serial), "") if cap.serial else ""
        if atual and self.combo.get() != atual:
            self.combo.set(atual)
        if cap.serial:
            self.inj.garantir(cap.serial)
        cor = FG2
        if self.ocupado:
            txt, cor = self.ocupado, ACENTO
        elif self.msg[1] > time.time():
            txt = self.msg[0]
        elif self.dica_txt and time.time() < self.dica_ate:
            txt = self.dica_txt
        elif cap.erro:
            txt, cor = cap.erro, PERIGO
        else:
            agora = time.time()
            self.fps_hist = [(a, b) for a, b in self.fps_hist + [(agora, cap.seq)] if a > agora - 3.0]
            fps = (self.fps_hist[-1][1] - self.fps_hist[0][1]) / max(0.001, self.fps_hist[-1][0] - self.fps_hist[0][0]) if len(self.fps_hist) > 1 else 0.0
            clique = "Toque instant\u00e2neo" if self.inj.ok(cap.serial) else ("Toque lento (via adb)" if self.inj.erro else "Preparando o toque\u2026")
            dim = "%d\u00d7%d" % cap.tamanho if cap.tamanho is not None else "\u2014"
            idade = time.time() - cap.t_frame if cap.t_frame else None
            if self.pausado:
                estado = "Pausado"
            elif idade is None:
                estado = "Aguardando imagem"
            elif idade < 4:
                estado = "Ao vivo"
            else:
                estado = "Imagem parada h\u00e1 %d s" % idade
            via = "V\u00eddeo" if cap.via == "video" else "Quadros (%d ms)" % cap.ms
            if cap.nota and cap.via != "video":
                via += " \u00b7 v\u00eddeo indispon\u00edvel, tentando de novo"
            instantaneo = self.inj.ok(cap.serial)
            self.rodape.estado([
                (estado, visual.VERDE if estado == "Ao vivo" else visual.AMBAR),
                ("%s \u00b7 %.0f fps" % (via, fps), None),
                (clique, visual.VERDE if instantaneo else visual.AMBAR),
                ("Porta %d" % self.adb_porta, None),
            ])
            txt = None
        if txt is not None:
            self.rodape.mensagem(txt, cor)
        self.root.title("Vision - %s%s" % (cap.serial or "sem aparelho", " (pausado)" if self.pausado else ""))
        self.root.after(400, self.rodape_tick)


def comando_de_instalacao(instalador, exe_app, pids, espera=20):
    """PowerShell que roda depois que este Vision fecha: espera os processos dele, forca a parada de
    qualquer Vision aberto da mesma pasta (outras sessoes ou um que travou) e entao roda o instalador.
    O instalador precisa do Vision parado para trocar o Vision.exe."""
    def aspas(t):
        return "'" + str(t).replace("'", "''") + "'"
    ids = ",".join(str(int(x)) for x in pids if x)
    script = "; ".join([
        "$ErrorActionPreference = 'SilentlyContinue'",
        "Wait-Process -Id %s -Timeout %d" % (ids, espera),
        "Get-Process | Where-Object { $_.Path -eq %s } | Stop-Process -Force" % aspas(exe_app),
        "Start-Sleep -Milliseconds 800",
        "Start-Process -FilePath %s -ArgumentList '/SILENT','/SUPPRESSMSGBOXES','/NORESTART'" % aspas(instalador),
    ])
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", script]


def versoes_no_aparelho(adb, serial, pacotes):
    """{pacote: (versao, codigo)} lidos do aparelho; (None, None) para o que nao esta instalado e
    (False, None) quando o aparelho nao respondeu (nao da para dizer se esta instalado)."""
    pacotes = [x for x in pacotes if re.fullmatch(r"[A-Za-z0-9._]+", x)]
    if not pacotes:
        return {}
    cmd = "; ".join("echo '##%s'; dumpsys package %s | grep -E 'versionName=|versionCode='" % (x, x) for x in pacotes) + "; true"  # o grep sem resultado nao vira erro
    try:
        rc, out, _ = rodar([adb, "-s", serial, "shell", cmd], timeout=30)
    except Exception:  # noqa: BLE001
        rc, out = 1, ""
    if "##" not in out:  # o shell nem rodou (aparelho fora, sem permissao...)
        return {x: (False, None) for x in pacotes}
    partes, atual = {}, None
    for linha in out.splitlines():
        if linha.startswith("##"):
            atual = linha[2:].strip()
            partes[atual] = ""
        elif atual:
            partes[atual] += linha + "\n"
    return {x: apk.versao_no_aparelho(partes.get(x, "")) for x in pacotes}


def texto_versao(versao, codigo):
    if versao is False:
        return "não consegui ler (o aparelho não respondeu)"
    if versao is None and codigo is None:
        return "n\u00e3o instalado"
    return "%s (c\u00f3digo %s)" % (versao or "?", codigo if codigo is not None else "?")


def aplica_adb_lembrado(informado, cfg):
    """Se o usuario já escolheu trocar de porta pelo aviso, usa o adb.exe e a porta lembrados
    (salvo se --adb foi passado ou o ambiente já define ADB_SERVER_PORT)."""
    exe, porta = cfg.get("adb_exe"), cfg.get("adb_porta")
    if informado or not exe or not porta or not os.path.isfile(exe) or os.environ.get("ADB_SERVER_PORT"):
        return None
    os.environ["ADB_SERVER_PORT"] = str(porta)
    return exe


def vigia_porta_adb(app, info):
    """Enquanto não há aparelho pronto, confere se ele esta em outro servidor adb (outra porta)
    e oferece a troca uma vez. So consulta servidores já no ar (não sobe nenhum)."""
    time.sleep(3)
    while not app.cap.parar:
        if not any(x["estado"] == "device" for x in app.cap.aparelhos) and app.adb_porta == info["porta"]:
            sug = adb_servidor.sugestao(info, adb_servidor.servidores([info["porta"]]))
            if sug:
                porta = sug["porta"]
                app.resultados.put((lambda rc, s: app.mostra_aviso_acao(sug["texto"], "Usar a porta %d" % porta, lambda: app.troca_adb(info["exe"], porta)), 0, ""))
                return
        time.sleep(15)


def main():
    ap = argparse.ArgumentParser(description="Visualizador e controle desktop de tela Android.")
    ap.add_argument("--serial", default="", help="serial adb; vazio = o único aparelho conectado")
    ap.add_argument("--adb", default="", help="caminho do adb (padrão: o do Android SDK)")
    ap.add_argument("--intervalo-min", type=float, default=0.15, help="pausa minima entre capturas (s)")
    ap.add_argument("--abrir-memoria", action="store_true", help="abre direto o monitor de memória")
    ap.add_argument("--abrir-arquivos", action="store_true", help="abre direto o gerenciador de arquivos")
    ap.add_argument("--diagnostico", action="store_true", help="grava um relatorio de ambiente em %%TEMP%%\\vision-diagnostico.txt e sai")
    ap.add_argument("--abrir-app", action="store_true", help="abre direto o painel do app e do aparelho")
    a = ap.parse_args()
    cfg = carregar_config()
    aplica_tema(cfg)
    adb_inf = aplica_adb_lembrado(a.adb, cfg)
    if a.diagnostico:
        adb_d = adb_inf or achar_adb(a.adb or None)
        info = adb_servidor.analisa_adb(adb_d) if adb_d else None
        achados = adb_servidor.servidores([info["porta"]]) if info else {}
        sug = adb_servidor.sugestao(info, achados) if info else None
        linhas = [
            "Vision %s - diagnostico" % VERSAO,
            "python/exe: %s (frozen=%s)" % (sys.version.split()[0], getattr(sys, "frozen", False)),
            "Pillow: %s" % (Image is not None),
            "PyAV (modo video): %s" % (av.__version__ if av is not None else "ausente"),
            "injetor (espelha-input.jar): %s" % os.path.isfile(caminho_recurso("espelha-input.jar")),
            "icone: %s" % os.path.isfile(caminho_recurso("icone.ico")),
            "adb: %s (versão %s)" % (adb_d, versao_adb(adb_d) if adb_d else "-"),
            "porta do servidor adb: %s%s" % (info["porta"] if info else "-", " (wrapper de %s)" % info["exe"] if info and info["wrapper"] else ""),
            "aparelhos: %s" % (listar_aparelhos(adb_d) if adb_d else []),
            "servidores adb no ar: %s" % achados,
            "aviso de porta: %s" % (sug["texto"] if sug else "nenhum"),
            "outros adb em execução: %s" % adb_em_execucao(),
        ]
        destino = os.path.join(tempfile.gettempdir(), "vision-diagnostico.txt")
        with open(destino, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")
        return 0

    if os.name == "nt":  # nitidez em telas com escala de DPI
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vision.App")
        except Exception:
            pass
    root = tk.Tk()
    root.withdraw()
    if Image is None:
        messagebox.showerror("Vision", "Pillow não esta instalado.\nInstale com: pip install pillow")
        return 2
    adb = adb_inf or achar_adb(a.adb or None)
    if not adb:
        messagebox.showerror("Vision", "adb não encontrado.\nInstale o Android SDK platform-tools ou use --adb <caminho>.")
        return 2
    versao = versao_adb(adb)
    aviso = ""
    info = adb_servidor.analisa_adb(adb)
    nome_cap = cfg.get("captura", "V\u00eddeo r\u00e1pido")
    modo, perfil = MODOS_CAPTURA.get(NOMES_ANTIGOS_CAPTURA.get(nome_cap, nome_cap), ("video", "rapido"))
    if modo == "video" and av is None:
        modo = "quadros"
    cap = Captura(adb, a.serial, a.intervalo_min, modo, perfil)
    cap.ips = list(cfg.get("ips") or [])
    cap.start()
    root.deiconify()
    app = App(root, cap, versao, aviso)
    app.adb_porta = info["porta"]
    threading.Thread(target=vigia_porta_adb, args=(app, info), daemon=True).start()

    def checa_adb_duplo():
        real = info["exe"]  # um wrapper .cmd chama o adb.exe real: esse nao e "outro adb"
        outros = [x for x in adb_em_execucao() if os.path.normcase(os.path.abspath(x)) != os.path.normcase(os.path.abspath(real))]
        if outros:
            texto = (
                "Há outro adb em execução (%s). Se for de versão diferente do usado aqui (%s), os dois "
                "derrubam o servidor um do outro. Feche o outro se a conexão oscilar. (clique para dispensar)" % ("; ".join(outros), versao)
            )
            app.resultados.put((lambda rc, s: app.mostra_aviso(texto), 0, ""))  # a UI consome na propria thread

    threading.Thread(target=checa_adb_duplo, daemon=True).start()
    if a.abrir_memoria:
        root.after(1500, app.abre_memoria)
    if a.abrir_arquivos:
        root.after(1500, app.abre_arquivos)
    if a.abrir_app:
        root.after(1500, app.abre_painel)
    root.mainloop()
    cap.parar = True
    return 0


if __name__ == "__main__":
    sys.exit(main())

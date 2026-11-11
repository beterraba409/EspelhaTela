# -*- coding: utf-8 -*-
"""Registro de diagnostico do video (%APPDATA%\\Vision\\video.log).

Serve para descobrir de onde vem uma travada: do aparelho (parou de mandar quadros), do PC (o
video chegou mas ficou esperando para ser decodificado/desenhado) ou do reinicio da gravacao.

- eventos: inicio e fim de cada gravacao, troca sem pausa, falhas;
- resumo a cada 10 s com video: quadros recebidos, tempo de decodificar e de desenhar, video acumulado;
- resposta lenta: mais de 0,3 s entre um toque e o primeiro quadro depois dele;
- dados do aparelho: codificador de video, processador e quadros que o proprio Android desenha.

Sem Tkinter: testavel em testes_sem_tela.py.
"""
import datetime
import os
import re
import threading
import time

PAUSA = 0.3  # s entre um toque e o proximo quadro que ja se percebe como travada
SEM_RESPOSTA = 5.0  # s: mais que isso, o toque provavelmente nao mudou nada na tela (nao e travada)
FILA_PC = 64 * 1024  # bytes de video esperando no PC: acima disso, o PC nao estava dando conta
RESUMO = 10.0  # s entre resumos
LIMITE = 1024 * 1024  # bytes do arquivo antes de girar para video.log.1


class RegistroVideo:
    def __init__(self, caminho, relogio=time.time):
        self.caminho = caminho
        self.relogio = relogio
        self.lock = threading.Lock()
        self._zera()
        self.t_resumo = relogio()
        self.t_toque = 0.0
        self.t_quadro = None
        self.aguardando = None  # hora do toque que ainda espera o primeiro quadro
        self.pausas_total = 0

    def _zera(self):
        self.n_quadros = 0
        self.decod = []
        self.desenho = []
        self.fila_max = 0
        self.pausas = 0
        self.pausas_aparelho = 0
        self.pausas_pc = 0
        self.n_toques = 0
        self.toques_sem_mudanca = 0

    # ---- escrita
    def _escreve(self, texto):
        try:
            os.makedirs(os.path.dirname(self.caminho), exist_ok=True)
            if os.path.isfile(self.caminho) and os.path.getsize(self.caminho) > LIMITE:
                os.replace(self.caminho, self.caminho + ".1")
            agora = datetime.datetime.fromtimestamp(self.relogio()).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            with open(self.caminho, "a", encoding="utf-8") as f:
                f.write("%s  %s\n" % (agora, texto))
        except OSError:
            pass  # diagnostico nunca derruba o video

    def evento(self, texto):
        with self.lock:
            self._escreve(texto)

    # ---- medidas
    def toque(self):
        """Um toque na tela: a resposta e medida ate o primeiro quadro que chegar depois dele."""
        with self.lock:
            self.t_toque = self.relogio()
            if self.aguardando is None:
                self.aguardando = self.t_toque
            self.n_toques += 1

    def quadro(self, decod_ms, fila_bytes=0):
        """Chamado a cada quadro decodificado. fila_bytes: video que ainda esperava no PC."""
        agora = self.relogio()
        with self.lock:
            self.n_quadros += 1
            self.decod.append(decod_ms)
            self.fila_max = max(self.fila_max, fila_bytes)
            self.t_quadro = agora
            if self.aguardando is None:
                return
            # tempo entre o toque e o primeiro quadro depois dele (a tela parada antes do toque nao conta)
            resposta, self.aguardando = agora - self.aguardando, None
            if resposta < PAUSA:
                return
            if resposta > SEM_RESPOSTA:
                self.toques_sem_mudanca += 1
                self._escreve("toque sem mudanca na tela por %.1f s (toque numa area sem acao?)" % resposta)
                return
            self.pausas += 1
            self.pausas_total += 1
            if fila_bytes >= FILA_PC or decod_ms >= 50:
                self.pausas_pc += 1
                causa = "PC: havia %d KB de video esperando, decodificar levou %.0f ms" % (fila_bytes / 1024, decod_ms)
            else:
                self.pausas_aparelho += 1
                causa = "aparelho: nada chegou nesse tempo (o aparelho nao mandou quadros)"
            self._escreve("RESPOSTA LENTA: %.1f s entre o toque e o proximo quadro. Causa provavel: %s" % (resposta, causa))

    def aparelho(self, texto):
        """Dados lidos do proprio aparelho (processador, quadros desenhados pelo Android)."""
        with self.lock:
            self._escreve("aparelho: " + texto)

    def teve_uso(self, janela=12.0):
        """Houve toque ou quadro nos ultimos segundos (vale medir o aparelho; tela parada, nao)."""
        return self.relogio() - max(self.t_toque, self.t_quadro or 0.0) < janela

    def desenhou(self, ms):
        with self.lock:
            self.desenho.append(ms)

    def periodico(self):
        """Grava o resumo a cada RESUMO segundos (so quando houve video)."""
        agora = self.relogio()
        with self.lock:
            if agora - self.t_resumo < RESUMO:
                return
            dur = agora - self.t_resumo
            self.t_resumo = agora
            if self.n_quadros:
                def med_max(v):
                    return (sum(v) / len(v), max(v)) if v else (0.0, 0.0)
                dm, dx = med_max(self.decod)
                wm, wx = med_max(self.desenho)
                self._escreve("resumo %.0f s: %d quadros (%.1f fps) | decodificar %.1f/%.0f ms | desenhar %.1f/%.0f ms "
                              "| video acumulado no PC ate %d KB | respostas lentas: %d (aparelho %d, PC %d) em %d toques" % (
                                  dur, self.n_quadros, self.n_quadros / dur, dm, dx, wm, wx, self.fila_max / 1024,
                                  self.pausas, self.pausas_aparelho, self.pausas_pc, self.n_toques))
            self._zera()


def comeca_com_inicio_de_quadro(dados):
    """O bloco do H.264 (Annex B) comeca num codigo de inicio de NAL? Se nao, o que veio antes estava incompleto."""
    return dados.startswith(b"\x00\x00\x01") or dados.startswith(b"\x00\x00\x00\x01")


def bytes_na_fila(proc):
    """Bytes de video que chegaram do aparelho e ainda nao foram lidos (so Windows)."""
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes
        disp = wintypes.DWORD(0)
        h = msvcrt.get_osfhandle(proc.stdout.fileno())
        if ctypes.windll.kernel32.PeekNamedPipe(wintypes.HANDLE(h), None, 0, None, ctypes.byref(disp), None):
            return disp.value
    except Exception:  # noqa: BLE001
        pass
    return 0


# ---- leitura de dados do aparelho (texto vindo do adb shell)
_SOFTWARE = ("OMX.google.", "c2.android.", "OMX.SEC.avc.sw", "c2.google.")

# codificadores declarados pelo Android (lido uma vez por aparelho)
COMANDO_CODIFICADORES = "cat /vendor/etc/media_codecs*.xml /odm/etc/media_codecs*.xml /system/etc/media_codecs*.xml 2>/dev/null"

# codificador que a gravacao atual abriu: o proprio screenrecord anota no logcat (MediaCodec "init name(...)",
# "Component Allocated (...)" ou Codec2 "Created component [...]"). Le sem limpar o logcat de ninguem.
COMANDO_CODIFICADOR_EM_USO = (
    r'''p=$(pidof screenrecord | awk '{print $NF}'); '''
    r'''[ -n "$p" ] && logcat -d --pid=$p 2>/dev/null | grep -E 'init name\(|Component Allocated|Created component' | tail -5'''
)


def codificador_em_uso(saida, conhecidos):
    """Nome do codificador que aparece por ultimo no logcat do screenrecord (entre os conhecidos), ou None."""
    achado = None
    for linha in (saida or "").splitlines():
        for nome in re.findall(r"[\(\[]([A-Za-z0-9_.]+)[\)\]]", linha):
            if nome in conhecidos:
                achado = nome
    return achado


# uma amostra a cada 10 s de uso: app em primeiro plano (a janela em foco ou, se ela nao for de app, o app
# em primeiro plano), quadros que ele desenhou desde a amostra anterior
# (o reset zera a contagem) e o processador do screenrecord, do surfaceflinger (desenho da tela) e do app
COMANDO_AMOSTRA = (
    r'''f=$(dumpsys window 2>/dev/null | grep -E 'mCurrentFocus|mFocusedApp'); '''
    r'''p=$(echo "$f" | sed -n 's|.* u0 \([^/ ]*\)/.*|\1|p' | head -1); '''
    r'''echo "##pkg $p"; '''
    r'''if [ -n "$p" ]; then dumpsys gfxinfo "$p" reset 2>/dev/null | grep -E 'Total frames rendered|Janky frames'; fi; '''
    r'''echo '##top'; '''
    r'''top -b -n 1 -d 1 -s 1 -o %CPU,ARGS 2>/dev/null | grep -E "screenrecord|surfaceflinger|${p:-nada}" | head -8'''
)


def le_amostra(saida):
    """(pacote, (quadros, com_atraso), {processo: %CPU}) da saida de COMANDO_AMOSTRA."""
    pkg = ""
    m = re.search(r"##pkg (\S*)", saida or "")
    if m:
        pkg = m.group(1)
    partes = (saida or "").split("##top", 1)
    quadros = quadros_do_app(partes[0])
    cpu = cpu_dos_processos(partes[1] if len(partes) > 1 else "", ["screenrecord", "surfaceflinger", pkg])
    return pkg, quadros, cpu


def codificadores_h264(xml):
    """Codificadores H.264 (video/avc) declarados nos media_codecs*.xml: [(nome, eh_software)], na ordem."""
    saida = []
    for bloco in re.findall(r"<Encoders>(.*?)</Encoders>", xml or "", re.S):
        for m in re.finditer(r'<MediaCodec\b([^>]*)>(.*?)</MediaCodec>|<MediaCodec\b([^>]*)/>', bloco, re.S):
            attrs = m.group(1) or m.group(3) or ""
            corpo = m.group(2) or ""
            nome = re.search(r'name="([^"]+)"', attrs)
            tipo = re.search(r'type="([^"]+)"', attrs)
            tipos = [tipo.group(1)] if tipo else re.findall(r'<Type\s+name="([^"]+)"', corpo)
            if nome and "video/avc" in tipos:
                n = nome.group(1)
                if n not in [x for x, _ in saida]:
                    saida.append((n, n.startswith(_SOFTWARE) or ".sw." in n.lower()))
    return saida


def quadros_do_app(gfxinfo):
    """(total, com_atraso) de 'dumpsys gfxinfo <pacote>'; (None, None) se nao houver."""
    tot = re.search(r"Total frames rendered:\s*(\d+)", gfxinfo or "")
    jank = re.search(r"Janky frames:\s*(\d+)", gfxinfo or "")
    if not tot:
        return None, None
    return int(tot.group(1)), (int(jank.group(1)) if jank else 0)


def cpu_dos_processos(top, nomes):
    """{nome: %CPU} das linhas de 'top -b -n 1 -o %CPU,ARGS' que contem cada nome (soma se houver varias)."""
    uso = {}
    for linha in (top or "").splitlines():
        partes = linha.split(None, 1)
        if len(partes) < 2:
            continue
        try:
            cpu = float(partes[0].rstrip("%"))
        except ValueError:
            continue
        if partes[1].startswith(("grep ", "sh -c", "top ")):
            continue  # o proprio comando de medida, nao o processo medido
        for n in nomes:
            if n and n in partes[1]:
                uso[n] = uso.get(n, 0.0) + cpu
    return uso

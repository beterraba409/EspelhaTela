# -*- coding: utf-8 -*-
"""Registro de diagnostico do video (%APPDATA%\\Vision\\video.log).

Serve para descobrir de onde vem uma travada: do aparelho (parou de mandar quadros), do PC (o
video chegou mas ficou esperando para ser decodificado/desenhado) ou do reinicio da gravacao.

- eventos: inicio e fim de cada gravacao, troca sem pausa, falhas;
- resumo a cada 10 s com video: quadros recebidos, tempo de decodificar e de desenhar, video acumulado;
- pausa percebida: mais de 0,3 s sem quadro logo depois de um toque (a tela deveria ter mudado).

Sem Tkinter: testavel em testes_sem_tela.py.
"""
import datetime
import os
import threading
import time

PAUSA = 0.3  # s sem quadro que ja se percebe como travada
JANELA_TOQUE = 1.5  # s depois de um toque em que a tela deveria mudar
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
        self.pausas_total = 0

    def _zera(self):
        self.n_quadros = 0
        self.decod = []
        self.desenho = []
        self.fila_max = 0
        self.pausas = 0
        self.pausas_aparelho = 0
        self.pausas_pc = 0

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
        self.t_toque = self.relogio()

    def quadro(self, decod_ms, fila_bytes=0):
        """Chamado a cada quadro decodificado. fila_bytes: video que ainda esperava no PC."""
        agora = self.relogio()
        with self.lock:
            self.n_quadros += 1
            self.decod.append(decod_ms)
            self.fila_max = max(self.fila_max, fila_bytes)
            anterior, self.t_quadro = self.t_quadro, agora
            if anterior is None:
                return
            pausa = agora - anterior
            # pausa percebida: a pessoa tocou pouco antes de (ou durante) o tempo sem quadro
            if pausa >= PAUSA and anterior - JANELA_TOQUE <= self.t_toque <= agora:
                self.pausas += 1
                self.pausas_total += 1
                if fila_bytes >= FILA_PC or decod_ms >= 50:
                    self.pausas_pc += 1
                    causa = "PC: havia %d KB de video esperando, decodificar levou %.0f ms" % (fila_bytes / 1024, decod_ms)
                else:
                    self.pausas_aparelho += 1
                    causa = "aparelho: nada chegou nesse tempo (o aparelho nao mandou quadros)"
                self._escreve("PAUSA de %.1f s logo apos um toque. Causa provavel: %s" % (pausa, causa))

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
                              "| video acumulado no PC ate %d KB | pausas apos toque: %d (aparelho %d, PC %d)" % (
                                  dur, self.n_quadros, self.n_quadros / dur, dm, dx, wm, wx, self.fila_max / 1024,
                                  self.pausas, self.pausas_aparelho, self.pausas_pc))
            self._zera()


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

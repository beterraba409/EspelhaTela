# -*- coding: utf-8 -*-
"""Gravacao da tela espelhada em .mp4 (video H.264) ou .gif (animacao curta).

Usa os quadros que o Vision ja recebe e desenha (nada a mais no aparelho, sem disputar o screenrecord).
A codificacao roda numa thread propria com fila curta: se o PC atrasar, quadros da gravacao sao
pulados, mas o espelho na tela nunca espera por ela.
"""

import fractions
import queue
import threading
import time

FPS_MP4 = 30
FPS_GIF = 10
LARGURA_GIF = 360
LIMITE_GIF = 60  # s: GIF fica pesado rapido (e vive na memoria ate salvar)


def par(n):
    """O H.264 com yuv420p exige largura e altura pares."""
    n = int(n)
    return max(2, n - n % 2)


def nome_do_tempo(segundos):
    s = int(segundos)
    return "%02d:%02d" % (s // 60, s % 60)


class Gravacao:
    """`quadro(fr)` a cada quadro mostrado (av.VideoFrame ou PIL.Image); `parar()` termina e salva.
    `ao_fim(caminho, erro, motivo)` e chamado da thread de gravacao quando o arquivo fica pronto."""

    def __init__(self, caminho, formato, ao_fim=None):
        assert formato in ("mp4", "gif")
        self.caminho, self.formato, self.ao_fim = caminho, formato, ao_fim
        self.fps = FPS_MP4 if formato == "mp4" else FPS_GIF
        self.q = queue.Queue(maxsize=8)
        self.ativo = True
        self.t0 = None
        self.t_ultimo = -1.0
        self.ultimo = None  # ultimo quadro visto, gravado no fim para a tela parada durar ate o stop
        self.ultimo_na_fila = True
        self.gravados = 0
        self.pulados = 0
        self.erro = ""
        self.motivo = ""
        self.thread = threading.Thread(target=self._roda, daemon=True)
        self.thread.start()

    def duracao(self):
        return 0.0 if self.t0 is None else time.monotonic() - self.t0

    def quadro(self, fr):
        if not self.ativo or fr is None:
            return
        agora = time.monotonic()
        if self.t0 is None:
            self.t0 = agora
        t = agora - self.t0
        if self.formato == "gif" and t > LIMITE_GIF:
            return self.parar("limite")
        self.ultimo, self.ultimo_na_fila = (fr, t), False
        if t - self.t_ultimo < 1.0 / self.fps:
            return  # mais rapido que o necessario para o arquivo
        self._enfileira(fr, t)

    def _enfileira(self, fr, t):
        try:
            self.q.put_nowait((fr, t))
            self.t_ultimo, self.ultimo_na_fila = t, True
        except queue.Full:
            self.pulados += 1

    def parar(self, motivo="parado"):
        if not self.ativo:
            return
        self.ativo = False
        self.motivo = motivo
        fim = self.duracao()
        if self.ultimo is not None:
            self.q.put((self.ultimo[0], max(self.ultimo[1], fim)))  # a tela parada no fim tambem conta
        self.q.put(None)

    # ---- thread de codificacao
    def _roda(self):
        try:
            (self._grava_mp4 if self.formato == "mp4" else self._grava_gif)()
        except Exception as e:  # noqa: BLE001
            self.erro = str(e)[:200] or type(e).__name__
            self.ativo = False
        if self.ao_fim:
            self.ao_fim(self.caminho, self.erro, self.motivo)

    def _itens(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            yield item

    def _grava_mp4(self):
        import av
        saida = stream = None
        ultimo_pts = -1
        try:
            for fr, t in self._itens():
                if not isinstance(fr, av.VideoFrame):
                    fr = av.VideoFrame.from_image(fr)
                if stream is None:
                    saida = av.open(self.caminho, "w", options={"movflags": "+faststart"})
                    stream = saida.add_stream("libx264", rate=self.fps,
                                              options={"preset": "veryfast", "crf": "23", "tune": "zerolatency"})
                    stream.width, stream.height = par(fr.width), par(fr.height)
                    stream.pix_fmt = "yuv420p"
                    stream.codec_context.time_base = fractions.Fraction(1, 1000)
                pts = max(int(t * 1000), ultimo_pts + 1)
                novo = fr.reformat(width=stream.width, height=stream.height, format="yuv420p")
                novo.pts, novo.time_base = pts, fractions.Fraction(1, 1000)
                ultimo_pts = pts
                for pkt in stream.encode(novo):
                    saida.mux(pkt)
                self.gravados += 1
            if stream is None:
                raise RuntimeError("nenhum quadro chegou durante a gravação")
            for pkt in stream.encode(None):
                saida.mux(pkt)
        finally:
            if saida is not None:
                saida.close()

    def _grava_gif(self):
        from PIL import Image
        quadros, tempos = [], []
        for fr, t in self._itens():
            img = fr.to_image() if hasattr(fr, "to_image") else fr
            if img.width > LARGURA_GIF:
                img = img.resize((LARGURA_GIF, max(1, round(img.height * LARGURA_GIF / img.width))), Image.BILINEAR)
            quadros.append(img.convert("RGB").quantize(colors=256, method=Image.Quantize.FASTOCTREE))
            tempos.append(t)
            self.gravados += 1
        if not quadros:
            raise RuntimeError("nenhum quadro chegou durante a gravação")
        # duracao de cada quadro = ate o proximo (o ultimo fica 1 s, para a animacao nao recomecar de supetao)
        duracoes = [max(20, int((b - a) * 1000)) for a, b in zip(tempos, tempos[1:])] + [1000]
        quadros[0].save(self.caminho, save_all=True, append_images=quadros[1:], duration=duracoes, loop=0, optimize=False)

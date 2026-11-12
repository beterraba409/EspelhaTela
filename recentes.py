# -*- coding: utf-8 -*-
"""Os ultimos segundos do espelho, sempre na memoria, para o Reportar bug ter o video de antes do clique.

Guarda quadros reduzidos em JPEG (8 por segundo, ate 480 px de altura): ~10 MB para 30 s e pouco
processador. A conversao roda numa thread propria com fila curta (o espelho nunca espera por ela).
"""

import collections
import fractions
import io
import queue
import threading
import time

SEGUNDOS = 30
FPS = 8
ALTURA_MAX = 480
QUALIDADE = 70
REPETE_MS = 500  # num trecho parado, o ultimo quadro e repetido a cada meio segundo


class UltimosSegundos:
    def __init__(self, segundos=SEGUNDOS, fps=FPS, altura_max=ALTURA_MAX):
        self.segundos, self.fps, self.altura_max = segundos, fps, altura_max
        self.quadros = collections.deque()  # (instante, bytes jpeg)
        self.lock = threading.Lock()
        self.q = queue.Queue(maxsize=3)
        self.ativo = True
        self.t_ultimo = 0.0
        self._conv = None
        threading.Thread(target=self._roda, daemon=True).start()

    def quadro(self, fr):
        """Chamado a cada quadro mostrado (av.VideoFrame ou PIL.Image); guarda so FPS por segundo."""
        if not self.ativo or fr is None:
            return
        agora = time.monotonic()
        if agora - self.t_ultimo < 1.0 / self.fps:
            return
        try:
            self.q.put_nowait((agora, fr))
            self.t_ultimo = agora
        except queue.Full:
            pass

    def _roda(self):
        while True:
            agora, fr = self.q.get()
            try:
                if hasattr(fr, "to_image"):  # conversor desta thread (o do quadro e compartilhado com a tela)
                    if self._conv is None:
                        from av.video.reformatter import VideoReformatter
                        self._conv = VideoReformatter()
                    w, h = fr.width, fr.height
                    if h > self.altura_max:  # reduz e converte numa passada so (antes: RGB cheio e depois reduzir)
                        w, h = max(2, round(w * self.altura_max / h)), self.altura_max
                    img = self._conv.reformat(fr, width=w, height=h, format="rgb24", interpolation="AREA").to_image()
                else:
                    img = fr
                if img.height > self.altura_max:
                    img = img.resize((max(2, round(img.width * self.altura_max / img.height)), self.altura_max))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, "JPEG", quality=QUALIDADE)
                with self.lock:
                    self.quadros.append((agora, buf.getvalue()))
                    while self.quadros and agora - self.quadros[0][0] > self.segundos:
                        self.quadros.popleft()
            except Exception:  # noqa: BLE001  (um quadro ruim nao derruba a memoria)
                pass

    def duracao(self):
        with self.lock:
            return 0.0 if len(self.quadros) < 2 else self.quadros[-1][0] - self.quadros[0][0]

    def bytes_usados(self):
        with self.lock:
            return sum(len(b) for _, b in self.quadros)

    def congela(self):
        """Copia do que esta guardado agora (o momento do bug), para salvar depois sem pressa."""
        with self.lock:
            return list(self.quadros)

    def limpa(self):
        with self.lock:
            self.quadros.clear()


def salva_mp4(quadros, caminho, ate=None):
    """Grava em MP4 os quadros congelados, no tempo real em que chegaram. O ultimo dura ate `ate`
    (instante do clique em Reportar bug), para o video terminar na tela do momento."""
    import av
    from PIL import Image
    if not quadros:
        raise ValueError("nenhum quadro guardado")
    t0 = quadros[0][0]
    primeira = Image.open(io.BytesIO(quadros[0][1]))
    larg, alt = primeira.width - primeira.width % 2, primeira.height - primeira.height % 2
    tb = fractions.Fraction(1, 1000)
    with av.open(caminho, "w", options={"movflags": "+faststart"}) as saida:
        st = saida.add_stream("libx264", rate=FPS, options={"preset": "veryfast", "crf": "23", "tune": "zerolatency"})
        st.width, st.height, st.pix_fmt = larg, alt, "yuv420p"
        st.codec_context.time_base = tb
        itens = list(quadros)
        if ate is not None and ate > itens[-1][0]:
            itens.append((ate, itens[-1][1]))
        ultimo, anterior = -1, None
        for t, jpeg in itens:
            pts = max(int((t - t0) * 1000), ultimo + 1)
            if anterior is not None:  # tela parada: repete o quadro (a duracao do MP4 fica certa em qualquer player)
                for extra in range(ultimo + REPETE_MS, pts - REPETE_MS // 2, REPETE_MS):
                    rep = anterior.reformat(format="yuv420p")
                    rep.pts, rep.time_base = extra, tb
                    for pkt in st.encode(rep):
                        saida.mux(pkt)
            img = Image.open(io.BytesIO(jpeg)).convert("RGB")
            if img.size != (larg, alt):
                from gravacao import encaixa
                img = encaixa(img, larg, alt)  # o aparelho girou dentro dos 30 s: sem esticar
            fr = av.VideoFrame.from_image(img).reformat(width=larg, height=alt, format="yuv420p")
            fr.pts, fr.time_base, ultimo, anterior = pts, tb, pts, fr
            for pkt in st.encode(fr):
                saida.mux(pkt)
        for pkt in st.encode(None):
            saida.mux(pkt)
    return len(quadros)

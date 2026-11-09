"""Gera icone.ico a partir de icone-fonte.png (quadrada, fundo transparente). Rodado pelo compilar.bat.

Icone de verdade: cada tamanho e preparado para o seu uso. De 64 px para cima vai a imagem inteira; de
48 px para baixo (barra de tarefas, titulo da janela, Explorer em lista) vai um recorte fechado no rosto,
reduzido em etapas e com nitidez reforcada, para nao virar borrao. Inclui os tamanhos que o Windows usa
em cada escala de tela (16, 20, 24, 32, 40, 48, 64, 128, 256).

Com --previa, grava icone-previa.png com todos os tamanhos lado a lado (e ampliados 4x os pequenos).
"""
import sys

from PIL import Image, ImageDraw, ImageFilter

GRANDES = [256, 128, 64]
PEQUENOS = [48, 40, 32, 24, 20, 16]
# recorte do rosto (fracao da imagem fonte): da joia na testa ate o queixo, centrado
RECORTE_ROSTO = (0.155, 0.10, 0.845, 0.79)


def _reduz_em_etapas(img, t):
    """Reduz pela metade ate perto do alvo e termina com LANCZOS: menos serrilhado e menos borrao."""
    while img.width >= t * 2:
        img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
    return img.resize((t, t), Image.LANCZOS)


def _circulo(t, k=4):
    m = Image.new("L", (t * k, t * k), 0)
    ImageDraw.Draw(m).ellipse((0, 0, t * k - 1, t * k - 1), fill=255)
    return m.resize((t, t), Image.LANCZOS)


def grande(fonte, t):
    img = _reduz_em_etapas(fonte, t)
    return img.filter(ImageFilter.UnsharpMask(radius=0.8, percent=50, threshold=1))


def pequeno(fonte, t):
    w, h = fonte.size
    x1, y1, x2, y2 = RECORTE_ROSTO
    rosto = fonte.crop((int(w * x1), int(h * y1), int(w * x2), int(h * y2))).convert("RGBA")
    fundo = Image.new("RGBA", rosto.size, (16, 34, 52, 255))  # o azul-noite do circulo original
    fundo.alpha_composite(rosto)
    img = _reduz_em_etapas(fundo, t)
    img = img.filter(ImageFilter.UnsharpMask(radius=0.6, percent=110 if t <= 24 else 80, threshold=0))
    img.putalpha(_circulo(t))
    return img


def gera(fonte):
    return {t: (grande(fonte, t) if t in GRANDES else pequeno(fonte, t)) for t in GRANDES + PEQUENOS}


def main():
    fonte = Image.open("icone-fonte.png").convert("RGBA")
    imgs = gera(fonte)
    tamanhos = sorted(imgs, reverse=True)
    imgs[256].save("icone.ico", sizes=[(t, t) for t in tamanhos], append_images=[imgs[t] for t in tamanhos[1:]])
    if "--previa" in sys.argv:
        larg = sum(tamanhos) + 20 * len(tamanhos) + 4 * sum(PEQUENOS[-3:]) + 60
        previa = Image.new("RGBA", (larg, 276), (240, 240, 240, 255))
        x = 10
        for t in tamanhos:
            previa.paste(imgs[t], (x, 10), imgs[t])
            x += t + 20
        for t in PEQUENOS[-3:]:  # 24, 20 e 16 ampliados 4x, para ver os pixels
            z = imgs[t].resize((t * 4, t * 4), Image.NEAREST)
            previa.paste(z, (x, 10), z)
            x += t * 4 + 20
        previa.save("icone-previa.png")
    print("icone.ico gerado:", ", ".join(str(t) for t in tamanhos))


if __name__ == "__main__":
    main()

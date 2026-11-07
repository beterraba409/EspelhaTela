"""Gera icone.ico (um celular estilizado) com Pillow. Rodado pelo compilar.bat."""
from PIL import Image, ImageDraw

N = 256
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((20, 20, 236, 236), radius=44, fill=(28, 28, 30, 255))
d.rounded_rectangle((78, 36, 178, 220), radius=18, outline=(230, 230, 230, 255), width=9, fill=(74, 31, 99, 255))
d.rounded_rectangle((96, 58, 160, 190), radius=6, fill=(124, 77, 255, 255))
d.ellipse((118, 198, 138, 212), fill=(230, 230, 230, 255))
img.save("icone.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icone.ico gerado")

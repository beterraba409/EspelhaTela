# -*- coding: utf-8 -*-
"""Verificacoes sem tela e sem aparelho: python testes_sem_tela.py"""

import os
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adb_servidor as A  # noqa: E402
import seletor as S  # noqa: E402

WRAPPER = r"""@echo off
setlocal
set "ADB_EXE=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
set "DEFAULT_ADB_SERVER_PORT=5038"
set "HAS_PORT_ARG="
for %%A in (%*) do (
  if /I "%%~A"=="-P" set "HAS_PORT_ARG=1"
)
if defined ADB_SERVER_PORT (
  "%ADB_EXE%" -P %ADB_SERVER_PORT% %*
  exit /b %ERRORLEVEL%
)
"%ADB_EXE%" -P %DEFAULT_ADB_SERVER_PORT% %*
"""

XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node index="0" text="" resource-id="" class="android.widget.FrameLayout" content-desc="" clickable="false" bounds="[0,0][720,1280]">
 <node index="0" text="" resource-id="button-teste-conexao" class="android.view.ViewGroup" content-desc="" clickable="true" bounds="[60,540][400,620]">
  <node index="0" text="Conexão com a internet" resource-id="title-button-teste-conexao" class="android.widget.TextView" content-desc="title-button-teste-conexao" clickable="false" bounds="[100,560][380,600]" />
 </node>
 <node index="1" text="" resource-id="item-lista" class="android.view.ViewGroup" content-desc="" clickable="true" bounds="[0,700][720,760]">
  <node index="0" text="R$ 10,00 &quot;promo&quot;" resource-id="" class="android.widget.TextView" content-desc="" clickable="false" bounds="[10,710][300,750]" />
 </node>
 <node index="2" text="" resource-id="item-lista" class="android.view.ViewGroup" content-desc="" clickable="true" bounds="[0,760][720,820]" />
 <node index="3" text="" resource-id="com.exemplo.app:id/campo" class="android.widget.EditText" content-desc="" clickable="true" bounds="[0,900][720,980]" />
 <node index="4" text="" resource-id="" class="android.view.View" content-desc="" clickable="false" bounds="[0,0][0,0]" />
</node>
</hierarchy>UI hierchary dumped to: /dev/tty"""


class TestAdbServidor(unittest.TestCase):
    def _wrapper(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".CMD", delete=False, encoding="utf-8")
        f.write(WRAPPER)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_wrapper_porta_e_exe(self):
        info = A.analisa_adb(self._wrapper(), env={"LOCALAPPDATA": r"C:\U\AppData\Local"})
        self.assertTrue(info["wrapper"])
        self.assertEqual(info["porta"], 5038)
        self.assertEqual(info["exe"], r"C:\U\AppData\Local\Android\Sdk\platform-tools\adb.exe")

    def test_wrapper_respeita_ambiente(self):
        info = A.analisa_adb(self._wrapper(), env={"LOCALAPPDATA": "C:\\x", "ADB_SERVER_PORT": "5037"})
        self.assertEqual(info["porta"], 5037)

    def test_exe_comum(self):
        self.assertEqual(A.analisa_adb(r"C:\sdk\adb.exe", env={})["porta"], 5037)
        self.assertEqual(A.analisa_adb(r"C:\sdk\adb.exe", env={"ADB_SERVER_PORT": "6000"})["porta"], 6000)
        self.assertFalse(A.analisa_adb(r"C:\sdk\adb.exe", env={})["wrapper"])

    def test_consulta_servidor_falso(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        porta = srv.getsockname()[1]
        recebido = []

        def atende():
            c, _ = srv.accept()
            recebido.append(c.recv(64))
            corpo = b"0123abcd\tdevice\n192.168.1.7:5555\toffline\n"
            c.sendall(b"OKAY" + b"%04x" % len(corpo) + corpo)
            c.close()

        t = threading.Thread(target=atende)
        t.start()
        lista = A.aparelhos_no_servidor(porta)
        t.join()
        srv.close()
        self.assertEqual(recebido[0], b"000chost:devices")
        self.assertEqual(lista, [{"serial": "0123abcd", "estado": "device"}, {"serial": "192.168.1.7:5555", "estado": "offline"}])

    def test_porta_sem_servidor(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
        s.close()
        self.assertIsNone(A.aparelhos_no_servidor(porta, timeout=0.5))

    def test_sugestao(self):
        info = {"caminho": r"C:\bin\adb.CMD", "exe": "adb.exe", "porta": 5038, "wrapper": True}
        dev = [{"serial": "0123abcd", "estado": "device"}]
        sug = A.sugestao(info, {5037: dev, 5038: []})
        self.assertEqual(sug["porta"], 5037)
        self.assertIn("porta 5038, sem aparelhos", sug["texto"])
        self.assertIn("0123abcd", sug["texto"])
        self.assertIn("que nem esta no ar", A.sugestao(info, {5037: dev})["texto"])
        self.assertIsNone(A.sugestao(info, {5037: dev, 5038: dev}))  # a porta em uso ja tem aparelho
        self.assertIsNone(A.sugestao(info, {5037: [{"serial": "x", "estado": "unauthorized"}], 5038: []}))
        self.assertIsNone(A.sugestao(info, {5038: []}))

    def test_servidores_so_os_no_ar(self):
        achados = A.servidores([6001], consulta=lambda p: [] if p in (5037, 6001) else None)
        self.assertEqual(achados, {5037: [], 6001: []})


class TestSeletor(unittest.TestCase):
    def setUp(self):
        self.nos = S.le_nos(S.extrai_xml(XML))

    def _idx(self, rid=None, texto=None):
        return next(i for i, n in enumerate(self.nos) if (rid is None or n["resource-id"] == rid) and (texto is None or n["text"] == texto))

    def test_extrai_xml(self):
        self.assertTrue(S.extrai_xml(XML).endswith("</hierarchy>"))
        self.assertEqual(S.extrai_xml("ERROR: could not get idle state."), "")

    def test_menor_no_no_ponto(self):
        i = S.no_no_ponto(self.nos, 200, 580)
        self.assertEqual(self.nos[i]["resource-id"], "title-button-teste-conexao")
        self.assertEqual(self.nos[S.no_no_ponto(self.nos, 70, 545)]["resource-id"], "button-teste-conexao")
        self.assertIsNone(S.no_no_ponto(self.nos, 9999, 9999))

    def test_seletores_testid_e_clicavel(self):
        i = self._idx("title-button-teste-conexao")
        sug = dict(S.seletores(self.nos, i, (720, 1280)))
        self.assertEqual(sug["id"], '- tapOn:\n    id: "title-button-teste-conexao"')
        self.assertEqual(sug["id do elemento clicavel que contem este"], '- tapOn:\n    id: "button-teste-conexao"')
        self.assertEqual(sug["texto"], '- tapOn: "Conexão com a internet"')
        self.assertNotIn("accessibilityLabel", sug)  # content-desc igual ao testID nao vira sugestao
        self.assertEqual(sug["ponto (ultimo recurso)"], '- tapOn:\n    point: "33%,45%"')

    def test_id_repetido_ganha_index_e_texto_escapado(self):
        i = self._idx(texto='R$ 10,00 "promo"')
        sug = S.seletores(self.nos, i, (720, 1280))
        rotulo, yaml = sug[0]
        self.assertIn("do elemento pai", rotulo)
        self.assertIn("2 elementos com esse id", rotulo)
        self.assertEqual(yaml, '- tapOn:\n    id: "item-lista"\n    index: 0')
        self.assertIn(("texto", '- tapOn: "R$ 10,00 \\"promo\\""'), sug)
        j = self.nos.index(next(n for n in self.nos if n["bounds"] == (0, 760, 720, 820)))
        self.assertIn("index: 1", S.seletores(self.nos, j, (720, 1280))[0][1])

    def test_view_nativa_e_campo(self):
        i = self._idx("com.exemplo.app:id/campo")
        sug = dict(S.seletores(self.nos, i, (720, 1280)))
        self.assertEqual(sug["id"], '- tapOn:\n    id: "campo"')
        self.assertIn("digitar no campo", sug)

    def test_texto_do_filho_quando_clica_no_botao(self):
        i = self._idx("button-teste-conexao")
        self.assertIn(("texto", '- tapOn: "Conexão com a internet"'), S.seletores(self.nos, i, (720, 1280)))

    def test_ler_tela_com_plano_b(self):
        chamadas = []

        def rodar(cmd, timeout=0):
            chamadas.append(cmd[-1])
            if cmd[-1].startswith("uiautomator dump /dev/tty"):
                return 0, "", "dump para /dev/tty nao suportado"
            return 0, XML, ""

        nos, erro = S.ler_tela(rodar, "adb", "x")
        self.assertEqual(erro, "")
        self.assertEqual(len(nos), len(self.nos))
        self.assertEqual(len(chamadas), 2)

    def test_ler_tela_falha(self):
        nos, erro = S.ler_tela(lambda cmd, timeout=0: (1, "ERROR: could not get idle state.", ""), "adb", "x")
        self.assertIsNone(nos)
        self.assertIn("idle state", erro)


try:
    import av  # noqa: E402
    from PIL import Image  # noqa: E402
    import espelha_tela as E  # noqa: E402
except ImportError:  # sem PyAV/Pillow: as verificacoes do video ficam de fora
    E = None


@unittest.skipIf(E is None, "PyAV ou Pillow ausentes")
class Video(unittest.TestCase):
    def _cap(self):
        return E.Captura("adb", "x", 0.1)

    def _quadro(self, w=32, h=64):
        img = Image.new("RGB", (w, h), (200, 30, 30))
        return av.VideoFrame.from_image(img).reformat(format="yuv420p")

    def test_quadro_do_video_so_converte_quando_pedido(self):
        cap = self._cap()
        self.assertIsNone(cap.tamanho)
        fr = self._quadro()
        cap._av = fr  # como o leitor do video faz
        self.assertEqual(cap.tamanho, (32, 64))
        self.assertIsNone(cap._img)  # saber o tamanho nao converte nada
        img = cap.frame
        self.assertEqual(img.size, (32, 64))
        self.assertIs(cap.frame, img)  # mesmo quadro: conversao reaproveitada
        cap._av = self._quadro()
        self.assertIsNot(cap.frame, img)  # quadro novo: conversao nova

    def test_imagem_ja_sai_no_tamanho_da_janela(self):
        cap = self._cap()
        cap._av = self._quadro()
        ampliada = cap.imagem(64, 128)
        reduzida = cap.imagem(8, 16)
        self.assertEqual((ampliada.size, reduzida.size), ((64, 128), (8, 16)))
        r, g, b = ampliada.getpixel((30, 60))
        self.assertTrue(r > 150 and g < 80 and b < 80, (r, g, b))  # cor preservada na conversao YUV -> RGB

    def test_modo_quadros_continua_com_pil(self):
        cap = self._cap()
        cap._av = self._quadro()
        cap.frame = Image.new("RGB", (10, 20))  # o modo quadros grava uma PIL.Image e descarta o video
        self.assertEqual(cap.tamanho, (10, 20))
        self.assertEqual(cap.imagem(20, 40).size, (20, 40))
        cap.frame = None
        self.assertIsNone(cap.tamanho)
        self.assertIsNone(cap.imagem(20, 40))

    def test_video_que_falhou_e_tentado_de_novo(self):
        cap = self._cap()
        cap.modo = "video"
        self.assertFalse(cap._hora_de_tentar_video())  # nunca falhou
        cap.video_ok, cap.falhas_video, cap.t_falha_video = False, 1, E.time.time()
        self.assertFalse(cap._hora_de_tentar_video())  # acabou de falhar
        cap.t_falha_video -= 31
        self.assertTrue(cap._hora_de_tentar_video())  # 30 s depois
        esperas = []
        for n in (1, 2, 3, 4, 9):
            cap.falhas_video = n
            esperas.append(cap.espera_video())
        self.assertEqual(esperas, [30, 60, 120, 240, 300])
        cap.modo = "quadros"  # quem escolheu quadros nao recebe video a forca
        self.assertFalse(cap._hora_de_tentar_video())

    def test_trocar_de_aparelho_zera_a_falha(self):
        cap = self._cap()
        cap.video_ok, cap.falhas_video = False, 3
        cap.trocar("outro")
        self.assertTrue(cap.video_ok)
        self.assertEqual(cap.falhas_video, 0)


@unittest.skipIf(E is None, "PyAV ou Pillow ausentes")
class Dados(unittest.TestCase):
    def test_configuracao_da_pasta_antiga_vem_junto(self):
        with tempfile.TemporaryDirectory() as base:
            os.makedirs(os.path.join(base, "EspelhaTela"))
            with open(os.path.join(base, "EspelhaTela", "config.json"), "w", encoding="utf-8") as f:
                f.write('{"adb_porta": 5037}')
            antes = os.environ.get("APPDATA")
            os.environ["APPDATA"] = base
            try:
                self.assertEqual(E.carregar_config(), {"adb_porta": 5037})  # copiada para %APPDATA%\Vision
                self.assertTrue(os.path.isfile(os.path.join(base, "Vision", "config.json")))
                E.salvar_config({"adb_porta": 5038})  # a partir dai so a pasta nova e usada
                self.assertEqual(E.carregar_config(), {"adb_porta": 5038})
            finally:
                if antes is None:
                    del os.environ["APPDATA"]
                else:
                    os.environ["APPDATA"] = antes


import atualizacao as U  # noqa: E402


class Atualizacao(unittest.TestCase):
    RELEASES = [
        {"tag_name": "v1.3", "name": "Vision 1.3", "draft": True, "assets": [{"name": "Vision-Setup-1.3.exe"}]},
        {"tag_name": "v1.10", "name": "Vision 1.10", "body": " novidades ", "html_url": "https://x/v1.10",
         "assets": [{"name": "Vision-1.10.zip"}, {"name": "Vision-Setup-1.10.exe", "size": 9, "url": "https://api/a/1",
                                                    "browser_download_url": "https://dl/Vision-Setup-1.10.exe"}]},
        {"tag_name": "v1.9", "assets": [{"name": "Vision-Setup-1.9.exe"}]},
        {"tag_name": "v2.0", "assets": [{"name": "Vision-2.0.zip"}]},  # sem instalador: nao serve
        {"tag_name": "outro-v9.0", "assets": [{"name": "Vision-Setup-9.0.exe"}]},  # outro utilitario do repo
    ]

    def test_versoes(self):
        self.assertTrue(U.mais_nova("1.10", "1.9"))
        self.assertTrue(U.mais_nova("v1.2.1", "1.2"))
        self.assertFalse(U.mais_nova("1.2", "1.2"))
        self.assertFalse(U.mais_nova("", "1.0"))

    def test_escolhe_a_mais_nova_publicada_com_instalador(self):
        r = U.escolhe_release(self.RELEASES, "v", "Vision-Setup-")
        self.assertEqual((r["versao"], r["arquivo"], r["notas"]), ("1.10", "Vision-Setup-1.10.exe", "novidades"))
        self.assertEqual(r["url_publica"], "https://dl/Vision-Setup-1.10.exe")
        self.assertIsNone(U.escolhe_release(self.RELEASES, "vision-v", "Vision-SmartPOS-Setup-"))

    def test_token_nao_segue_para_outro_servidor(self):
        h = U.SemTokenNoRedirecionamento()
        req = U._pedido("https://api.github.com/repos/a/b/releases/assets/1", "segredo", "application/octet-stream")
        mesmo = h.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/outro")
        fora = h.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/x")
        self.assertIn("Authorization", mesmo.headers)
        self.assertNotIn("Authorization", fora.headers)
        self.assertNotIn("Authorization", fora.unredirected_hdrs)


@unittest.skipIf(E is None, "PyAV ou Pillow ausentes")
class OutroProcesso(unittest.TestCase):
    def test_ambiente_limpo_tira_as_variaveis_do_pyinstaller(self):
        antes = dict(os.environ)
        os.environ.update({"_PYI_APPLICATION_HOME_DIR": "C:/sumiu", "_MEIPASS2": "C:/sumiu", "PATH_TESTE": "fica"})
        try:
            amb = E.ambiente_limpo()
        finally:
            os.environ.clear()
            os.environ.update(antes)
        self.assertNotIn("_PYI_APPLICATION_HOME_DIR", amb)
        self.assertNotIn("_MEIPASS2", amb)
        self.assertEqual(amb["PATH_TESTE"], "fica")
        self.assertEqual(amb["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_ajudante_espera_para_e_so_depois_instala(self):
        cmd = E.comando_de_instalacao("C:/Temp/Vision-Setup-9.9.exe", "C:/Program Files/O'Vision/Vision.exe", [10, 20, 0])
        self.assertEqual(cmd[0], "powershell.exe")
        script = cmd[-1]
        espera, para, instala = script.index("Wait-Process -Id 10,20"), script.index("Stop-Process -Force"), script.index("Start-Process")
        self.assertTrue(espera < para < instala)  # nesta ordem
        self.assertIn("'C:/Program Files/O''Vision/Vision.exe'", script)  # aspas simples escapadas
        self.assertIn("'/SILENT','/SUPPRESSMSGBOXES','/NORESTART'", script)


import apk as K  # noqa: E402

APK_REAL = r"C:\codigos_fontes\automacao-maestro\scripts\apks\Getnet P2-A7\getnet-linx-postos-smartpos.1.17.0.2026-09-21_17-40.apk"


class Apk(unittest.TestCase):
    def test_versao_no_aparelho(self):
        saida = "    versionCode=11701000 minSdk=24 targetSdk=34\n    versionName=1.17.1\n    versionCode=1 minSdk=1\n"
        self.assertEqual(K.versao_no_aparelho(saida), ("1.17.1", 11701000))  # a primeira e a que vale
        self.assertEqual(K.versao_no_aparelho(""), (None, None))

    def test_tipo_de_mudanca(self):
        self.assertEqual(K.tipo_de_mudanca(47, None), "nova")
        self.assertEqual(K.tipo_de_mudanca(47, 46), "atualizacao")
        self.assertEqual(K.tipo_de_mudanca(47, 47), "mesma")
        self.assertEqual(K.tipo_de_mudanca(46, 47), "downgrade")

    def test_manifesto_invalido(self):
        with self.assertRaises(ValueError):
            K.le_manifesto(b"<manifest/>")

    @unittest.skipUnless(os.path.isfile(APK_REAL), "APK de exemplo ausente nesta maquina")
    def test_apk_real_igual_ao_aapt(self):
        i = K.le_apk(APK_REAL)  # conferido com: aapt2 dump badging
        self.assertEqual((i["pacote"], i["versao"], i["codigo"]), ("com.smartposv2.getnet", "1.17.0", 11700000))
        self.assertEqual(K.le_apks([APK_REAL])["pacote"], "com.smartposv2.getnet")


import diagnostico_video as DV  # noqa: E402


class DiagnosticoVideo(unittest.TestCase):
    def _registro(self):
        self.t = [1000.0]
        pasta = tempfile.mkdtemp()
        self.arq = os.path.join(pasta, "video.log")
        return DV.RegistroVideo(self.arq, relogio=lambda: self.t[0])

    def _texto(self):
        return open(self.arq, encoding="utf-8").read() if os.path.isfile(self.arq) else ""

    def test_pausa_depois_de_toque_vem_do_aparelho(self):
        r = self._registro()
        r.quadro(2)
        r.toque()
        self.t[0] += 0.8  # 0,8 s sem quadro logo depois do toque, sem video esperando no PC
        r.quadro(2, fila_bytes=0)
        self.assertIn("RESPOSTA LENTA: 0.8 s", self._texto())
        self.assertIn("aparelho", self._texto())

    def test_pausa_com_video_acumulado_e_do_pc(self):
        r = self._registro()
        r.quadro(2)
        r.toque()
        self.t[0] += 0.6
        r.quadro(80, fila_bytes=300 * 1024)
        self.assertIn("PC: havia 300 KB", self._texto())

    def test_tela_parada_sem_toque_nao_e_travada(self):
        r = self._registro()
        r.quadro(2)
        self.t[0] += 5  # ninguem tocou: tela parada nao manda quadro, e isso e normal
        r.quadro(2)
        self.assertNotIn("PAUSA", self._texto())

    def test_resumo_a_cada_10_s(self):
        r = self._registro()
        for _ in range(30):
            self.t[0] += 0.05
            r.quadro(3)
        r.desenhou(4)
        self.t[0] += 10
        r.periodico()
        self.assertIn("resumo", self._texto())
        self.assertIn("30 quadros", self._texto())


class DiagnosticoAparelho(unittest.TestCase):
    def _registro(self):
        self.t = [1000.0]
        self.arq = os.path.join(tempfile.mkdtemp(), "video.log")
        return DV.RegistroVideo(self.arq, relogio=lambda: self.t[0])

    def _texto(self):
        return open(self.arq, encoding="utf-8").read() if os.path.isfile(self.arq) else ""

    def test_tela_parada_e_depois_toque_mede_so_a_resposta(self):
        r = self._registro()
        r.quadro(2)
        self.t[0] += 30  # 30 s de tela parada (normal)
        r.toque()
        self.t[0] += 0.5  # o aparelho respondeu em 0,5 s
        r.quadro(2)
        self.assertIn("RESPOSTA LENTA: 0.5 s", self._texto())
        self.assertNotIn("30.", self._texto())

    def test_toque_sem_mudanca_na_tela_nao_e_travada(self):
        r = self._registro()
        r.quadro(2)
        r.toque()
        self.t[0] += 8
        r.quadro(2)
        self.assertIn("toque sem mudanca", self._texto())
        self.assertNotIn("RESPOSTA LENTA", self._texto())

    def test_uso_recente(self):
        r = self._registro()
        self.assertFalse(r.teve_uso())
        r.toque()
        self.assertTrue(r.teve_uso())
        self.t[0] += 20
        self.assertFalse(r.teve_uso())

    def test_amostra_do_aparelho(self):
        saida = ("##pkg com.smartposv2.linxtef\nTotal frames rendered: 240\nJanky frames: 30 (12.50%)\n##top\n"
                 "12.5 surfaceflinger\n 9.3 com.smartposv2.linxtef\n 3.1 screenrecord --output-format=h264 -\n"
                 " 0.0 grep -E screenrecord|surfaceflinger|com.smartposv2.linxtef\n"
                 " 5.0 sh -c screenrecord '--output-format=h264'\n")
        pkg, quadros, cpu = DV.le_amostra(saida)
        self.assertEqual(pkg, "com.smartposv2.linxtef")
        self.assertEqual(quadros, (240, 30))
        self.assertEqual(cpu, {"surfaceflinger": 12.5, "com.smartposv2.linxtef": 9.3, "screenrecord": 3.1})  # sem o grep e o sh

    def test_codificadores(self):
        xml = ('<MediaCodecs><Encoders>'
               '<MediaCodec name="OMX.qcom.video.encoder.avc" type="video/avc"><Limit name="size"/></MediaCodec>'
               '<MediaCodec name="c2.android.avc.encoder"><Type name="video/avc"/></MediaCodec>'
               '<MediaCodec name="OMX.qcom.video.encoder.hevc" type="video/hevc"/>'
               '</Encoders><Decoders><MediaCodec name="OMX.qcom.video.decoder.avc" type="video/avc"/></Decoders></MediaCodecs>')
        self.assertEqual(DV.codificadores_h264(xml), [("OMX.qcom.video.encoder.avc", False), ("c2.android.avc.encoder", True)])


class CodificadorEmUso(unittest.TestCase):
    CONHECIDOS = {"c2.android.avc.encoder": True, "OMX.MTK.VIDEO.ENCODER.AVC": False}

    def test_le_o_codificador_do_logcat(self):
        saida = ("11-10 16:02:11.909 20198 20198 I MediaCodec: (0xaf1c9000) init name(OMX.MTK.VIDEO.ENCODER.AVC)\n"
                 "11-10 16:02:12.226 20198 20200 I MediaCodec: (0xaf1c9000) Component Allocated (OMX.MTK.VIDEO.ENCODER.AVC)\n")
        self.assertEqual(DV.codificador_em_uso(saida, self.CONHECIDOS), "OMX.MTK.VIDEO.ENCODER.AVC")

    def test_codec2(self):
        saida = "I CCodec  : Created component [c2.android.avc.encoder]\n"
        self.assertEqual(DV.codificador_em_uso(saida, self.CONHECIDOS), "c2.android.avc.encoder")

    def test_logcat_restrito(self):
        self.assertIsNone(DV.codificador_em_uso("", self.CONHECIDOS))
        self.assertIsNone(DV.codificador_em_uso("I MediaCodec: init name(outro.codec)", self.CONHECIDOS))


if __name__ == "__main__":
    unittest.main(verbosity=1)

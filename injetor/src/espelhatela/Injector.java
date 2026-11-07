package espelhatela;

import android.content.ClipData;
import android.os.IBinder;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.MotionEvent;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;
import java.net.URLDecoder;
import java.net.URLEncoder;

/**
 * Injetor de eventos de entrada, sempre ativo, para o EspelhaTela.
 *
 * Roda no aparelho via app_process (usuario shell) e le comandos de texto na entrada padrao,
 * uma linha por comando. Como o processo fica vivo, cada toque custa microssegundos em vez de
 * subir uma JVM (adb shell input tap leva de 0,5 a 1 s em aparelhos fracos).
 *
 *   d x y            toque para baixo (ACTION_DOWN)
 *   m x y            movimento (ACTION_MOVE)
 *   u x y            toque solto (ACTION_UP)
 *   k codigo         tecla (KeyEvent) pressionada e solta
 *   t texto          texto, codificado como URL (%20 para espaco)
 *   s x1 y1 x2 y2 ms deslize completo
 *   c texto          poe o texto (URL) na area de transferencia do aparelho; responde "CLIPSET ok|falhou"
 *   v texto          cola o texto: area de transferencia + KEYCODE_PASTE (com acentos); sem
 *                    area de transferencia, digita o texto tecla a tecla
 *   g                le a area de transferencia; responde "CLIP texto" (URL) ou "CLIP" vazio
 *   q                encerra
 *
 * Responde "READY" ao iniciar e "ERR ..." quando um comando falha.
 * Mesma tecnica do scrcpy: InputManager.injectInputEvent por reflexao.
 */
public final class Injector {
    private static Object inputManager;
    private static Method inject;
    private static long downTime;
    private static final int MODE_ASYNC = 0;
    private static final int KEYCODE_PASTE = 279;
    private static final String PACOTE = "com.android.shell";
    private static Object clipboard;

    public static void main(String[] args) throws Exception {
        try {
            Method getInstance = Class.forName("android.hardware.input.InputManager").getDeclaredMethod("getInstance");
            inputManager = getInstance.invoke(null);
            inject = inputManager.getClass().getMethod("injectInputEvent", InputEvent.class, int.class);
        } catch (Throwable t) {
            System.out.println("ERR init " + t);
            System.out.flush();
            return;
        }
        System.out.println("READY");
        System.out.flush();

        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        String linha;
        while ((linha = in.readLine()) != null) {
            linha = linha.trim();
            if (linha.isEmpty()) {
                continue;
            }
            try {
                if (!comando(linha)) {
                    return;
                }
            } catch (Throwable t) {
                System.out.println("ERR " + linha + " -> " + t);
                System.out.flush();
            }
        }
    }

    private static boolean comando(String linha) throws Exception {
        String[] p = linha.split(" ", 2);
        String c = p[0];
        String resto = p.length > 1 ? p[1] : "";
        switch (c) {
            case "d":
                downTime = SystemClock.uptimeMillis();
                toque(MotionEvent.ACTION_DOWN, f(resto, 0), f(resto, 1), downTime, 1.0f);
                break;
            case "m":
                toque(MotionEvent.ACTION_MOVE, f(resto, 0), f(resto, 1), downTime, 1.0f);
                break;
            case "u":
                toque(MotionEvent.ACTION_UP, f(resto, 0), f(resto, 1), downTime, 0.0f);
                break;
            case "k":
                tecla(Integer.parseInt(resto.trim()));
                break;
            case "t":
                texto(URLDecoder.decode(resto, "UTF-8"));
                break;
            case "s":
                final String[] a = resto.split(" ");
                new Thread(new Runnable() {
                    public void run() {
                        try {
                            deslizar(Float.parseFloat(a[0]), Float.parseFloat(a[1]), Float.parseFloat(a[2]), Float.parseFloat(a[3]), Long.parseLong(a[4]));
                        } catch (Throwable t) {
                            System.out.println("ERR swipe " + t);
                            System.out.flush();
                        }
                    }
                }).start();
                break;
            case "c":
                boolean ok = clipPoe(URLDecoder.decode(resto, "UTF-8"));
                responde("CLIPSET " + (ok ? "ok" : "falhou"));
                break;
            case "v":
                String txt = URLDecoder.decode(resto, "UTF-8");
                if (clipPoe(txt)) {
                    Thread.sleep(60);
                    tecla(KEYCODE_PASTE);
                } else {
                    texto(txt);
                }
                break;
            case "g":
                String lido = clipLe();
                responde(lido == null ? "CLIP" : "CLIP " + URLEncoder.encode(lido, "UTF-8").replace("+", "%20"));
                break;
            case "q":
                return false;
            default:
                System.out.println("ERR comando desconhecido: " + c);
                System.out.flush();
        }
        return true;
    }

    private static void responde(String s) {
        System.out.println(s);
        System.out.flush();
    }

    /** IClipboard do sistema por reflexao (como o scrcpy); null se o aparelho nao deixar. */
    private static Object clip() throws Exception {
        if (clipboard == null) {
            Class<?> sm = Class.forName("android.os.ServiceManager");
            IBinder b = (IBinder) sm.getMethod("getService", String.class).invoke(null, "clipboard");
            clipboard = Class.forName("android.content.IClipboard$Stub").getMethod("asInterface", IBinder.class).invoke(null, b);
        }
        return clipboard;
    }

    /**
     * Chama um metodo do IClipboard montando os argumentos pelo tipo: a assinatura muda a cada
     * versao do Android (pacote; + userId no 10; + attributionTag no 12; + deviceId no 14...).
     */
    private static Object chamaClip(String nome, ClipData dado) throws Exception {
        Object c = clip();
        Throwable ultimo = null;
        for (Method m : c.getClass().getMethods()) {
            if (!m.getName().equals(nome)) {
                continue;
            }
            Class<?>[] tipos = m.getParameterTypes();
            Object[] args = new Object[tipos.length];
            boolean primeiraString = true;
            boolean serve = true;
            for (int i = 0; i < tipos.length; i++) {
                if (tipos[i] == ClipData.class) {
                    args[i] = dado;
                } else if (tipos[i] == String.class) {
                    args[i] = primeiraString ? PACOTE : null;  // pacote; depois attributionTag
                    primeiraString = false;
                } else if (tipos[i] == int.class) {
                    args[i] = 0;  // userId 0 e deviceId 0 (aparelho principal)
                } else {
                    serve = false;
                }
            }
            if (!serve || (dado != null) != java.util.Arrays.asList(tipos).contains(ClipData.class)) {
                continue;
            }
            try {
                return m.invoke(c, args);
            } catch (Throwable t) {
                ultimo = t;
            }
        }
        throw new Exception("IClipboard." + nome + " indisponivel" + (ultimo != null ? ": " + ultimo.getCause() : ""));
    }

    private static boolean clipPoe(String s) {
        try {
            chamaClip("setPrimaryClip", ClipData.newPlainText("EspelhaTela", s));
            return true;
        } catch (Throwable t) {
            responde("ERR clip " + t);
            return false;
        }
    }

    private static String clipLe() {
        try {
            ClipData d = (ClipData) chamaClip("getPrimaryClip", null);
            if (d == null || d.getItemCount() == 0) {
                return null;
            }
            CharSequence t = d.getItemAt(0).getText();
            return t == null ? null : t.toString();
        } catch (Throwable t) {
            responde("ERR clip " + t);
            return null;
        }
    }

    private static float f(String resto, int i) {
        return Float.parseFloat(resto.trim().split(" ")[i]);
    }

    private static void injeta(InputEvent e) throws Exception {
        inject.invoke(inputManager, e, MODE_ASYNC);
    }

    private static void toque(int acao, float x, float y, long down, float pressao) throws Exception {
        long agora = SystemClock.uptimeMillis();
        MotionEvent ev = MotionEvent.obtain(down, agora, acao, x, y, pressao, 1.0f, 0, 1.0f, 1.0f, 0, 0);
        ev.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        try {
            injeta(ev);
        } finally {
            ev.recycle();
        }
    }

    private static void tecla(int codigo) throws Exception {
        long agora = SystemClock.uptimeMillis();
        KeyEvent d = new KeyEvent(agora, agora, KeyEvent.ACTION_DOWN, codigo, 0, 0, KeyCharacterMap.VIRTUAL_KEYBOARD, 0, 0, InputDevice.SOURCE_KEYBOARD);
        KeyEvent u = new KeyEvent(agora, agora, KeyEvent.ACTION_UP, codigo, 0, 0, KeyCharacterMap.VIRTUAL_KEYBOARD, 0, 0, InputDevice.SOURCE_KEYBOARD);
        injeta(d);
        injeta(u);
    }

    private static void texto(String s) throws Exception {
        KeyCharacterMap kcm = KeyCharacterMap.load(KeyCharacterMap.VIRTUAL_KEYBOARD);
        KeyEvent[] evs = kcm.getEvents(s.toCharArray());
        if (evs == null) {
            System.out.println("ERR texto sem mapeamento de teclas (acentos?)");
            System.out.flush();
            return;
        }
        for (KeyEvent e : evs) {
            injeta(e);
        }
    }

    private static void deslizar(float x1, float y1, float x2, float y2, long ms) throws Exception {
        long ini = SystemClock.uptimeMillis();
        toque(MotionEvent.ACTION_DOWN, x1, y1, ini, 1.0f);
        int passos = (int) Math.max(4, Math.min(30, ms / 16));
        for (int i = 1; i <= passos; i++) {
            float t = (float) i / passos;
            Thread.sleep(Math.max(1, ms / passos));
            toque(MotionEvent.ACTION_MOVE, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, ini, 1.0f);
        }
        toque(MotionEvent.ACTION_UP, x2, y2, ini, 0.0f);
    }
}

# Changelog

## 1.0 - primeira versão pública

- Espelho por vídeo H.264 (três perfis) ou por quadros, com plano B automático.
- Controle com injetor sempre ativo (toque, arraste, rolagem, teclado) e plano B pelo `adb shell input`.
- Seletor de identificador para o Maestro (F6): `id:`, `text:`, accessibilityLabel, `assertVisible`, `point:` e `index:`.
- Aviso de adb e porta: detecta wrapper `.cmd`/`.bat` ou `ADB_SERVER_PORT` em outro servidor e oferece a troca.
- Painel "App e aparelho" para qualquer app instalado, com favoritos e preparo do aparelho para automação.
- Instalar e desinstalar APK, gerenciador de arquivos, monitor de memória, exportação de logcat e conexão por IP.
- Executável único para Windows (`compilar.bat`) e verificações sem tela (`testes_sem_tela.py`).

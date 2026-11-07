# EspelhaTela - Roadmap

Ideias para as próximas versões. Sugestões e PRs são bem-vindos.

## Próximos

### Gravação e pacote de evidência de bug
- Gravar vídeo da tela e um "replay" dos últimos N segundos (o fluxo H.264 já chega ao PC, falta guardar).
- Captura anotada (seta, retângulo, texto) e um botão "Montar evidência" que junta print, vídeo, logcat do período,
  versão do app e dados do aparelho numa pasta ou zip.

### Vários aparelhos
- Vários aparelhos lado a lado, com a opção de repetir o mesmo clique em todos.
- Cuidado: limitar a taxa por aparelho para não disputar o adb com a automação.

### Ideias menores (sem ordem)
- Gravar um flow do Maestro a partir dos cliques feitos no espelho.
- Texto com acentos pelo teclado do PC (área de transferência ou teclado de apoio).
- Reiniciar o vídeo sozinho ao girar a tela; perfil de vídeo adaptativo conforme a carga do aparelho.
- Console de shell com histórico; encaminhamento de porta (`adb reverse`); abrir link ou deep link no aparelho;
  copiar e colar texto entre o PC e o aparelho.
- Assinatura digital do `.exe` e atualizador automático.

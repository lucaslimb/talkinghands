# Maestro — Instrumento Gestual Expressivo

> *"Conduza o som com as mãos como um maestro conduz sua orquestra."*

O **Maestro** é o modo mais expressivo do Talking Hands. Inspirado no theremin, mas com maior riqueza gestual, ele transforma movimentos contínuos e discretos das mãos em parâmetros musicais complexos em tempo real — pitch, vibrato, tremolo, timbre, volume, reverb, percussão e mais.

---

## Início rápido

```bash
python src/main.py -i "Maestro"
python src/main.py -i "Maestro" -t          # com trackers visíveis
python src/main.py -i "Maestro" -r 72030    # 720p @ 30fps
```

---

## Divisão de responsabilidades entre as mãos

| Mão | Papel | Eixos de controle |
|-----|-------|-------------------|
| **Direita** | Melodia e expressão tonal | Pitch · Pan · Timbre · Vibrato · Tremolo |
| **Esquerda** | Dinâmica e efeitos | Volume · Reverb · Chorus |

Qualquer das mãos pode disparar eventos percussivos com gestos rápidos.

---

## Mapeamento gestual completo

### Mão direita — melodia

| Gesto / Parâmetro | Controle gerado | Faixa |
|---|---|---|
| Posição vertical **Y** | Pitch (nota MIDI) | C3 (baixo) → C6 (alto) |
| Posição horizontal **X** | Pan estéreo (CC 10) | Esquerda → Direita |
| **Abertura da mão** | Timbre / brilho (CC 74) | Punho=escuro · Aberta=brilhante |
| **Oscilação rápida** 3,5–10 Hz | Vibrato (pitch LFO adaptativo) | Profundidade até ±1,5 semitons |
| **Oscilação lenta** 1–4 Hz | Tremolo (amplitude LFO) | Modulação de ±38% do volume |
| **Descida rápida** | Kick (canal 9, nota 36) | Trigger percussivo |
| **Lateral rápido** | Snare (canal 9, nota 38) | Trigger percussivo |

### Mão esquerda — expressão

| Gesto / Parâmetro | Controle gerado | Faixa |
|---|---|---|
| Posição vertical **Y** | Volume / Expression (CC 11) | Baixo=silencioso · Alto=forte |
| Posição horizontal **X** | Reverb send (CC 91) | Esquerda=seco · Direita=molhado |
| **Abertura da mão** | Chorus (CC 93) | Punho=sem · Aberta=máx chorus |
| **Fechar mão rapidamente** | Accent — velocity spike momentânea | Dura ~200ms, decaimento suave |
| **Abrir mão rapidamente** | Swell — boost temporário de reverb | Dura ~900ms, decaimento suave |

---

## Como funciona a detecção de vibrato e tremolo

O Maestro usa um **`OscillationDetector`** que analisa um buffer deslizante das posições verticais recentes da mão direita:

1. **Remove a componente DC** (tendência lenta) para isolar oscilações.
2. **Conta zero-crossings** do sinal centrado para estimar a frequência fundamental.
3. **Mede a amplitude** como desvio padrão × 2 (aproximação do pico a pico).

| Frequência detectada | Resultado |
|---|---|
| < 1 Hz ou > 10 Hz | Ignorado (ruído ou movimento intencional) |
| **1 – 4 Hz** | **Tremolo** — modula amplitude via LFO |
| **3,5 – 10 Hz** | **Vibrato** — modula pitch via bend LFO |
| Ambos coexistem | Tremolo e vibrato são independentes |

A velocidade e profundidade dos LFOs se adaptam em tempo real ao que o músico faz — sem necessidade de botões ou zonas.

---

## Gestos discretos (eventos percussivos)

Os gestos abaixo são detectados pelo **`DiscreteGestureDetector`** com cooldown de 280ms para evitar duplos disparos:

| Gesto | Condição | Evento |
|---|---|---|
| Descida rápida | `vy > 2.2 coord/s` | **KICK** — nota 36, canal 9 |
| Lateral rápido | `|vx| > 2.2 coord/s` | **SNARE** — nota 38, canal 9 |
| Fechar mão | taxa de fechamento `< -1.8/s` e abertura `< 30%` | **ACCENT** — sobe velocity |
| Abrir mão | taxa de abertura `> 1.8/s` e abertura `> 65%` | **SWELL** — boost de reverb |

> **Dica:** experimente combinar um kick da mão direita com um swell da mão esquerda para criar transições dramáticas.

---

## Suavização de sinais

Todo parâmetro contínuo passa por um **filtro EMA (Exponential Moving Average)** antes de ser enviado ao FluidSynth:

| Velocidade | Alpha | Uso |
|---|---|---|
| Slow | 0,08 | LFO de vibrato e tremolo (evita saltos) |
| Med | 0,15 | Pitch, pan, timbre, volume, reverb |
| Fast | 0,28 | Velocidade da mão (para detecção de gestos) |

Um alpha menor = mais suave, mais latência. Um alpha maior = mais responsivo, mais jitter.

---

## Arquitetura interna

```
src/expressions/maestro.py
│
├── SignalSmoother          — filtro EMA adaptativo por canal
├── OscillationDetector     — FFT leve via zero-crossings
├── GestureVelocityTracker  — velocidade 2D suavizada
├── DiscreteGestureDetector — debounce + threshold para eventos
│
├── _audio_worker()         — thread de consumo da fila de áudio
├── _trigger_perc()         — disparo percussivo com noteoff atrasado
├── _render_ui()            — painel pygame com barras e indicadores LFO
└── start_maestro()         — loop principal câmera + MediaPipe + FluidSynth
```

### Fluxo de dados

```
Webcam → CameraThread → MediaPipe Hands → HandFeatures
                                              │
                      ┌───────────────────────┤
                      │                       │
               Mão Direita               Mão Esquerda
               · Pitch / Pan             · Volume
               · Timbre                  · Reverb / Chorus
               · OscillationDetector     · DiscreteGestureDetector
               · DiscreteGestureDetector
                      │
                 audio_queue  ←──── _trigger_perc (drums)
                      │
                _audio_worker (thread)
                      │
                  FluidSynth  →  Saída de áudio em tempo real
```

---

## Canais MIDI usados

| Canal | Soundfont | Uso |
|---|---|---|
| **0** | `module_master.sf2` | Pad melódico (Warm Pad por padrão) |
| **9** | `NewDrums.sf2` | Percussão (kick, snare) |

---

## Controls da interface

| Tecla | Ação |
|---|---|
| `1` | Iniciar gravação |
| `2` | Parar gravação |
| `3` | Toggle playback da gravação |
| `0` | Ocultar / mostrar painel |
| `ESC` | Sair |

---

## Dicas de performance

- **Vibrato natural:** mova a mão direita em pequenas oscilações verticais (tipo trêmulo de violinista) a ~5–7 Hz. O sistema detecta e aplica automaticamente.
- **Crescendo suave:** levante a mão esquerda lentamente enquanto mantém a direita estável para fazer um crescendo sem vibrato.
- **Kick com swell:** descida rápida da mão direita + abertura rápida da esquerda cria um kick com cauda de reverb expansiva.
- **Melodia com tremolo:** oscilações lentas (~2 Hz) da mão direita geram tremolo expressivo — útil em notas longas.
- **Timbre dinâmico:** abrir e fechar a mão direita gradualmente enquanto sustenta uma nota modula o CC 74 (brightness), simulando um filtro passa-alta.

---

## Parâmetros ajustáveis no código

Todos os thresholds estão nas constantes do topo de `src/expressions/maestro.py` e podem ser calibrados conforme o músico e as condições de iluminação:

| Constante | Padrão | Descrição |
|---|---|---|
| `PITCH_LOW / PITCH_HIGH` | 48 / 84 | Faixa de pitch (C3..C6) |
| `VIB_FREQ_MIN / MAX` | 3,5 / 10,0 Hz | Janela de detecção de vibrato |
| `TREM_FREQ_MIN / MAX` | 1,0 / 5,0 Hz | Janela de detecção de tremolo |
| `VIB_MAX_DEPTH` | 1,5 st | Profundidade máxima de vibrato |
| `TREM_DEPTH` | 0,38 | Modulação máxima de amplitude |
| `KICK_VY_THRESHOLD` | 2,2 | Sensibilidade ao gestode kick |
| `SNARE_VX_THRESHOLD` | 2,2 | Sensibilidade ao gesto de snare |
| `GESTURE_COOLDOWN` | 0,28s | Tempo mínimo entre gestos iguais |
| `SMOOTH_MED` | 0,15 | Suavização de pitch e volume |

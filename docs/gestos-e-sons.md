# Talking Hands — Gestos e Sons

> Como os movimentos de braços e mãos são capturados e convertidos em som.

---

## Visão Geral da Captura

O sistema usa a câmera para capturar o vídeo em tempo real e processa cada frame com o **MediaPipe**:

- **MediaPipe Hands** — detecta até 21 pontos de referência (landmarks) por mão (palma, articulações, pontas dos dedos).
- **MediaPipe Pose** — detecta pontos do corpo inteiro, incluindo pés (usado no modo Bateria com kit completo).

Todos os landmarks são retornados em **coordenadas normalizadas** (0.0 a 1.0), onde:
- **X** vai da esquerda (0) para a direita (1) da tela.
- **Y** vai do topo (0) para a base (1) da tela.
- **Z** é uma estimativa de profundidade — valores menores indicam mão mais perto da câmera.

A imagem exibida na tela é **espelhada horizontalmente**, então o que o usuário vê como "direita" corresponde à mão direita do próprio usuário.

---

## Modo Arms (Theremin Multi-Eixo)

> Arquivo: `src/expressions/arms.py`  
> Instrumento padrão: **Warm Pad** (pode ser qualquer instrumento melódico)

O modo Arms transforma o espaço diante da câmera em um **instrumento contínuo**, sem teclas ou botões. A analogia mais próxima é a de um **theremin**, mas com muito mais dimensões de controle.

Cada mão controla um conjunto distinto de parâmetros musicais. Uma nota fica tocando continuamente enquanto a mão direita for visível; a mão esquerda modela o som em tempo real em paralelo.

---

### Mão Direita — Melodia

A mão direita é o "braço de melodia". Ela define **qual nota soar** e como essa nota **se comporta timbricamente**.

#### Eixo Y (vertical) → Altura da nota (Pitch)

| Posição da mão | Resultado |
|---|---|
| Mão no topo da tela (Y ≈ 0) | Nota mais aguda — **Dó 6 (MIDI 84)** |
| Mão no meio da tela | Nota intermediária — **Dó 4 (MIDI 60)** |
| Mão na base da tela (Y ≈ 1) | Nota mais grave — **Dó 3 (MIDI 48)** |

O pitch não é discreto: a nota sendo tocada é calculada como um **número decimal** (ex: 60.7). A parte inteira define a nota MIDI enviada, e a fração decimal é convertida em um **pitch bend fracional**, permitindo afinação microtonal contínua. Isso cria a sensação de "deslizar" entre as notas, característica do theremin.

**Por quê funciona assim?** O Y normalizado é invertido (1.0 - Y) e mapeado linearmente entre os valores MIDI 48 e 84, criando a correlação intuitiva "mão acima = som mais alto".

#### Eixo X (horizontal) → Velocidade do Vibrato

| Posição da mão | Resultado |
|---|---|
| Mão à esquerda (X ≈ 0) | Sem vibrato (0 Hz) |
| Mão à direita (X ≈ 1) | Vibrato máximo (**7 Hz**) |

O vibrato é implementado por um **oscilador LFO** (Low Frequency Oscillator) em software. A taxa do LFO é controlada pelo X da mão direita. O LFO modula o pitch bend continuamente com uma função seno, criando a oscilação periódica de altura típica do vibrato.

**Por quê X controla velocidade?** Porque a profundidade (quanto o pitch varia) vem de outro gesto (a inclinação da palma), separando os dois parâmetros do vibrato em dois eixos distintos e independentes.

#### Inclinação da Palma (palm roll) → Profundidade do Vibrato

| Posição da palma | Resultado |
|---|---|
| Palma plana, voltada para baixo | Profundidade 0 (sem oscilação de pitch) |
| Palma inclinada 90° (lateral) | Profundidade máxima (**± 1.5 semitons**) |

A inclinação é calculada pelo ângulo do vetor que vai do **MCP do indicador (lm[5])** até o **MCP do mindinho (lm[17])**. Quando a palma está plana, esse vetor é aproximadamente horizontal (ângulo ≈ 0). Quando a palma é girada, o ângulo aumenta.

O valor de profundidade multiplica a amplitude do seno do LFO antes de ser convertido em unidades de pitch bend.

#### Eixo Z (profundidade) → Brilho / Timbre (CC 74)

| Posição da mão | Resultado |
|---|---|
| Mão perto da câmera | Brilho alto — som mais brilhante/cortante |
| Mão longe da câmera | Brilho baixo — som mais encoberto/escuro |

A profundidade não é medida diretamente pela câmera, mas **inferida pelo tamanho aparente da mão**: uma mão mais próxima aparece maior. O sistema mede a distância euclidiana entre o pulso (lm[0]) e o MCP do dedo médio (lm[9]) em coordenadas normalizadas. Esse tamanho é mapeado entre um mínimo (`0.07`) e um máximo (`0.22`) para gerar um valor de 0 a 127.

Esse valor é enviado como **CC 74** (Brightness / Filter Cutoff), que na maioria dos soundfonts controla o filtro de brilho do timbre.

---

### Mão Esquerda — Expressão

A mão esquerda é o "braço de expressão". Ela não define notas, apenas **molda como o som é percebido**: volume, posição no espaço estéreo, reverberação e coro.

#### Eixo Y (vertical) → Volume (CC 11 — Expression)

| Posição da mão | Resultado |
|---|---|
| Mão no topo (Y ≈ 0) | Volume máximo (CC 11 = 127) |
| Mão na base (Y ≈ 1) | Volume zero (CC 11 = 0) |

O CC 11 (Expression) é preferido ao CC 7 (Volume) para controle contínuo em tempo real pois é projetado para variações expressivas durante a performance.

#### Eixo X (horizontal) → Panorama Estéreo (CC 10 — Pan)

| Posição da mão | Resultado |
|---|---|
| Mão à esquerda (X ≈ 0) | Som todo no canal esquerdo (CC 10 = 0) |
| Mão ao centro (X ≈ 0.5) | Som centralizado (CC 10 = 64) |
| Mão à direita (X ≈ 1) | Som todo no canal direito (CC 10 = 127) |

#### Eixo Z (profundidade) → Reverb (CC 91)

| Posição da mão | Resultado |
|---|---|
| Mão perto da câmera | Reverb alto — mais espaço/profundidade no som |
| Mão longe da câmera | Reverb baixo — som mais seco/direto |

Da mesma forma que na mão direita, a profundidade é estimada pelo tamanho aparente da mão. O valor mapeado é enviado como **CC 91** (Reverb Send Level).

#### Abertura dos Dedos → Chorus (CC 93)

| Estado da mão | Resultado |
|---|---|
| Mão fechada (punho) | Chorus zero (CC 93 = 0) |
| Mão aberta (espalmada) | Chorus máximo (CC 93 ≈ 80) |

A abertura é calculada pela **média da distância de cada ponta de dedo (lm[4, 8, 12, 16, 20]) ao pulso (lm[0])**. Esse valor é normalizado entre aproximadamente `0.08` (mão fechada) e `0.25` (mão completamente aberta).

O chorus cria um leve desafinamento em cópias do sinal, gerando a sensação de "vibratos" de timbre ou de múltiplos instrumentos tocando juntos.

---

### Suavização (Smoothing)

Todos os parâmetros passam por um **filtro de suavização exponencial** antes de serem enviados ao sintetizador:

```
valor_suavizado += fator × (novo_valor − valor_suavizado)
```

Os fatores são:
- Pitch: `0.15`
- Volume: `0.15`
- Demais CCs (vibrato, brilho, pan, reverb, chorus): `0.12`

Isso evita saltos abruptos quando a câmera perde rastreamento por um frame e previne "ziguezague" sonoro por tremulação de mão. O trade-off é uma leve inércia no controle.

---

### Ausência de Mão → Silêncio

Se a mão direita desaparecer do campo de visão por mais de **0.12 segundos**, a nota atual recebe um `noteoff` e a saída de áudio para. Ao reaparecer, a nota recorre normalmente a partir da posição atual.

---

## Modo Piano (Teclado Virtual)

> Arquivo: `src/instruments/keyboard.py`

O modo Piano projeta um **teclado virtual** na parte inferior da imagem. O usuário toca as teclas como em um piano real, mas interagindo com a câmera.

---

### A "Linha da Mesa"

Uma linha horizontal configura a posição da "superfície do teclado" na tela — chamada de **table_y** (padrão: 80% da altura da tela, ajustável). Essa linha divide a tela em:

- **Acima da linha**: zona de preparo (dedo visível, ainda não tocando).
- **Na/abaixo da linha**: zona de toque (nota disparada).

---

### Quais dedos são monitorados

São rastreados **5 dedos por mão**: polegar (4), indicador (8), médio (12), anelar (16) e mindinho (20) — usando os landmarks das pontas. Cada dedo age como um dedo independente no teclado, permitindo acordes.

---

### Ciclo de vida de um toque (máquina de estados por dedo)

Cada dedo passa pelos seguintes estados:

| Estado | Descrição |
|---|---|
| **IDLE** | Dedo abaixo da linha ou sem distância suficiente acima dela. Não arma o toque. |
| **ARMED** | Dedo está acima da linha com folga suficiente (`LIFT_THRESHOLD ≈ 0.02`). Pronto para tocar. |
| **TOUCHING** | Dedo cruzou a linha. Nota disparada. |

**IDLE → ARMED**: o dedo sobe acima da linha por uma distância mínima.  
**ARMED → TOUCHING**: o dedo desce até a linha (dentro de uma tolerância de `0.005`). A nota tocada é determinada pela **posição X** do dedo, que é mapeada na tecla correspondente do teclado virtual.  
**TOUCHING → ARMED**: o dedo sobe novamente um pouco acima da linha (`RELEASE_THRESHOLD ≈ 0.015`). A nota recebe `noteoff`.

Se o dedo some do rastreamento por mais de `0.1 s`, a nota é encerrada automaticamente para evitar notas "presas".

---

### Qual nota soa?

As teclas brancas e pretas são distribuídas uniformemente na largura da tela a partir de uma nota base (padrão: **Dó 3**, MIDI 48). A nota é escolhida pela posição X normalizada do dedo no momento do toque, priorizando teclas pretas se o dedo estiver sobre elas.

O trecho abaixo resume o mapeamento visual:

```
|  C  |C#|  D  |D#|  E  |  F  |F#| ... |
|_____|  |_____|  |_____|_____|  | ... |
←────────────── Largura total da tela ──────────────→
```

---

### Controle de Volume pela Barra Lateral

No lado direito da tela existe uma **barra de volume** vertical. O usuário posiciona o **dedo indicador** sobre ela e desliza para ajustar o volume entre -50 e +50. Abaixo de zero, o volume é controlado via CC 11 (Expression). Acima de zero, o ganho digital do sintetizador aumenta gradualmente até `2×`.

---

## Modo Bateria (Drums)

> Arquivo: `src/instruments/drums.py`

O modo Bateria projeta os **elementos de uma bateria** (prato, caixa, bumbo, etc.) como zonas interativas na tela. O usuário golpeia essas zonas com as mãos, e o sistema detecta o movimento descendente como uma batida.

---

### Como uma batida é detectada

O sistema rastreia o **polegar de cada mão** (landmark 4 — thumb tip) como cursor de toque. O raciocínio é que o polegar fica à frente do movimento natural de bater.

A detecção funciona assim:

1. **Cálculo do delta Y** (`dy = y_atual − y_anterior`): um `dy` positivo significa que a mão está descendo.
2. **Verificação de colisão**: a posição atual do cursor é comparada com cada zona de instrumento (elipses ou retângulos em coordenadas normalizadas).
3. **Disparo da batida**: se `dy > VELOCITY_THRESHOLD (0.002)` e o cursor está dentro de uma zona, a batida é acionada.
4. **Cooldown por posição**: após uma batida, outra só é acionada se o cursor se mover pelo menos **32 pixels** a partir do ponto de impacto (evita batidas duplas involuntárias).
5. **Cooldown por tempo**: intervalo mínimo de **45 ms** entre batidas no mesmo elemento.

**Por que usar o polegar?** Porque ele permanece visível durante movimentos de golpe e tende a ser o ponto mais avançado da mão em um toque de batida.

---

### Velocidade da batida (dinâmica)

A força do golpe (velocity MIDI, de 0 a 127) é calculada a partir de `dy`:

```
velocity = (dy − TOUCH_VELOCITY) × 10.000
```

Limitado a um mínimo de **50** e máximo de **127**. Isso garante que golpes mais fortes (mão descendo mais rápido) produzem sons mais altos, replicando a dinâmica de uma bateria real.

---

### Rearmamento após batida

Após bater, o cursor precisa:
- **Sair da zona** ou
- **Estar na metade superior** do elemento e **subir** (`dy < −VELOCITY_THRESHOLD`)

para que uma nova batida seja permitida. Isso impede que uma mão parada sobre a zona dispare múltiplas vezes.

---

### Elementos de Bateria e Zonas

Cada elemento possui:
- **Posição** (`pos`): coordenadas X, Y normalizadas do centro na tela.
- **Tamanho** (`axes`): semi-eixos horizontal e vertical em coordenadas normalizadas.
- **Forma** (`shape`): `ellipse` para pratos e tons, `rect` para bumbo, caixa e pedais.
- **Nota MIDI** associada (GM Percussion Channel 10):

| Elemento | Nome | Nota MIDI |
|---|---|---|
| Crash | CRASH | 49 |
| Ride | RIDE | 51 |
| Hi-Hat fechado | HI-HAT | 42 |
| Hi-Hat aberto | OPEN-HH | 46 |
| Snare (caixa) | SNARE | 38 |
| Tom alto | HI-TOM | 48 |
| Tom médio | MID-TOM | 47 |
| Tom baixo | LO-TOM | 45 |
| Floor Tom | FLOOR | 41 |
| Bumbo | KICK | 36 |
| Bumbo alt | KICK-ALT | 35 |
| Pedal Hi-Hat | HH-PEDAL | 44 |
| Rimshot | RIMSHOT | 37 |
| Splash | SPLASH | 55 |
| China | CHINA | 52 |
| Cowbell | COWBELL | 56 |
| Clap | CLAP | 39 |

---

### Pedais (Pé/Foot) — Kit Completo

No modelo de kit **"complete"**, o MediaPipe Pose rastreia os pés. O **tornozelo** ou **ponta do pé** é monitorado separadamente pelo estado `feet_state`. O comportamento é idêntico ao das mãos, mas com um cooldown de posição maior (**36 px**) para lidar com a menor precisão do rastreamento de pés.

Os elementos `foot_only: True` (Bumbo e Pedal de Hi-Hat) só são acionados por pés e ignoram colisões com as mãos.

---

### Customização do Layout

O usuário pode:
- **Arrastar** qualquer elemento pela tela (mouse ou toque).
- **Redimensionar** arrastando as bordas do elemento.
- **Remover** com clique direito do mouse.
- **Resetar** posições com a tecla `5`.

---

## Referência Rápida — Mapeamento por Modo

### Arms

| Gesto | Parâmetro | Efeito no Som |
|---|---|---|
| Mão D: altura (Y) | Pitch (nota) | mais alto = nota mais aguda |
| Mão D: horizontal (X) | Taxa de vibrato | mais à direita = vibrato mais rápido |
| Mão D: profundidade (Z) | Brilho (CC 74) | mais perto = timbre mais brilhante |
| Mão D: inclinação da palma | Profundidade do vibrato | mais inclinada = vibrato mais intenso |
| Mão E: altura (Y) | Volume (CC 11) | mais alto = mais volume |
| Mão E: horizontal (X) | Pan estéreo (CC 10) | esquerda/direita = posição no campo estéreo |
| Mão E: profundidade (Z) | Reverb (CC 91) | mais perto = mais reverb |
| Mão E: abertura dos dedos | Chorus (CC 93) | mão aberta = mais chorus |

### Piano

| Gesto | Parâmetro | Efeito no Som |
|---|---|---|
| Dedo desce até a linha | Disparo de nota (note-on) | toca a nota da tecla correspondente |
| Posição X do dedo | Seleção de nota | determina qual tecla é tocada |
| Dedo sobe acima da linha | Liberação (note-off) | encerra a nota |
| Indicador na barra lateral | Volume | deslizar cima/baixo ajusta volume |

### Bateria

| Gesto | Parâmetro | Efeito no Som |
|---|---|---|
| Polegar desce em zona de bumbo | Disparo (note-on, MIDI 36/35) | som de bumbo |
| Polegar desce em zona de caixa | Disparo (note-on, MIDI 38) | som de caixa |
| Polegar desce em prato | Disparo (note-on, MIDI 49/51/...) | som de prato |
| Velocidade da descida (`dy`) | Velocity MIDI | mais rápido = som mais alto |
| Pé desce em zona de pedal | Disparo de bumbo/pedal hi-hat | sons de pedal |

---

## Glossário MIDI

| Termo | Descrição |
|---|---|
| **Note-on / Note-off** | Mensagens que ligam e desligam uma nota no sintetizador |
| **Pitch Bend** | Desvio contínuo de afinação, em unidades de ±8192 |
| **CC (Control Change)** | Mensagem de controle contínuo (volume, pan, efeitos) |
| **CC 7** | Volume do canal |
| **CC 10** | Pan (panorama estéreo) |
| **CC 11** | Expression (volume expressivo em tempo real) |
| **CC 74** | Brightness / Filter Cutoff (brilho do timbre) |
| **CC 91** | Reverb Send Level (quantidade de reverb) |
| **CC 93** | Chorus Send Level (quantidade de chorus) |
| **Velocity** | Intensidade de uma nota (0–127) |
| **LFO** | Low Frequency Oscillator — oscilador usado para criar vibrato |
| **Bank / Preset** | Endereço de um instrumento dentro de um arquivo SoundFont (.sf2) |

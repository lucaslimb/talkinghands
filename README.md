# Talking Hands

Talking Hands transforma movimentos capturados pela webcam em instrumentos musicais e jogos de ritmo. O projeto combina visão computacional, síntese por SoundFont e interfaces em PySide6 para criar uma experiência musical sem controlador físico.

> Plataforma principal: Windows 10/11, 64 bits. É necessária uma webcam e uma saída de áudio funcional.

## O que há no projeto

- Menu em tela cheia, com navegação em carrossel entre **Prática**, **Modo Jogo**, **Estatísticas** e **Gravações**.
- Instrumentos controlados por mãos, e as vezes pés.
- Sons baseados em SoundFonts e gravação de sessões em MIDI e WAV.
- Dois jogos configurados pelo menu: Piano Tiles e Genius Drums.
- Executável Windows gerado com PyInstaller e FluidSynth incluído.

## Modos de prática

No menu, abra **Modo Prática** e dê duplo clique no modo desejado. A seleção de som é feita dentro da própria interface do instrumento.

| Modo | Como tocar | Recursos principais |
| --- | --- | --- |
| **Piano** | Toque as teclas virtuais com os dedos. | Teclado de duas oitavas, sustain, glissando, calibração/posição das teclas, seleção de timbres e gravação. |
| **Bateria** | Faça movimentos de batida sobre os elementos exibidos na câmera. | Intensidade baseada na velocidade do gesto, kits e elementos configuráveis, reposicionamento dos pads, suporte opcional aos pés e gravação. |
| **Maestro** | Conduza o som com movimentos contínuos das duas mãos. | A mão direita controla pitch, pan, timbre, vibrato e tremolo; a esquerda controla volume, reverb e chorus. Gestos rápidos podem disparar kick, snare, accent e swell. |

Em todas as interfaces, `Esc` encerra a sessão. Os controles de gravação ficam disponíveis dentro de cada modo.

## Modo jogo

Informe um apelido antes de iniciar: cada tentativa concluída é salva localmente e o Ranking mostra o melhor resultado de cada pessoa, separado por jogo. As escolhas feitas no menu são mantidas durante a partida e ao reiniciar; para trocar dificuldade ou música, feche a sessão e volte ao menu.

- **Piano Tiles:** escolha **Fácil**, **Médio** ou **Difícil** e uma música. Depois da contagem regressiva, toque as notas quando elas chegarem à linha de toque. Ao terminar, reinicie com a mesma música/dificuldade ou encerre.
- **Genius Drums:** escolha a dificuldade e inicie. Após a contagem regressiva, observe a sequência de elementos da bateria e repita-a. Ao falhar, reinicie com a mesma dificuldade ou encerre.

## Gravações e estatísticas

- **Gravações:** lista as sessões salvas e permite atualizar a lista ou abrir sua pasta.
- **Estatísticas:** tela de acompanhamento de tempo, precisão e sequência; é a base visual para os indicadores de evolução do projeto.

Durante o desenvolvimento no Windows, as gravações ficam em `recordings\mids` e `recordings\wav` na pasta do projeto. No executável distribuído, elas ficam na pasta de dados do usuário.

## Tecnologias

| Área | Ferramentas |
| --- | --- |
| Interface | PySide6 / Qt |
| Visão computacional | OpenCV e MediaPipe |
| Áudio e MIDI | FluidSynth, pyFluidSynth, SoundFonts e mido |
| Jogos | Motores próprios para Piano Tiles e Genius Drums |
| Empacotamento | PyInstaller |
| Modelos auxiliares | ONNX Runtime e hsemotion-onnx |

## Executar em desenvolvimento

### Pré-requisitos

- Python 3.11

No PowerShell, a partir da pasta raiz do projeto:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Na primeira preparação de um clone que ainda não tenha o FluidSynth em `assets\fluidsynth-v2.5.1`, execute:

```powershell
python builders\setup_fluidsynth.py
```

Depois, inicie o menu:

```powershell
python src\main.py
```

## Gerar o executável Windows

Com o ambiente virtual ativado e as dependências instaladas:

```powershell
python builders\build.py
```

O script verifica ou baixa o FluidSynth, instala o PyInstaller caso necessário e cria uma distribuição em pasta. O resultado fica em:

```text
dist\THEngine\THEngine.exe
```

O build é `--onedir`: o executável depende dos arquivos ao redor dele. **Não copie somente `THEngine.exe`.**

## Executar em outro computador ou em outra pasta

1. Gere o pacote seguindo a seção anterior.
2. Copie a pasta inteira `dist\THEngine` para o computador de destino.
3. No destino, abra a pasta copiada e execute `THEngine.exe`.

Python, pip e FluidSynth não precisam ser instalados separadamente: o pacote gerado já inclui o runtime, dependências, assets, SoundFonts e DLLs necessários.

No executável Windows, os dados do usuário não ficam dentro da pasta do pacote. As gravações e o ranking local são salvos em:

```text
%LOCALAPPDATA%\\Talking Hands
```

O arquivo de ranking é `scores.sqlite3`; ele é criado automaticamente na primeira partida.

## Créditos de bancos de som

O projeto inclui SoundFonts como ModuleMaster, The Definitive Perfect Drums e Chris Flutes and Harmonicas. Consulte as licenças e atribuições dos arquivos distribuídos em `assets/` antes de redistribuir o aplicativo.

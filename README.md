# Talking Hands - Instrumentos Invisíveis com Visão Computacional

Aplicação de _Air Instrument_ projetada para transformar qualquer ambiente em interfaces musicais virtuais. O sistema utiliza algoritmos avançados de Inteligência Artificial para o rastreamento de mãos em tempo real, integrados a um motor de síntese de áudio de baixa latência, permitindo a execução musical via webcam sem a necessidade de periféricos físicos adicionais, com mais de 40 sons dividos em diversos instrumentos.

## 🚀 Funcionalidades do Sistema

### 🎹 Modos de Instrumento

-   **Teclado/Piano:**
    
    -   O sistema mapeia duas oitavas completas (C3 a B4).
        
    -   Permite calibrar tamanho e posição das teclas de acordo com as mãos do usuário.
                
    -   Permite técnicas como deslize (glissando) e sustentação de maneira dinâmica e configurável.
        
-   **Bateria:**
    
    -   Dispõe espacialmente os componentes da bateria (Caixa, Bumbo, Pratos, Tons).
        
    -   Modula a intensidade sonora baseando-se na velocidade vetorial do movimento de batida.

-   **Flauta:**

    -   Uso de reconhecimento facial para ação de sopro, com níveis diferentes de intensidade.
    
    -   Permite calibrar tamanho e posição dos furos da flauta, para se adaptar a mão e a distância da camera do usuário.
            
### 🎛️ Interface e Controle

-   **Launcher:** Interface gráfica para a seleção de instrumentos, timbres e configuração de parâmetros, incluindo parâmetros de processamento e simulação individuais de cada instrumento, como:
	- Tempo de sustentação de notas
    - Velocidade e sensibilidade de toque ou batida
    - Cálculo de previsão da ação de toque
    - Cálculo de intensidade de sopro com abertura da boca

-  **Interação na GUI dos instrumentos:** Grave trechos, toque playbacks, calibre as mãos diretamente na interface dos instrumentos.
      
-   **Gravação e Exportação:** Permite gravar e exportar nos formatos `.WAV`, `.MP3` ou `.MID`, além de organizar pastas de áudio.

## 🛠️ Stack de Tecnologias

O projeto foi desenvolvido inteiramente em **Python**, orquestrando bibliotecas de baixo nível em C/C++ para garantir a performance.

|Componente       |Tecnologia | Utilização
|----------------|---------|-------|
|Visão Computacional |`OpenCV(cv2)`| Gerenciamento de captura de vídeo, processamento de imagem e renderização da interface|
|IA & ML|`MediaPipe`| Inferência dos marcos anatômicos da mão e rosto (para instrumentos de sopro) em tempo real|
|Backend de Áudio|`pyFluidSynth`|Wrapper para a biblioteca FluidSynth em C, garantindo baixa latência|
|Interface Gráfica (Launcher) |`CustomTkinter` | Biblioteca para construção de interfaces de usuário moderna em linguagem Python
|Interface Gráfica (Instrumentos)|`PyGame` | Biblioteca para construção de interfaces e jogos em linguagem Python

> **Bancos de som utilizados incluem** [ModuleMaster](https://musical-artifacts.com/artifacts/5978), de Vini, [The Definitive Perfect Drums Soundfont](https://musical-artifacts.com/artifacts/6554), de TEC Again e [Chris Flutes and Harmonicas](https://www.producersbuzz.com/downloads/download-free-soundfonts-sf2/top-14-free-flute-soundfonts-sf2/), de C.Clews

## Como utilizar
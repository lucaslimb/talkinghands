# Talking Hands - Instrumentos Invisíveis com Visão Computacional

Aplicação de _Air Instrument_ de alta performance projetada para transformar qualquer ambiente em interfaces musicais virtuais. O sistema utiliza algoritmos avançados de Inteligência Artificial para o rastreamento de mãos em tempo real, integrados a um motor de síntese de áudio de baixa latência, permitindo a execução musical via webcam sem a necessidade de periféricos físicos adicionais, com mais de 30 sons dividos em diversos instrumentos.

## 🚀 Funcionalidades do Sistema

### 🎹 Modos de Instrumento

-   **Teclado/Piano:**
    
    -   O sistema mapeia duas oitavas completas (C3 a B4).
        
    -   Permite calibrar tamanho e posição das teclas de acordo com as mãos do usuário.
        
    -   Suporta a execução simultânea de múltiplas notas através do rastreamento de múltiplos dedos.
        
    -   Permite técnicas como deslize (glissando) e sustentação de maneira dinâmica e configurável.
        
-   **Bateria:**
    
    -   Dispõe espacialmente os componentes da bateria (Caixa, Bumbo, Pratos, Tons).
        
    -   Modula a intensidade sonora baseando-se na velocidade vetorial do movimento de impacto.
    
### 🎛️ Interface e Controle

-   **Launcher:** Interface gráfica para a seleção de instrumentos, timbres e configuração de parâmetros, incluindo parâmetros de processamento e simulação e dos instrumentos, como:
	- Tempo de sustentação de notas, velocidade e sensibilidade de toque, cálculo de previsão da ação de toque

-  **Interação na GUI dos instrumentos:** Grave trechos, toque playbacks, calibre as mãos diretamente na interface dos instrumentos.
      
-   **Gravação e Exportação:** Permite registrar a performance e exportá-la nos formatos `.WAV`, `.MP3` ou `.MID` (MIDI), além de organizar pastas de áudio.

## 🛠️ Stack de Tecnologias

O projeto foi desenvolvido inteiramente em **Python**, orquestrando bibliotecas de baixo nível em C++ para garantir a performance.

|Componente       |Tecnologia | Utilização
|----------------|---------|-------|
|Visão Computacional		 |`OpenCV(cv2)`| Gerenciamento de captura de vídeo, processamento de imagem e renderização da interface|
|IA & ML|`MediaPipe`| Inferência dos marcos anatômicos da mão em tempo real|
|Backend de Áudio|`pyFluidSynth`|Wrapper para a biblioteca FluidSynth em C, garantindo baixa latência|
|Interface Gráfica |`CustomTkinter` | Framework para construção de interfaces de usuário moderna em linguagem Python

> **Bancos de som utilizados incluem** [ModuleMaster](https://musical-artifacts.com/artifacts/5978), de Vini e [The Definitive Perfect Drums Soundfont](https://musical-artifacts.com/artifacts/6554), de TEC Again
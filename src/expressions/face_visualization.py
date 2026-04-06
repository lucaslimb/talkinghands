"""
Face Visualization — Visualização orgânica de emoções estilo cérebro alienígena.

Renderiza um "núcleo neural" central com partículas fluindo em direção a
setores angulares, onde cada setor corresponde a uma emoção. A intensidade
de cada emoção controla quantidade, velocidade e brilho das partículas.

Pode rodar standalone (com dados simulados via ondas senoidais) ou ser
integrado ao EmotionTracker de face.py passando um dicionário de scores.

Uso standalone:
    python -m src.expressions.face_visualization
"""

import math
import time

import pygame
from opensimplex import OpenSimplex

# ══════════════════════════════════════════════════════════════════════════════
# VARIÁVEIS AJUSTÁVEIS
# ══════════════════════════════════════════════════════════════════════════════

# Janela
SCREEN_WIDTH  = 1200
SCREEN_HEIGHT = 900
TARGET_FPS    = 60
BACKGROUND    = (4, 4, 18)          # azul quase-preto

# "Respiração" global (zoom in/out sutil)
BREATHING_AMP   = 0.012             # amplitude do zoom (fração)
BREATHING_SPEED = 0.4               # velocidade (Hz)

# Setor de emoção
SECTOR_LABEL_OFFSET  = 40           # distância extra do label além do raio do setor
SECTOR_ARC_RADIUS    = 320          # raio onde os setores ficam
SECTOR_ARC_WIDTH     = 6            # largura do arco indicador

# ══════════════════════════════════════════════════════════════════════════════
# CORES DAS EMOÇÕES (importadas de face.py quando possível)
# ══════════════════════════════════════════════════════════════════════════════

EMOTION_COLORS = {
    "Happiness": (255, 230,  50),
    "Sadness":   ( 80, 130, 220),
    "Anger":     (230,  50,  50),
    "Fear":      (180,  80, 230),
    "Surprise":  (255, 160,  30),
    "Contempt":  (160, 160, 100),
    "Disgust":   (100, 200,  80),
}

EMOTION_NAMES_PT = {
    "Happiness": "Felicidade",
    "Sadness":   "Tristeza",
    "Anger":     "Raiva",
    "Fear":      "Medo",
    "Surprise":  "Surpresa",
    "Contempt":  "Desprezo",
    "Disgust":   "Nojo",
}

# Lista ordenada (define a ordem angular)
EMOTIONS = list(EMOTION_COLORS.keys())

# ══════════════════════════════════════════════════════════════════════════════
# NOISE GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

_noise = OpenSimplex(seed=42)


def snoise2(x: float, y: float) -> float:
    """Wrapper para simplex noise 2D, retorna [-1, 1]."""
    return _noise.noise2(x, y)


# ══════════════════════════════════════════════════════════════════════════════
# EMOTION SECTOR
# ══════════════════════════════════════════════════════════════════════════════

class EmotionSector:
    """Setor angular correspondente a uma emoção."""

    def __init__(self, name: str, index: int, total: int):
        self.name = name
        self.name_pt = EMOTION_NAMES_PT.get(name, name)
        self.color = EMOTION_COLORS[name]
        self.intensity = 0.0  # 0..1
        self._smooth_intensity = 0.0  # versão suavizada

        # Ângulo central do setor
        self.angle = (2 * math.pi * index / total) - math.pi / 2  # começa no topo
        self.angle_width = 2 * math.pi / total

        # Posição do label
        label_r = SECTOR_ARC_RADIUS + SECTOR_LABEL_OFFSET
        self.label_x = math.cos(self.angle) * label_r
        self.label_y = math.sin(self.angle) * label_r

    def set_intensity(self, value: float):
        """Define intensidade (0..1)."""
        self.intensity = max(0.0, min(1.0, value))

    def update(self, dt: float):
        """Suaviza a intensidade com interpolação."""
        alpha = min(1.0, 4.0 * dt)
        self._smooth_intensity += alpha * (self.intensity - self._smooth_intensity)

    @property
    def smooth_intensity(self) -> float:
        return self._smooth_intensity

    def draw_arc(self, surface: pygame.Surface, cx: float, cy: float,
                 scale: float, t: float):
        """Desenha o arco indicador do setor."""
        intensity = self._smooth_intensity
        if intensity < 0.01:
            # Arco apagado
            self._draw_arc_segment(surface, cx, cy, scale, 0.15, (40, 40, 50))
            return

        # Pulsação leve do arco baseada na intensidade
        pulse = 1.0 + 0.15 * intensity * math.sin(t * 3.0 + self.angle * 2)
        alpha = int(60 + 195 * intensity * pulse)
        alpha = min(255, max(0, alpha))

        # Cor com brilho variável
        r = min(255, int(self.color[0] * (0.4 + 0.6 * intensity)))
        g = min(255, int(self.color[1] * (0.4 + 0.6 * intensity)))
        b = min(255, int(self.color[2] * (0.4 + 0.6 * intensity)))

        self._draw_arc_segment(surface, cx, cy, scale, intensity, (r, g, b), alpha)

    def _draw_arc_segment(self, surface, cx, cy, scale, intensity,
                          color, alpha=60):
        """Renderiza um segmento de arco com transparência."""
        radius = int(SECTOR_ARC_RADIUS * scale)
        width = max(2, int(SECTOR_ARC_WIDTH * (0.5 + 0.5 * intensity) * scale))

        half_arc = self.angle_width * 0.42  # gap entre setores
        start = self.angle - half_arc
        end = self.angle + half_arc

        # Desenhar arco como série de pontos para controle de alpha
        arc_surf = pygame.Surface((radius * 2 + 20, radius * 2 + 20), pygame.SRCALPHA)
        arc_cx = radius + 10
        arc_cy = radius + 10

        steps = max(20, int(40 * abs(end - start)))
        for i in range(steps):
            frac = i / (steps - 1)
            a = start + frac * (end - start)
            px = arc_cx + math.cos(a) * radius
            py = arc_cy + math.sin(a) * radius
            pygame.draw.circle(arc_surf, (*color, min(255, alpha)), (int(px), int(py)), width)

        surface.blit(arc_surf, (int(cx) - arc_cx, int(cy) - arc_cy),
                     special_flags=pygame.BLEND_RGBA_ADD)

    def draw_label(self, surface: pygame.Surface, font: pygame.font.Font,
                   cx: float, cy: float, scale: float):
        """Desenha o nome da emoção no canto do setor."""
        intensity = self._smooth_intensity
        # Brilho do texto depende da intensidade
        bright = 0.35 + 0.65 * intensity
        r = min(255, int(self.color[0] * bright))
        g = min(255, int(self.color[1] * bright))
        b = min(255, int(self.color[2] * bright))

        sx = int(cx + self.label_x * scale)
        sy = int(cy + self.label_y * scale)

        text = font.render(self.name_pt.upper(), True, (r, g, b))
        rect = text.get_rect(center=(sx, sy))
        surface.blit(text, rect)

        # Indicador numérico de intensidade
        pct = font.render(f"{int(intensity * 100)}%", True, (r, g, b))
        pct_rect = pct.get_rect(center=(sx, sy + 18))
        surface.blit(pct, pct_rect)


# ══════════════════════════════════════════════════════════════════════════════
# BRAIN VISUALIZER (classe principal)
# ══════════════════════════════════════════════════════════════════════════════

class BrainVisualizer:
    """
    Visualizador de emoções estilo cérebro alienígena.

    Pode ser usado de duas formas:
    1. Standalone: chamar run() para loop autónomo com dados simulados.
    2. Integrado: chamar update_emotions(scores_dict) a cada frame externo,
       em seguida draw(surface) para renderizar no surface fornecido.
    """

    def __init__(self, width: int = SCREEN_WIDTH, height: int = SCREEN_HEIGHT):
        self.width = width
        self.height = height
        self.cx = width / 2
        self.cy = height / 2

        # Escala para adaptar a diferentes tamanhos de janela
        self.scale = min(width, height) / 900.0

        # Setores de emoção
        self.sectors = [
            EmotionSector(name, i, len(EMOTIONS))
            for i, name in enumerate(EMOTIONS)
        ]

        # Tempo
        self.t = 0.0
        self.start_time = time.perf_counter()

        # Superfície interna para overlay (reutilizada a cada frame)
        self._overlay_surf = pygame.Surface((width, height))

        # Fonte
        try:
            self.font = pygame.font.SysFont("Consolas", max(12, int(14 * self.scale)))
        except Exception:
            self.font = pygame.font.Font(None, max(14, int(16 * self.scale)))

    def update_emotions(self, scores: dict):
        """
        Atualiza intensidades das emoções a partir de um dicionário
        {nome_emoção: float 0..1}.

        Compatível com EmotionTracker.scores de face.py.
        """
        for sector in self.sectors:
            if sector.name in scores:
                sector.set_intensity(scores[sector.name])

    def _simulate_emotions(self):
        """Gera intensidades simuladas via ondas senoidais + noise."""
        t = self.t
        for i, sector in enumerate(self.sectors):
            # Onda base com fase diferente por emoção
            phase = i * 1.7
            base = 0.5 + 0.5 * math.sin(t * 0.3 + phase)
            # Modulação por noise para variação orgânica
            noise_val = snoise2(t * 0.15 + i * 3.0, i * 7.0)
            intensity = base * (0.5 + 0.5 * noise_val)
            # Picos ocasionais
            spike = max(0, snoise2(t * 0.6 + i * 5.0, 100.0)) ** 3
            intensity = min(1.0, intensity + spike * 0.5)
            sector.set_intensity(intensity)

    def update(self, dt: float):
        """Atualiza o estado da visualização. dt em segundos."""
        self.t = time.perf_counter() - self.start_time

        # Suavizar intensidades
        for sector in self.sectors:
            sector.update(dt)

    def draw(self, surface: pygame.Surface):
        """Renderiza a visualização completa no surface fornecido."""
        t = self.t

        # Efeito de respiração (zoom sutil)
        breath = 1.0 + BREATHING_AMP * math.sin(t * BREATHING_SPEED * 2 * math.pi)
        eff_scale = self.scale * breath

        cx = self.cx
        cy = self.cy

        # ── Fundo ──────────────────────────────────────────────────────
        surface.fill(BACKGROUND)

        # ── Arcos dos setores ──────────────────────────────────────────
        for sector in self.sectors:
            sector.draw_arc(surface, cx, cy, eff_scale, t)

        # ── Labels ─────────────────────────────────────────────────────
        for sector in self.sectors:
            sector.draw_label(surface, self.font, cx, cy, eff_scale)

    def draw_overlay(self, target: pygame.Surface, darken_alpha: int = 100):
        """
        Renderiza a visualização como overlay sobre um surface existente.

        Fluxo:
        1. Escurece levemente o target (para contraste)
        2. Desenha a visualização num surface preto interno
        3. Compõe aditivamente sobre o target — preto=transparente,
           partículas e glow aparecem sobre o vídeo.

        Args:
            target: surface com o conteúdo de fundo (ex: frame da câmera).
            darken_alpha: intensidade do escurecimento (0=nenhum, 255=preto).
        """
        # Escurecer o fundo para dar contraste às partículas
        if darken_alpha > 0:
            dark = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            dark.fill((0, 0, 0, darken_alpha))
            target.blit(dark, (0, 0))

        # Renderizar visualização no surface preto interno
        self.draw(self._overlay_surf)

        # Compor aditivamente: preto (0,0,0) não altera nada,
        # pixels brilhantes (partículas, glow, arcos) se somam ao vídeo
        target.blit(self._overlay_surf, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def run(self):
        """Loop standalone com dados simulados. Fecha com ESC ou fechar janela."""
        pygame.init()
        screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Neural Emotion Core — Alien Brain Visualizer")
        clock = pygame.time.Clock()

        render_surface = pygame.Surface((self.width, self.height))

        running = True
        while running:
            dt = clock.tick(TARGET_FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

            # Simular emoções
            self._simulate_emotions()

            # Atualizar
            self.update(dt)

            # Desenhar
            self.draw(render_surface)
            screen.blit(render_surface, (0, 0))

            pygame.display.flip()

        pygame.quit()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT STANDALONE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pygame.init()
    viz = BrainVisualizer(SCREEN_WIDTH, SCREEN_HEIGHT)
    viz.run()

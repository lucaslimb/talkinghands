"""Game idea and scoring copy shared by the main-menu guide."""


_GUIDES = {
    "piano_tiles": (
        "Piano Tiles — como jogar",
        (
            ("Objetivo", "Toque a nota indicada quando o bloco alcançar a linha de toque. A música sempre chega ao fim: erros reduzem pontos, mas não encerram a partida."),
            ("Pontuação", "<b>Perfect:</b> 100 pontos<br><b>Good:</b> 60 pontos<br><b>Erro:</b> −20 pontos<br><br>O placar nunca fica abaixo de zero."),
            ("Bônus", "<b>Sequência:</b> 10–24: 1,25× · 25–49: 1,5× · 50+: 2×.<br><br><b>Dificuldade:</b> Fácil 1× · Médio 1,25× · Difícil 1,5×.<br><br><b>Precisão final:</b> 80%: 250 · 90%: 500 · 95%: 750 · 100%: 1.000. O bônus recebe o multiplicador de dificuldade."),
        ),
    ),
    "genius_drums": (
        "Genius Drums — como jogar",
        (
            ("Objetivo", "Observe a sequência mostrada nos elementos da bateria e repita-a na mesma ordem. A cada rodada, uma nova batida é adicionada à sequência."),
            ("Pontuação", "Cada batida correta vale <b>100</b> no Fácil, <b>125</b> no Médio e <b>150</b> no Difícil.<br><br>Uma batida errada ou o tempo esgotado encerra a partida e não concede pontos."),
            ("Bônus", "<b>Rodadas 1–4:</b> 100 × rodada<br><b>Rodadas 5–9:</b> 150 × rodada<br><b>Rodadas 10+:</b> 200 × rodada<br><br><b>Velocidade:</b> até 25% do bônus da rodada, conforme o tempo que restou."),
        ),
    ),
}


def get_score_guide(game_key: str):
    """Return a guide title and its compact information cards."""
    return _GUIDES[game_key]

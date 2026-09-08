"""Gera data/seed/imoveis.csv. Rodado uma vez; o produto e o CSV, nao este script.

Determinista (`Random(20260906)`) para que regerar produza o mesmo arquivo e o
diff mostre so o que mudou de proposito.
"""

import csv
import random
from pathlib import Path

DESTINO = Path(__file__).resolve().parents[1] / "data" / "seed" / "imoveis.csv"

BAIRROS = [
    ("Centro", "CENTRO", 1.00),
    ("Agronomica", "CENTRO", 1.10),
    ("Trindade", "CENTRO", 0.95),
    ("Itacorubi", "NORTE", 0.90),
    ("Coqueiros", "SUL", 0.85),
    ("Campeche", "SUL", 0.80),
    ("Jurere", "NORTE", 1.60),
    ("Canasvieiras", "NORTE", 0.75),
    ("Lagoa da Conceicao", "LESTE", 1.25),
    ("Santo Antonio de Lisboa", "NORTE", 1.15),
    ("Estreito", "OESTE", 0.70),
    ("Balneario", "OESTE", 0.78),
]

TIPOS = [
    ("APARTAMENTO", "AP", 0.50, (45, 180), (1, 4)),
    ("CASA", "CA", 0.25, (90, 320), (2, 5)),
    ("COBERTURA", "CO", 0.08, (120, 400), (2, 4)),
    ("TERRENO", "TE", 0.07, (200, 900), (0, 0)),
    ("COMERCIAL", "CM", 0.05, (30, 400), (0, 0)),
    # TEC-262. O peso de APARTAMENTO caiu de 0,55 para 0,50 para a soma
    # seguir em 1,00 -- `rng.choices` nao exige soma 1, mas a lista somava e
    # manter isso deixa o peso legivel como percentual. 0,05 poe RURAL entre
    # COMERCIAL e TERRENO, que e onde uma tipologia de nicho pertence.
    #
    # A faixa de area e a mais larga do arquivo, de proposito: chacara e
    # sitio vao de terreno pequeno a propriedade grande, e a largura e o que
    # mantem folgada a assercao de dispersao de preco do
    # `test_distribuicao_e_realista` com um tipo a mais.
    ("RURAL", "RU", 0.05, (400, 5000), (1, 4)),
]

CARACTERISTICAS = [
    "varanda gourmet",
    "pet friendly",
    "piscina",
    "academia",
    "churrasqueira",
    "vista mar",
    "mobiliado",
    "portaria 24h",
    "sacada",
    "energia solar",
]

CABECALHO = [
    "codigo", "titulo", "descricao", "tipo", "operacao", "preco_venda",
    "preco_aluguel", "condominio", "iptu_mensal", "bairro", "cidade", "uf",
    "zona", "latitude", "longitude", "area_util_m2", "quartos", "suites",
    "banheiros", "vagas", "caracteristicas", "fotos", "status",
]

# Piso de aluguel em reais. O parser (src/mobia/domain/catalogo/parser.py,
# PRECO_MINIMO_EM_CENTAVOS) rejeita qualquer preco_aluguel abaixo de R$1.000,
# e essa guarda vale tanto para preco_aluguel quanto para preco_venda -- nao e
# bug, e RN-08.5/D6 do desenho. O aluguel proporcional (0,35%-0,55% do valor de
# venda) fica abaixo desse piso exatamente nos imoveis mais baratos da base
# (ex.: COMERCIAL de 30m2 num bairro barato). Em vez de afrouxar a guarda do
# parser -- decisao ja tomada no desenho aprovado -- ou de inflar o preco por
# m2 so para empurrar o aluguel proporcional para cima (o que distorceria toda
# a distribuicao de preco_venda), fixamos um piso no proprio aluguel: ele
# continua proporcional ao preco de venda, mas nunca sai do arquivo abaixo do
# que o parser aceita.
ALUGUEL_MINIMO_EM_REAIS = 1000.0


def gerar(quantidade: int = 520) -> list[list[str]]:
    rng = random.Random(20260906)
    linhas = []
    for n in range(1, quantidade + 1):
        tipo, prefixo, _, (area_min, area_max), (q_min, q_max) = rng.choices(
            TIPOS, weights=[t[2] for t in TIPOS]
        )[0]
        bairro, zona, fator = rng.choice(BAIRROS)
        area = rng.randint(area_min, area_max)
        quartos = rng.randint(q_min, q_max) if q_max else 0
        suites = rng.randint(0, quartos) if quartos else 0
        banheiros = max(1, quartos)
        vagas = rng.randint(0, 3)

        # Preco por m2 puxado pelo fator do bairro, com ruido de +-15%.
        por_m2 = rng.randint(7000, 14000) * fator * rng.uniform(0.85, 1.15)
        preco_venda = round(area * por_m2, 2)

        operacao = rng.choices(["VENDA", "ALUGUEL", "AMBOS"], weights=[0.72, 0.18, 0.10])[0]
        # Ver ALUGUEL_MINIMO_EM_REAIS acima: o max() garante que nenhum
        # aluguel emitido caia sob o piso de plausibilidade do parser.
        aluguel = round(
            max(preco_venda * rng.uniform(0.0035, 0.0055), ALUGUEL_MINIMO_EM_REAIS), 2
        )

        status = rng.choices(
            ["DISPONIVEL", "RESERVADO", "VENDIDO", "ALUGADO", "INATIVO"],
            weights=[0.80, 0.07, 0.07, 0.04, 0.02],
        )[0]

        caracteristicas = rng.sample(CARACTERISTICAS, rng.randint(0, 4))

        linhas.append([
            f"{prefixo}-{1000 + n}",
            f"{tipo.capitalize()} em {bairro}",
            f"{tipo.capitalize()} de {area} m2 em {bairro}, "
            f"{quartos} quarto(s) e {vagas} vaga(s). "
            + (", ".join(caracteristicas) if caracteristicas else "Sem diferenciais listados")
            + ".",
            tipo,
            operacao,
            f"{preco_venda:.2f}" if operacao in ("VENDA", "AMBOS") else "",
            f"{aluguel:.2f}" if operacao in ("ALUGUEL", "AMBOS") else "",
            f"{rng.randint(200, 2500)}.00",
            f"{rng.randint(80, 900)}.00",
            bairro,
            "Florianopolis",
            "SC",
            zona,
            f"{rng.uniform(-27.75, -27.40):.6f}",
            f"{rng.uniform(-48.60, -48.40):.6f}",
            str(area),
            str(quartos),
            str(suites),
            str(banheiros),
            str(vagas),
            "|".join(caracteristicas),
            f"https://exemplo.com/{prefixo.lower()}-{1000 + n}-1.jpg",
            status,
        ])
    return linhas


if __name__ == "__main__":
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    with DESTINO.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, lineterminator="\n")
        escritor.writerow(CABECALHO)
        escritor.writerows(gerar())
    print(f"gerado: {DESTINO}")

import os
from datetime import date, datetime, timezone, timedelta
import requests

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PRECO_ALVO_BRL = 4800.00  # Alerta imediato se qualquer voo direto ficar <= este valor
MIN_DIAS_CORRIDOS = 18
MAX_DIAS_CORRIDOS = 25

# Feriados nacionais no Brasil (setembro a novembro de 2027)
FERIADOS_BR_2027 = {
    date(2027, 9, 7),   # Independência do Brasil (terça)
    date(2027, 10, 12), # Nossa Senhora Aparecida (terça)
    date(2027, 11, 2),  # Finados (terça)
    date(2027, 11, 15), # Proclamação da República (segunda)
    date(2027, 11, 20), # Consciência Negra (sábado)
}


def contar_dias_uteis(ida: date, volta: date) -> int:
    uteis = 0
    atual = ida
    while atual <= volta:
        if atual.weekday() < 5 and atual not in FERIADOS_BR_2027:
            uteis += 1
        atual += timedelta(days=1)
    return uteis


def gerar_melhores_combinacoes(limite_buscas: int = 8) -> list[dict]:
    """
    Gera todas as combinações entre 18 e 25 dias corridos (set/out/nov 2027),
    sem restrição de dia da semana, e seleciona as que consomem menos dias úteis
    para respeitar a cota mensal da SerpApi.
    """
    inicio_busca = date(2027, 9, 1)
    fim_busca = date(2027, 11, 30)
    candidatas = []

    dia_ida = inicio_busca
    while dia_ida <= fim_busca - timedelta(days=MIN_DIAS_CORRIDOS - 1):
        for duracao in range(MIN_DIAS_CORRIDOS, MAX_DIAS_CORRIDOS + 1):
            dia_volta = dia_ida + timedelta(days=duracao - 1)
            if dia_volta > fim_busca:
                break

            uteis = contar_dias_uteis(dia_ida, dia_volta)
            # Índice de eficiência: prioriza menor nº de dias úteis e maior duração
            candidatas.append({
                "ida": dia_ida.isoformat(),
                "volta": dia_volta.isoformat(),
                "ida_br": dia_ida.strftime("%d/%m"),
                "volta_br": dia_volta.strftime("%d/%m"),
                "dias_corridos": duracao,
                "dias_uteis": uteis,
                "ratio": uteis / duracao,
            })
        dia_ida += timedelta(days=1)

    # Ordena pelas combinações que consomem menos dias úteis (e depois maior duração)
    candidatas.sort(key=lambda x: (x["dias_uteis"], -x["dias_corridos"]))

    # Seleciona as top combinações diversificando datas (evita datas quase idênticas)
    selecionadas = []
    for c in candidatas:
        if any(abs((date.fromisoformat(c["ida"]) - date.fromisoformat(s["ida"])).days) < 3
               and c["dias_corridos"] == s["dias_corridos"] for s in selecionadas):
            continue
        selecionadas.append(c)
        if len(selecionadas) >= limite_buscas:
            break

    return selecionadas


def enviar_telegram(mensagem: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"},
        timeout=20,
    )


def eh_segunda_manha_brt() -> bool:
    fuso_brt = timezone(timedelta(hours=-3))
    agora_brt = datetime.now(fuso_brt)
    return agora_brt.weekday() == 0 and 7 <= agora_brt.hour <= 12


def buscar_voos_diretos():
    combinacoes = gerar_melhores_combinacoes(limite_buscas=8)
    resultados_validos = []

    for comb in combinacoes:
        params = {
            "engine": "google_flights",
            "departure_id": "GRU",
            "arrival_id": "MAD",
            "outbound_date": comb["ida"],
            "return_date": comb["volta"],
            "currency": "BRL",
            "hl": "pt-br",
            "gl": "br",
            "stops": "1",  # Apenas voos diretos (nonstop)
            "api_key": SERPAPI_KEY,
        }

        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
        if resp.status_code != 200:
            continue

        dados = resp.json()
        voos = dados.get("best_flights", []) + dados.get("other_flights", [])

        for opcao in voos:
            preco = opcao.get("price")
            trechos = opcao.get("flights", [])
            if not preco or not trechos:
                continue

            cia = trechos[0].get("airline", "Desconhecida")
            resultados_validos.append({
                "preco": float(preco),
                "dias_uteis": comb["dias_uteis"],
                "dias_corridos": comb["dias_corridos"],
                "ida_br": comb["ida_br"],
                "volta_br": comb["volta_br"],
                "cia": cia,
            })

    # Ordena exatamente conforme solicitado:
    # 1º Menor valor | 2º Menor quantidade de dias úteis | 3º Maior nº de dias corridos
    resultados_validos.sort(key=lambda x: (x["preco"], x["dias_uteis"], -x["dias_corridos"]))

    # Remove duplicatas idênticas de (cia, ida, volta)
    unicos = []
    vistos = set()
    for r in resultados_validos:
        chave = (r["cia"], r["ida_br"], r["volta_br"])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(r)

    alertas = [r for r in unicos if r["preco"] <= PRECO_ALVO_BRL]

    if alertas:
        linhas_alerta = [
            f"• *R$ {r['preco']:,.2f}* — {r['cia']}\n"
            f"  📅 {r['ida_br']} a {r['volta_br']} ({r['dias_corridos']}d corridos / *{r['dias_uteis']}d úteis*)"
            for r in alertas[:10]
        ]
        enviar_telegram(
            f"🚨 *ALERTA VOO DIRETO GRU → MAD (≤ R$ {PRECO_ALVO_BRL:,.0f})*\n\n"
            + "\n\n".join(linhas_alerta)
        )

    forcar_relatorio = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if eh_segunda_manha_brt() or forcar_relatorio:
        if unicos:
            linhas_rank = [
                f"{idx}. *R$ {r['preco']:,.2f}* ({r['cia']})\n"
                f"   📅 {r['ida_br']} a {r['volta_br']} — {r['dias_corridos']}d corridos | *{r['dias_uteis']}d úteis*"
                for idx, r in enumerate(unicos[:12], start=1)
            ]
            msg = (
                "📊 *Ranking Voos Diretos GRU → MAD (18 a 25 dias)*\n"
                "Ordenado por: *Menor Preço → Menos Dias Úteis*\n\n"
                + "\n\n".join(linhas_rank)
            )
        else:
            msg = "📊 *Ranking Voos Diretos GRU → MAD*\nNenhuma tarifa direta retornada para as janelas testadas hoje."

        enviar_telegram(msg)


if __name__ == "__main__":
    buscar_voos_diretos()

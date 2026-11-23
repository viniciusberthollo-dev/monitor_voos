import os
from datetime import datetime, timezone, timedelta
import requests

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PRECO_ALVO_BRL = 5200.00  # Alerta imediato se qualquer voo direto ficar <= este valor

# Combinações otimizadas (18 a 20 dias com mínimo de dias úteis em 2027)
JANELAS_2027 = [
    {"nome": "Setembro (03/09 a 22/09 - 20d / 13d úteis)", "ida": "2027-09-03", "volta": "2027-09-22"},
    {"nome": "Setembro (04/09 a 22/09 - 19d / 12d úteis)", "ida": "2027-09-04", "volta": "2027-09-22"},
    {"nome": "Outubro (08/10 a 27/10 - 20d / 13d úteis)",  "ida": "2027-10-08", "volta": "2027-10-27"},
    {"nome": "Outubro (09/10 a 27/10 - 19d / 12d úteis)",  "ida": "2027-10-09", "volta": "2027-10-27"},
    {"nome": "Novembro (30/10 a 16/11 - 18d / 11d úteis)", "ida": "2027-10-30", "volta": "2027-11-16"},
    {"nome": "Novembro (01/11 a 18/11 - 18d / 11d úteis)", "ida": "2027-11-01", "volta": "2027-11-18"},
]


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
    alertas_imediato = []
    linhas_relatorio = []

    for janela in JANELAS_2027:
        params = {
            "engine": "google_flights",
            "departure_id": "GRU",
            "arrival_id": "MAD",
            "outbound_date": janela["ida"],
            "return_date": janela["volta"],
            "currency": "BRL",
            "hl": "pt-br",
            "gl": "br",
            "stops": "1",  # 1 = Apenas voos diretos (nonstop) na SerpApi
            "api_key": SERPAPI_KEY,
        }

        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
        if resp.status_code != 200:
            linhas_relatorio.append(f"• *{janela['nome']}*\n  _Erro ou data ainda não aberta no Google Flights_")
            continue

        dados = resp.json()
        voos = dados.get("best_flights", []) + dados.get("other_flights", [])

        if not voos:
            linhas_relatorio.append(f"• *{janela['nome']}*\n  _Sem voos diretos abertos ainda_")
            continue

        melhores_por_cia = {}
        for opcao in voos:
            preco = opcao.get("price")
            trechos = opcao.get("flights", [])
            if not preco or not trechos:
                continue

            cia = trechos[0].get("airline", "Desconhecida")
            preco_float = float(preco)

            if cia not in melhores_por_cia or preco_float < melhores_por_cia[cia]:
                melhores_por_cia[cia] = preco_float

        ordenado = sorted(melhores_por_cia.items(), key=lambda x: x[1])
        detalhes_cias = []

        for cia, preco in ordenado:
            detalhes_cias.append(f"  - {cia}: R$ {preco:,.2f}")
            if preco <= PRECO_ALVO_BRL:
                alertas_imediato.append(
                    f"• *{janela['nome']}*\n  ✈️ {cia}: *R$ {preco:,.2f}*"
                )

        linhas_relatorio.append(f"• *{janela['nome']}*\n" + "\n".join(detalhes_cias))

    if alertas_imediato:
        msg_alerta = (
            f"🚨 *ALERTA DE PREÇO: Voo Direto GRU → MAD (≤ R$ {PRECO_ALVO_BRL:,.0f})*\n\n"
            + "\n\n".join(alertas_imediato)
        )
        enviar_telegram(msg_alerta)

    forcar_relatorio = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if eh_segunda_manha_brt() or forcar_relatorio:
        msg_semanal = (
            "📊 *Resumo Semanal — Voos Diretos GRU → MAD (2027)*\n"
            f"🎯 Meta configurada: R$ {PRECO_ALVO_BRL:,.2f}\n\n"
            + "\n\n".join(linhas_relatorio)
        )
        enviar_telegram(msg_semanal)


if __name__ == "__main__":
    buscar_voos_diretos()

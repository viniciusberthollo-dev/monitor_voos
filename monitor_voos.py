import os
from datetime import datetime, timezone, timedelta
import requests

AMADEUS_CLIENT_ID = os.getenv("AMADEUS_CLIENT_ID")
AMADEUS_CLIENT_SECRET = os.getenv("AMADEUS_CLIENT_SECRET")
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

NOMES_CIAS = {
    "LA": "LATAM",
    "IB": "Iberia",
    "UX": "Air Europa",
    "CA": "Air China",
}


def obter_token_amadeus() -> str:
    resp = requests.post(
        "https://api.amadeus.com/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": AMADEUS_CLIENT_ID,
            "client_secret": AMADEUS_CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


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
    # Segunda-feira (weekday == 0) na execução da manhã (entre 07h e 12h BRT)
    return agora_brt.weekday() == 0 and 7 <= agora_brt.hour <= 12


def buscar_voos_diretos():
    token = obter_token_amadeus()
    headers = {"Authorization": f"Bearer {token}"}

    alertas_imediato = []
    linhas_relatorio = []

    for janela in JANELAS_2027:
        params = {
            "originLocationCode": "GRU",
            "destinationLocationCode": "MAD",
            "departureDate": janela["ida"],
            "returnDate": janela["volta"],
            "adults": 1,
            "nonStop": "true",
            "currencyCode": "BRL",
            "max": 15,
        }
        resp = requests.get(
            "https://api.amadeus.com/v2/shopping/flight-offers",
            headers=headers,
            params=params,
            timeout=30,
        )

        if resp.status_code != 200:
            linhas_relatorio.append(f"• *{janela['nome']}*\n  _Sem tarifas abertas no sistema ainda_")
            continue

        dados = resp.json().get("data", [])
        if not dados:
            linhas_relatorio.append(f"• *{janela['nome']}*\n  _Nenhum voo direto encontrado_")
            continue

        melhores_por_cia = {}
        for oferta in dados:
            preco = float(oferta["price"]["total"])
            cia_cod = oferta["validatingAirlineCodes"][0]
            cia_nome = NOMES_CIAS.get(cia_cod, cia_cod)

            if cia_nome not in melhores_por_cia or preco < melhores_por_cia[cia_nome]:
                melhores_por_cia[cia_nome] = preco

        ordenado = sorted(melhores_por_cia.items(), key=lambda x: x[1])
        detalhes_cias = []

        for cia, preco in ordenado:
            detalhes_cias.append(f"  - {cia}: R$ {preco:,.2f}")
            if preco <= PRECO_ALVO_BRL:
                alertas_imediato.append(
                    f"• *{janela['nome']}*\n  ✈️ {cia}: *R$ {preco:,.2f}*"
                )

        linhas_relatorio.append(f"• *{janela['nome']}*\n" + "\n".join(detalhes_cias))

    # 1. Disparo imediato se alguma tarifa bater a meta
    if alertas_imediato:
        msg_alerta = (
            f"🚨 *ALERTA DE PREÇO: Voo Direto GRU → MAD (≤ R$ {PRECO_ALVO_BRL:,.0f})*\n\n"
            + "\n\n".join(alertas_imediato)
        )
        enviar_telegram(msg_alerta)

    # 2. Relatório semanal toda segunda-feira pela manhã (ou se rodar manualmente via workflow_dispatch)
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

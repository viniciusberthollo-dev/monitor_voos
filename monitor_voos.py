import json
import os
import re
from datetime import date, datetime, timezone, timedelta
import requests

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()

CONFIG_PATH = "config.json"
OFFSET_PATH = ".telegram_offset.json"

FERIADOS_BR_2027 = {
    date(2027, 9, 7),   # Independência do Brasil
    date(2027, 10, 12), # Nossa Senhora Aparecida
    date(2027, 11, 2),  # Finados
    date(2027, 11, 15), # Proclamação da República
    date(2027, 11, 20), # Consciência Negra
}

CONFIG_PADRAO = {
    "min_dias_corridos": 18,
    "max_dias_corridos": 25,
    "min_dias_uteis": 10,
    "max_dias_uteis": 15,
    "preco_alvo_brl": 4500.0,
    "meses": [9, 10, 11],
    "limite_buscas": 16,
}


def carregar_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            dados = json.load(f)
            return {**CONFIG_PADRAO, **dados}
    return dict(CONFIG_PADRAO)


def salvar_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def carregar_offset() -> int | None:
    if os.path.exists(OFFSET_PATH):
        with open(OFFSET_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("offset")
    return None


def salvar_offset(offset: int):
    with open(OFFSET_PATH, "w", encoding="utf-8") as f:
        json.dump({"offset": offset}, f)


def enviar_telegram(mensagem: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"},
        timeout=20,
    )


def formatar_status(cfg: dict) -> str:
    meses_str = ", ".join(str(m) for m in cfg["meses"])
    return (
        "⚙️ *Configuração Atual do Robô (GRU → MAD Direto)*\n\n"
        f"• *Dias corridos:* mín *{cfg['min_dias_corridos']}* | máx *{cfg['max_dias_corridos']}*\n"
        f"• *Dias úteis:* mín *{cfg['min_dias_uteis']}* | máx *{cfg['max_dias_uteis']}*\n"
        f"• *Meses (2027):* {meses_str}\n"
        f"• *Preço alvo:* R$ {cfg['preco_alvo_brl']:,.2f}\n"
        f"• *Consultas por rodada:* {cfg['limite_buscas']}\n\n"
        "*Comandos disponíveis:*\n"
        "`/corridos 18 25` — mín e máx dias corridos\n"
        "`/uteis 10 15` — mín e máx dias úteis\n"
        "`/alvo 4500` — preço alvo em R$\n"
        "`/meses 9,10,11` — meses de 2027\n"
        "`/config` — ver configuração atual\n"
        "`/buscar` — rodar busca agora\n"
        "`/reset` — restaurar valores padrão"
    )


def processar_comandos_telegram(cfg: dict) -> tuple[dict, bool, bool]:
    if not TELEGRAM_TOKEN:
        return cfg, False, False

    params = {"timeout": 5}
    offset = carregar_offset()
    if offset is not None:
        params["offset"] = offset

    resp = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
        params=params,
        timeout=20,
    )
    if resp.status_code != 200:
        return cfg, False, False

    updates = resp.json().get("result", [])
    houve_alteracao = False
    disparar_busca = False
    responder_status = False
    maior_update_id = offset

    for upd in updates:
        uid = upd.get("update_id")
        if uid is not None:
            maior_update_id = uid + 1

        msg = upd.get("message") or upd.get("edited_message") or {}
        chat_id = str(msg.get("chat", {}).get("id", "")).strip()
        texto = (msg.get("text") or "").strip()

        if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
            continue
        if not texto:
            continue

        cmd_lower = texto.lower()

        if cmd_lower.startswith("/start") or cmd_lower.startswith("/config"):
            responder_status = True

        elif cmd_lower.startswith("/reset"):
            cfg = dict(CONFIG_PADRAO)
            houve_alteracao = True
            responder_status = True

        elif cmd_lower.startswith("/corridos"):
            nums = [int(n) for n in re.findall(r"\d+", texto)]
            if len(nums) >= 2 and 1 <= nums[0] <= nums[1] <= 60:
                cfg["min_dias_corridos"] = nums[0]
                cfg["max_dias_corridos"] = nums[1]
                houve_alteracao = True
                responder_status = True
            else:
                enviar_telegram("⚠️ Use o formato: `/corridos 18 25` (mínimo e máximo de dias corridos).")

        elif cmd_lower.startswith("/uteis"):
            nums = [int(n) for n in re.findall(r"\d+", texto)]
            if len(nums) >= 2 and 0 <= nums[0] <= nums[1] <= 45:
                cfg["min_dias_uteis"] = nums[0]
                cfg["max_dias_uteis"] = nums[1]
                houve_alteracao = True
                responder_status = True
            else:
                enviar_telegram("⚠️ Use o formato: `/uteis 10 15` (mínimo e máximo de dias úteis).")

        elif cmd_lower.startswith("/alvo"):
            nums = re.findall(r"\d+(?:[.,]\d+)?", texto)
            if nums:
                valor = float(nums[0].replace(",", "."))
                if valor > 0:
                    cfg["preco_alvo_brl"] = valor
                    houve_alteracao = True
                    responder_status = True

        elif cmd_lower.startswith("/meses"):
            meses = [int(m) for m in re.findall(r"\b(?:9|10|11)\b", texto)]
            if meses:
                cfg["meses"] = sorted(set(meses))
                houve_alteracao = True
                responder_status = True
            else:
                enviar_telegram("⚠️ Informe meses válidos entre `9`, `10` e `11` (ex.: `/meses 10,11`).")

        elif cmd_lower.startswith("/buscar"):
            disparar_busca = True

    if maior_update_id is not None:
        salvar_offset(maior_update_id)

    if houve_alteracao:
        salvar_config(cfg)

    if responder_status:
        enviar_telegram(formatar_status(cfg))

    return cfg, houve_alteracao, disparar_busca


def contar_dias_uteis(ida: date, volta: date) -> int:
    uteis = 0
    atual = ida
    while atual <= volta:
        if atual.weekday() < 5 and atual not in FERIADOS_BR_2027:
            uteis += 1
        atual += timedelta(days=1)
    return uteis


def gerar_combinacoes(cfg: dict) -> list[dict]:
    meses_validos = set(cfg.get("meses", [9, 10, 11]))
    min_corr = cfg["min_dias_corridos"]
    max_corr = cfg["max_dias_corridos"]
    min_uteis = cfg["min_dias_uteis"]
    max_uteis = cfg["max_dias_uteis"]
    limite = cfg.get("limite_buscas", 16)

    inicio_busca = date(2027, 9, 1)
    fim_busca = date(2027, 11, 30)
    candidatas = []

    dia_ida = inicio_busca
    while dia_ida <= fim_busca - timedelta(days=min_corr - 1):
        for duracao in range(min_corr, max_corr + 1):
            dia_volta = dia_ida + timedelta(days=duracao - 1)
            if dia_volta > fim_busca:
                break

            if (dia_ida.month not in meses_validos) and (dia_volta.month not in meses_validos):
                continue

            uteis = contar_dias_uteis(dia_ida, dia_volta)
            if not (min_uteis <= uteis <= max_uteis):
                continue

            candidatas.append({
                "ida": dia_ida.isoformat(),
                "volta": dia_volta.isoformat(),
                "ida_br": dia_ida.strftime("%d/%m"),
                "volta_br": dia_volta.strftime("%d/%m"),
                "dias_corridos": duracao,
                "dias_uteis": uteis,
            })
        dia_ida += timedelta(days=1)

    candidatas.sort(key=lambda x: (x["dias_uteis"], -x["dias_corridos"]))

    selecionadas = []
    for c in candidatas:
        if any(
            abs((date.fromisoformat(c["ida"]) - date.fromisoformat(s["ida"])).days) < 2
            and c["dias_corridos"] == s["dias_corridos"]
            for s in selecionadas
        ):
            continue
        selecionadas.append(c)
        if len(selecionadas) >= limite:
            break

    return selecionadas


def eh_segunda_manha_brt() -> bool:
    fuso_brt = timezone(timedelta(hours=-3))
    agora_brt = datetime.now(fuso_brt)
    return agora_brt.weekday() == 0 and 7 <= agora_brt.hour <= 12


def executar():
    cfg = carregar_config()
    cfg, houve_alteracao, disparar_busca = processar_comandos_telegram(cfg)

    evento_manual = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
    combinacoes = gerar_combinacoes(cfg)

    if not combinacoes:
        enviar_telegram(
            "⚠️ Nenhuma combinação de datas atendeu simultaneamente aos filtros de "
            f"*dias corridos ({cfg['min_dias_corridos']}–{cfg['max_dias_corridos']})*, "
            f"*dias úteis ({cfg['min_dias_uteis']}–{cfg['max_dias_uteis']})* e *meses {cfg['meses']}*."
        )
        return

    resultados = []
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
            "stops": "1",
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
            resultados.append({
                "preco": float(preco),
                "dias_uteis": comb["dias_uteis"],
                "dias_corridos": comb["dias_corridos"],
                "ida_br": comb["ida_br"],
                "volta_br": comb["volta_br"],
                "cia": cia,
            })

    resultados.sort(key=lambda x: (x["preco"], x["dias_uteis"], -x["dias_corridos"]))

    unicos = []
    vistos = set()
    for r in resultados:
        chave = (r["cia"], r["ida_br"], r["volta_br"])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(r)

    preco_alvo = float(cfg["preco_alvo_brl"])
    alertas = [r for r in unicos if r["preco"] <= preco_alvo]

    if alertas:
        linhas_alerta = [
            f"• *R$ {r['preco']:,.2f}* — {r['cia']}\n"
            f"  📅 {r['ida_br']} a {r['volta_br']} ({r['dias_corridos']}d corridos / *{r['dias_uteis']}d úteis*)"
            for r in alertas[:10]
        ]
        enviar_telegram(
            f"🚨 *ALERTA VOO DIRETO GRU → MAD (≤ R$ {preco_alvo:,.0f})*\n\n"
            + "\n\n".join(linhas_alerta)
        )

    if eh_segunda_manha_brt() or evento_manual or disparar_busca or houve_alteracao:
        if unicos:
            linhas_rank = [
                f"{idx}. *R$ {r['preco']:,.2f}* ({r['cia']})\n"
                f"   📅 {r['ida_br']} a {r['volta_br']} — {r['dias_corridos']}d corridos | *{r['dias_uteis']}d úteis*"
                for idx, r in enumerate(unicos[:15], start=1)
            ]
            msg = (
                "📊 *Ranking Voos Diretos GRU → MAD*\n"
                f"Filtros: *{cfg['min_dias_corridos']}–{cfg['max_dias_corridos']}d corridos* | "
                f"*{cfg['min_dias_uteis']}–{cfg['max_dias_uteis']}d úteis*\n"
                "Ordenado por: *Menor Preço → Menos Dias Úteis*\n\n"
                + "\n\n".join(linhas_rank)
            )
        else:
            msg = (
                "📊 *Ranking Voos Diretos GRU → MAD*\n"
                "Nenhuma tarifa direta encontrada nas datas filtradas hoje."
            )
        enviar_telegram(msg)


if __name__ == "__main__":
    executar()

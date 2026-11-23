def gerar_combinacoes(cfg: dict) -> list[dict]:
    meses_validos = set(cfg.get("meses", [9, 10, 11]))
    min_corr = cfg["min_dias_corridos"]
    max_corr = cfg["max_dias_corridos"]
    min_uteis = cfg["min_dias_uteis"]
    max_uteis = cfg["max_dias_uteis"]
    limite = cfg.get("limite_buscas", 16)

    inicio_busca = date(2027, 9, 1)
    fim_busca = date(2027, 11, 30)
    por_duracao: dict[int, list[dict]] = {d: [] for d in range(min_corr, max_corr + 1)}

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

            por_duracao[duracao].append({
                "ida": dia_ida.isoformat(),
                "volta": dia_volta.isoformat(),
                "ida_br": dia_ida.strftime("%d/%m"),
                "volta_br": dia_volta.strftime("%d/%m"),
                "dias_corridos": duracao,
                "dias_uteis": uteis,
            })
        dia_ida += timedelta(days=1)

    # Dentro de cada duração, ordena pelas que usam menos dias úteis e espaça as datas
    filas_por_duracao = []
    for duracao in range(min_corr, max_corr + 1):
        lista = sorted(por_duracao[duracao], key=lambda x: (x["dias_uteis"], x["ida"]))
        filtrada = []
        for item in lista:
            if any(abs((date.fromisoformat(item["ida"]) - date.fromisoformat(f["ida"])).days) < 3 for f in filtrada):
                continue
            filtrada.append(item)
        if filtrada:
            filas_por_duracao.append(filtrada)

    # Seleciona em formato round-robin (1 de cada duração por rodada) até atingir 'limite'
    selecionadas = []
    idx_item = 0
    while len(selecionadas) < limite:
        adicionou_nesta_volta = False
        for fila in filas_por_duracao:
            if idx_item < len(fila):
                selecionadas.append(fila[idx_item])
                adicionou_nesta_volta = True
                if len(selecionadas) >= limite:
                    break
        if not adicionou_nesta_volta:
            break
        idx_item += 1

    return selecionadas

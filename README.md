# Pipeline ETL - Monitoramento de Obras e Recapes em SP

Pipeline em Python para coletar, transformar e visualizar ordens de servico e recapeamentos vinculados a operacao da Sabesp em Sao Paulo.

## Problema

Equipes de campo e gestao de obras lidam com dados fragmentados em sistemas diferentes, sem uma visao unica de status, prazos e distribuicao geografica das demandas.

## Solucao

O projeto consolida tres fontes operacionais, normaliza os registros e gera um dashboard interativo com:

- KPIs de cobertura e situacao
- filtros por fonte, regional e status
- graficos de distribuicao e evolucao temporal
- mapa com notificacoes e trechos de recape

## Estrutura

```text
obras-sp-pipeline/
|-- data/
|   |-- raw/          # arquivos de entrada locais, nao versionar
|   |-- processed/    # saidas geradas pelo pipeline, nao versionar
|   `-- cache/        # cache geoespacial local, nao versionar
|-- src/
|   `-- transform.py  # ETL: leitura, limpeza, cruzamento e geometria
|-- dashboard/
|   `-- app.py        # Dashboard Streamlit
|-- requirements.txt
`-- README.md
```

## Fontes de dados

- `sgz_156.csv`: ordens de servico abertas pelo canal 156
- `sgz_convias.csv`: notificacoes do sistema Convias
- `recape.xlsx` ou `recape.csv`: base de recapeamentos

## Regras do mapa

- Notificacoes aparecem como pontos
- Recapes aparecem como linhas, em camada separada
- Cores dos recapes:
  - vermelho: concluido ha menos de 1 ano
  - cinza claro: concluido ha mais de 1 ano
  - amarelo: planejado
  - azul: em execucao

## Como rodar

```bash
pip install -r requirements.txt
python src/transform.py
streamlit run dashboard/app.py
```

## Observacoes importantes

- Feche `qualquer arquivo da pasta data/raw` antes de rodar o ETL. Em Windows, arquivo aberto pode bloquear a leitura.
- Os dados em `data/raw/`, `data/processed/` e `data/cache/` sao locais e nao devem ser publicados no GitHub.
- O projeto pode conter dados operacionais com informacoes sensiveis, como endereco, localizacao e identificadores de OS. Antes de publicar um repositorio aberto, revise os arquivos e avalie o risco de LGPD.

## Autor

Gabriel Bitencourt

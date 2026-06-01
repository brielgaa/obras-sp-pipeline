import streamlit as st
import pandas as pd
import os
import json
import unicodedata
import pydeck as pdk

st.set_page_config(page_title="Auditoria de OSs × Recape | SP", page_icon="🏗️", layout="wide")

PROJECT_DIR = os.path.dirname(os.path.dirname(__file__))
PROCESSED_DIR = os.path.join(PROJECT_DIR, 'data', 'processed')

@st.cache_data
def load_data():
    cruzamento   = pd.read_csv(os.path.join(PROCESSED_DIR, 'cruzamento.csv'), parse_dates=['data_recebimento','data_termino_recape'], low_memory=False)
    recape       = pd.read_csv(os.path.join(PROCESSED_DIR, 'recape_clean.csv'), parse_dates=['data_criacao','data_termino'], low_memory=False)
    notificacoes = pd.read_csv(os.path.join(PROCESSED_DIR, 'notificacoes.csv'), parse_dates=['data_recebimento'], low_memory=False)
    return cruzamento, recape, notificacoes

cruzamento, recape, notificacoes = load_data()

HOJE = pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None).normalize()


def classificar_recape(row):
    status = str(row.get('status', '')).strip().upper()
    status = unicodedata.normalize('NFKD', status).encode('ascii', 'ignore').decode('ascii')
    data_termino = pd.to_datetime(row.get('data_termino'), errors='coerce')
    if status.startswith('CONCLUIDO') and pd.notna(data_termino):
        if (HOJE - data_termino.normalize()).days <= 365:
            return 'CONCLUIDO_RECENTE'
        return 'CONCLUIDO_ANTIGO'
    if status in {'EM_EXECUCAO', 'EM EXECUCAO', 'EXECUCAO', 'EM_ANDAMENTO'}:
        return 'EM_EXECUCAO'
    if status in {'PLANEJADO', 'CONTRATADO', 'A_CONTRATAR_CURTO_PRAZO', 'APENAS_INFRA'}:
        return 'PLANEJADO'
    return 'OUTRO'


RECAPE_CORES = {
    'CONCLUIDO_RECENTE': [220, 38, 38, 235],
    'CONCLUIDO_ANTIGO': [210, 210, 210, 170],
    'EM_EXECUCAO': [0, 122, 255, 225],
    'PLANEJADO': [255, 204, 0, 225],
    'OUTRO': [160, 160, 160, 140],
}

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
st.sidebar.title("🔍 Filtros")

regionais = ['Todas'] + sorted(cruzamento['prefeitura_regional'].dropna().unique().tolist())
regional_sel = st.sidebar.selectbox("Prefeitura Regional", regionais)

situacoes = ['Todas'] + sorted(cruzamento['situacao'].dropna().unique().tolist())
situacao_sel = st.sidebar.selectbox("Situação", situacoes)

fontes = ['Todas'] + sorted(cruzamento['fonte_notif'].dropna().unique().tolist())
fonte_sel = st.sidebar.selectbox("Fonte da Notificação", fontes)

df = cruzamento.copy()
if regional_sel != 'Todas':
    df = df[df['prefeitura_regional'] == regional_sel]
if situacao_sel != 'Todas':
    df = df[df['situacao'] == situacao_sel]
if fonte_sel != 'Todas':
    df = df[df['fonte_notif'] == fonte_sel]

# ── CABEÇALHO ─────────────────────────────────────────────────────────────────
st.title("🏗️ Auditoria de Notificações × Recapeamentos — SP")
st.caption("Cruzamento entre notificações SGZ/Convias e a base de recapeamentos da Sabesp")
st.divider()

# ── KPIs ──────────────────────────────────────────────────────────────────────
total        = len(df)
concluido    = len(df[df['situacao'] == '✅ Recape concluído'])
planejado    = len(df[df['situacao'] == '⚠️ Recape planejado'])
andamento    = len(df[df['situacao'] == '🟡 Em andamento'])
sem_cobertura= len(df[df['situacao'] == '🔴 Sem cobertura'])
pct_cobertura = ((total - sem_cobertura) / total * 100) if total > 0 else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total de Notificações", f"{total:,}")
c2.metric("✅ Recape Concluído",   f"{concluido:,}", help="Base sólida para defesa administrativa")
c3.metric("⚠️ Recape Planejado",  f"{planejado:,}", help="Comunicar prazo à PMSP")
c4.metric("🔴 Sem Cobertura",     f"{sem_cobertura:,}", help="Demandas que precisam de ação")
c5.metric("Cobertura Geral",      f"{pct_cobertura:.1f}%")

st.divider()

# ── LINHA 1: distribuição ─────────────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("📊 Situação das Notificações")
    sit_count = df['situacao'].value_counts().reset_index()
    sit_count.columns = ['Situação', 'Qtd']
    st.bar_chart(sit_count.set_index('Situação'))

with col_b:
    st.subheader("📍 Notificações por Regional")
    reg_count = df['prefeitura_regional'].value_counts().head(15).reset_index()
    reg_count.columns = ['Regional', 'Qtd']
    st.bar_chart(reg_count.set_index('Regional'))

# ── LINHA 2: análises operacionais ───────────────────────────────────────────
col_c, col_d = st.columns(2)

with col_c:
    st.subheader("📅 Notificações por Mês")
    df_t = df.dropna(subset=['data_recebimento']).copy()
    df_t['mes'] = df_t['data_recebimento'].dt.to_period('M').astype(str)
    mensal = df_t.groupby(['mes', 'situacao']).size().unstack(fill_value=0)
    st.bar_chart(mensal)

with col_d:
    st.subheader("🏗️ Status dos Recapes correspondentes")
    rec_status = df.dropna(subset=['status_recape'])['status_recape'].value_counts().reset_index()
    rec_status.columns = ['Status Recape', 'Qtd']
    if not rec_status.empty:
        st.bar_chart(rec_status.set_index('Status Recape'))
    else:
        st.info("Nenhum recape encontrado com os filtros selecionados.")

# ── MAPA ──────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("🗺️ Localização das Notificações")

df_mapa = df.dropna(subset=['latitude', 'longitude']).copy()
df_mapa = df_mapa[
    df_mapa['latitude'].between(-24.1, -23.3) &
    df_mapa['longitude'].between(-47.0, -46.3)
]

def parse_linha_recape(row):
    for col in ['path', 'geometry', 'geojson', 'wkt']:
        if col not in row or pd.isna(row[col]):
            continue
        valor = str(row[col]).strip()
        if not valor:
            continue
        try:
            if valor.upper().startswith('LINESTRING'):
                coords = valor.split('(', 1)[1].rsplit(')', 1)[0].split(',')
                return [[float(x), float(y)] for x, y in (p.strip().split()[:2] for p in coords)]
            geo = json.loads(valor)
            if isinstance(geo, dict):
                if geo.get('type') == 'LineString':
                    return geo.get('coordinates')
                if geo.get('type') == 'Feature':
                    geom = geo.get('geometry') or {}
                    if geom.get('type') == 'LineString':
                        return geom.get('coordinates')
            if isinstance(geo, list):
                return geo
        except Exception:
            continue
    return None

recapes_mapa = recape.copy()
recapes_mapa['path'] = recapes_mapa.apply(parse_linha_recape, axis=1)
recapes_mapa = recapes_mapa[recapes_mapa['path'].notna()].copy()
if not recapes_mapa.empty:
    recapes_mapa['status_visual'] = recapes_mapa.apply(classificar_recape, axis=1)
    recapes_mapa['path_color'] = recapes_mapa['status_visual'].map(RECAPE_CORES)
    recapes_mapa['path_color'] = recapes_mapa['path_color'].apply(
        lambda cor: cor if isinstance(cor, list) else RECAPE_CORES['OUTRO']
    )

if not df_mapa.empty or not recapes_mapa.empty:
    df_mapa['data_recebimento_fmt'] = df_mapa['data_recebimento'].dt.strftime('%d/%m/%Y').fillna('')
    df_mapa['tooltip_tipo'] = df_mapa['fonte_notif'].fillna('Notificação')
    df_mapa['tooltip_rua'] = df_mapa['rua_notif'].fillna('')
    df_mapa['tooltip_status'] = df_mapa['situacao'].fillna('')
    df_mapa['tooltip_recape'] = df_mapa['rua_recape'].fillna('')
    df_mapa['tooltip_trecho'] = ''
    convias_mapa = df_mapa[df_mapa['fonte_notif'] == 'SGZ_CONVIAS'].copy()
    sgz_156_mapa = df_mapa[df_mapa['fonte_notif'] == 'SGZ_156'].copy()
    if not recapes_mapa.empty:
        recapes_mapa['tooltip_tipo'] = 'RECAPE'
        recapes_mapa['tooltip_rua'] = recapes_mapa.get('rua_raw', '').fillna('')
        recapes_mapa['tooltip_status'] = recapes_mapa.get('status', '').fillna('')
        recapes_mapa['tooltip_status_visual'] = recapes_mapa['status_visual'].fillna('')
        recapes_mapa['tooltip_recape'] = recapes_mapa.get('rua_raw', '').fillna('')
        recapes_mapa['tooltip_trecho'] = (
            recapes_mapa.get('de', '').fillna('') + ' até ' + recapes_mapa.get('ate', '').fillna('')
        )
        recapes_mapa['data_recebimento_fmt'] = ''
        recapes_mapa['numero_os'] = ''
        recapes_mapa['prefeitura_regional'] = recapes_mapa.get('subprefeitura', '').fillna('')

    layers = []
    if not recapes_mapa.empty:
        layers.append(pdk.Layer(
            'PathLayer',
            data=recapes_mapa,
            get_path='path',
            get_color='path_color',
            get_width=5,
            width_min_pixels=2,
            pickable=True,
            auto_highlight=True,
        ))
    if not convias_mapa.empty:
        layers.append(pdk.Layer(
            'ScatterplotLayer',
            data=convias_mapa,
            get_position='[longitude, latitude]',
            get_fill_color=[230, 38, 25, 210],
            get_line_color=[255, 255, 255, 180],
            get_radius=25,
            radius_min_pixels=3,
            radius_max_pixels=8,
            stroked=True,
            line_width_min_pixels=1,
            pickable=True,
            auto_highlight=True,
        ))
    if not sgz_156_mapa.empty:
        layers.append(pdk.Layer(
            'ScatterplotLayer',
            data=sgz_156_mapa,
            get_position='[longitude, latitude]',
            get_fill_color=[245, 196, 0, 220],
            get_line_color=[40, 40, 40, 190],
            get_radius=25,
            radius_min_pixels=3,
            radius_max_pixels=8,
            stroked=True,
            line_width_min_pixels=1,
            pickable=True,
            auto_highlight=True,
        ))

    st.pydeck_chart(pdk.Deck(
        map_style='https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
        initial_view_state=pdk.ViewState(
            latitude=-23.62,
            longitude=-46.62,
            zoom=9.4,
            pitch=0,
        ),
        layers=layers,
        tooltip={
            'html': (
                '<b>{tooltip_tipo}</b><br/>'
                'OS: {numero_os}<br/>'
                'Rua: {tooltip_rua}<br/>'
                'Regional: {prefeitura_regional}<br/>'
                'Recebimento: {data_recebimento_fmt}<br/>'
                'Situação: {tooltip_status}<br/>'
                '<hr/>'
                '<b>Recape</b><br/>'
                'Rua: {tooltip_recape}<br/>'
                'Trecho: {tooltip_trecho}<br/>'
                'Classe: {tooltip_status_visual}<br/>'
                'Extensão: {extensao_m} m'
            ),
            'style': {'backgroundColor': '#111827', 'color': 'white'}
        }
    ), use_container_width=True)
    st.caption(
        f"{len(convias_mapa):,} notificações Convias em vermelho · "
        f"{len(sgz_156_mapa):,} notificações 156 em amarelo · "
        f"{len(recapes_mapa):,} trechos de recape em linha"
    )
    if recapes_mapa.empty:
        st.info("A base atual de recapes não traz geometria linear do trecho; quando houver coluna geometry/geojson/wkt/path, o mapa desenha as linhas das ruas automaticamente.")
else:
    st.info("Sem coordenadas válidas com os filtros atuais.")

# ── TABELA PRINCIPAL: O CRUZAMENTO ────────────────────────────────────────────
st.divider()
st.subheader("📋 Detalhamento do Cruzamento")
st.caption("Cada notificação com o recapeamento correspondente encontrado — base para defesas administrativas.")

cols_exibir = [
    'situacao', 'numero_os', 'fonte_notif', 'rua_notif',
    'prefeitura_regional', 'data_recebimento', 'status_notif',
    'rua_recape', 'status_recape', 'data_termino_recape',
    'extensao_m', 'area_m2', 'metodo_match', 'score_fuzzy', 'dist_recape_km'
]
cols_validas = [c for c in cols_exibir if c in df.columns]

st.dataframe(
    df[cols_validas].sort_values('situacao'),
    use_container_width=True,
    height=450,
    column_config={
        'situacao':            st.column_config.TextColumn('Situação'),
        'numero_os':           st.column_config.TextColumn('Nº OS'),
        'fonte_notif':         st.column_config.TextColumn('Fonte'),
        'rua_notif':           st.column_config.TextColumn('Rua (Notificação)'),
        'prefeitura_regional': st.column_config.TextColumn('Regional'),
        'data_recebimento':    st.column_config.DateColumn('Recebimento', format='DD/MM/YYYY'),
        'status_notif':        st.column_config.TextColumn('Status OS'),
        'rua_recape':          st.column_config.TextColumn('Rua (Recape)'),
        'status_recape':       st.column_config.TextColumn('Status Recape'),
        'data_termino_recape': st.column_config.DateColumn('Término Recape', format='DD/MM/YYYY'),
        'extensao_m':          st.column_config.NumberColumn('Extensão (m)', format='%.0f m'),
        'area_m2':             st.column_config.NumberColumn('Área (m²)', format='%.0f m²'),
        'metodo_match':        st.column_config.TextColumn('Como foi cruzado'),
        'score_fuzzy':         st.column_config.ProgressColumn('Confiança', min_value=0, max_value=100),
        'dist_recape_km':      st.column_config.NumberColumn('Dist. recape (km)', format='%.3f km'),
    }
)

# ── EXPORTAR ──────────────────────────────────────────────────────────────────
st.divider()
col_exp1, col_exp2 = st.columns(2)

with col_exp1:
    csv_bytes = df[cols_validas].to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        "⬇️ Exportar tabela (CSV)",
        data=csv_bytes,
        file_name="cruzamento_os_recape.csv",
        mime='text/csv'
    )

with col_exp2:
    sem_cob = df[df['situacao'] == '🔴 Sem cobertura'][cols_validas]
    if not sem_cob.empty:
        csv_sc = sem_cob.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "⬇️ Exportar só as SEM COBERTURA",
            data=csv_sc,
            file_name="sem_cobertura.csv",
            mime='text/csv'
        )

st.caption(f"Exibindo {len(df):,} de {len(cruzamento):,} registros · Rode `python src/transform.py` para atualizar.")

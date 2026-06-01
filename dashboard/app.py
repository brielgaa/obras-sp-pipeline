import json
import os
import unicodedata

import pandas as pd
import pydeck as pdk
import streamlit as st

st.set_page_config(
    page_title="Auditoria de OSs x Recape | SP",
    page_icon="🏗️",
    layout="wide",
)

PROJECT_DIR = os.path.dirname(os.path.dirname(__file__))
PROCESSED_DIR = os.path.join(PROJECT_DIR, "data", "processed")


@st.cache_data
def load_data():
    cruzamento = pd.read_csv(
        os.path.join(PROCESSED_DIR, "cruzamento.csv"),
        parse_dates=["data_recebimento", "data_termino_recape"],
        low_memory=False,
    )
    recape = pd.read_csv(
        os.path.join(PROCESSED_DIR, "recape_clean.csv"),
        parse_dates=["data_criacao", "data_termino"],
        low_memory=False,
    )
    notificacoes = pd.read_csv(
        os.path.join(PROCESSED_DIR, "notificacoes.csv"),
        parse_dates=["data_recebimento"],
        low_memory=False,
    )
    return cruzamento, recape, notificacoes


cruzamento, recape, notificacoes = load_data()

HOJE = pd.Timestamp.now().normalize()


def normalizar_texto(valor: str) -> str:
    valor = str(valor).strip().upper()
    return unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode("ascii")


def resolver_tema_base(escolha: str) -> str:
    if escolha == "Sistema":
        base = str(st.get_option("theme.base") or "light").lower()
        return "dark" if base == "dark" else "light"
    return "dark" if escolha == "Escuro" else "light"


def aplicar_css_tema(tema_base: str) -> None:
    if tema_base == "dark":
        bg = "#0b1220"
        fg = "#e5e7eb"
        card = "#111827"
        muted = "#334155"
        sidebar = "#0f172a"
        control_bg = "#111827"
    else:
        bg = "#f8fafc"
        fg = "#0f172a"
        card = "#ffffff"
        muted = "#cbd5e1"
        sidebar = "#eef2ff"
        control_bg = "#ffffff"

    st.markdown(
        f"""
        <style>
            .stApp {{
                background: {bg};
                color: {fg} !important;
            }}
            .stApp, .stApp * {{
                color: {fg} !important;
            }}
            section[data-testid="stSidebar"] {{
                background: {sidebar};
            }}
            section[data-testid="stSidebar"] * {{
                color: {fg} !important;
            }}
            section[data-testid="stSidebar"] label,
            section[data-testid="stSidebar"] p,
            section[data-testid="stSidebar"] span,
            section[data-testid="stSidebar"] div {{
                color: {fg} !important;
            }}
            section[data-testid="stSidebar"] input,
            section[data-testid="stSidebar"] textarea,
            section[data-testid="stSidebar"] button {{
                color: {fg} !important;
                background: {control_bg} !important;
            }}
            section[data-testid="stSidebar"] [data-baseweb="select"] *,
            section[data-testid="stSidebar"] [data-baseweb="popover"] *,
            section[data-testid="stSidebar"] [role="radiogroup"] *,
            section[data-testid="stSidebar"] [role="radio"] *,
            section[data-testid="stSidebar"] [data-testid="stSelectbox"] *,
            section[data-testid="stSidebar"] [data-testid="stRadio"] * {{
                color: {fg} !important;
            }}
            section[data-testid="stSidebar"] [data-baseweb="select"] input,
            section[data-testid="stSidebar"] [data-baseweb="select"] div,
            section[data-testid="stSidebar"] [data-baseweb="select"] span,
            section[data-testid="stSidebar"] [data-baseweb="select"] svg {{
                color: {fg} !important;
                fill: {fg} !important;
            }}
            section[data-testid="stSidebar"] [data-baseweb="select"] > div {{
                background: {control_bg} !important;
                border-color: {muted} !important;
            }}
            section[data-testid="stSidebar"] [data-baseweb="menu"] *,
            section[data-testid="stSidebar"] [data-baseweb="option"] * {{
                color: {fg} !important;
                background: {control_bg} !important;
            }}
            body .stApp [data-baseweb="popover"],
            body .stApp [data-baseweb="menu"],
            body .stApp [data-baseweb="menu"] *,
            body .stApp [role="listbox"],
            body .stApp [role="option"],
            body .stApp [data-baseweb="option"] {{
                background: {control_bg} !important;
                color: {fg} !important;
            }}
            body .stApp [data-baseweb="popover"] *,
            body .stApp [role="listbox"] *,
            body .stApp [role="option"] * {{
                color: {fg} !important;
                background: {control_bg} !important;
            }}
            body .stApp [data-baseweb="select"] input::placeholder {{
                color: {fg} !important;
                opacity: 0.7 !important;
            }}
            div[data-testid="stMetric"] {{
                background: {card};
                border: 1px solid {muted};
                border-radius: 14px;
                padding: 12px 14px;
            }}
            div[data-testid="stMetric"] * {{
                color: {fg} !important;
            }}
            .stMarkdown, .stCaption, .stTextInput, .stSelectbox, .stRadio, .stButton, .stTabs, .stDataFrame {{
                color: {fg} !important;
            }}
            h1, h2, h3, h4, h5, h6, p, span, label, div, small {{
                color: {fg} !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def classificar_recape(row):
    status = normalizar_texto(row.get("status", ""))
    data_termino = pd.to_datetime(row.get("data_termino"), errors="coerce")
    if status.startswith("CONCLUIDO") and pd.notna(data_termino):
        if (HOJE - data_termino.normalize()).days <= 365:
            return "CONCLUIDO_RECENTE"
        return "CONCLUIDO_ANTIGO"
    if status in {"EM_EXECUCAO", "EM EXECUCAO", "EXECUCAO", "EM_ANDAMENTO"}:
        return "EM_EXECUCAO"
    if status in {"PLANEJADO", "CONTRATADO", "A_CONTRATAR_CURTO_PRAZO", "APENAS_INFRA"}:
        return "PLANEJADO"
    return "OUTRO"


RECAPE_CORES = {
    "CONCLUIDO_RECENTE": [220, 38, 38, 255],
    "CONCLUIDO_ANTIGO": [210, 210, 210, 210],
    "EM_EXECUCAO": [0, 122, 255, 255],
    "PLANEJADO": [255, 204, 0, 255],
    "OUTRO": [160, 160, 160, 180],
}


def parse_linha_recape(row):
    for col in ["path", "geometry", "geojson", "wkt"]:
        if col not in row or pd.isna(row[col]):
            continue
        valor = str(row[col]).strip()
        if not valor:
            continue
        try:
            if valor.upper().startswith("LINESTRING"):
                coords = valor.split("(", 1)[1].rsplit(")", 1)[0].split(",")
                return [[float(x), float(y)] for x, y in (p.strip().split()[:2] for p in coords)]
            geo = json.loads(valor)
            if isinstance(geo, dict):
                if geo.get("type") == "LineString":
                    return geo.get("coordinates")
                if geo.get("type") == "Feature":
                    geom = geo.get("geometry") or {}
                    if geom.get("type") == "LineString":
                        return geom.get("coordinates")
            if isinstance(geo, list):
                return geo
        except Exception:
            continue
    return None


@st.cache_data
def preparar_df_mapa(df: pd.DataFrame) -> pd.DataFrame:
    df_mapa = df.dropna(subset=["latitude", "longitude"]).copy()
    return df_mapa[
        df_mapa["latitude"].between(-24.1, -23.3)
        & df_mapa["longitude"].between(-47.0, -46.3)
    ]


@st.cache_data
def preparar_recapes_mapa(recape_df: pd.DataFrame) -> pd.DataFrame:
    recapes_mapa = recape_df.copy()
    recapes_mapa["path"] = recapes_mapa.apply(parse_linha_recape, axis=1)
    recapes_mapa = recapes_mapa[recapes_mapa["path"].notna()].copy()
    if not recapes_mapa.empty:
        recapes_mapa["status_visual"] = recapes_mapa.apply(classificar_recape, axis=1)
        recapes_mapa["path_color"] = recapes_mapa["status_visual"].map(RECAPE_CORES)
        recapes_mapa["path_color"] = recapes_mapa["path_color"].apply(
            lambda cor: cor if isinstance(cor, list) else RECAPE_CORES["OUTRO"]
        )
    return recapes_mapa


@st.cache_data
def preparar_tabela_cruzamento(df: pd.DataFrame, regional_sel: str, situacao_sel: str, fonte_sel: str) -> pd.DataFrame:
    tabela = df.copy()
    if regional_sel != "Todas":
        tabela = tabela[tabela["prefeitura_regional"] == regional_sel]
    if situacao_sel != "Todas":
        tabela = tabela[tabela["situacao"] == situacao_sel]
    if fonte_sel != "Todas":
        tabela = tabela[tabela["fonte_notif"] == fonte_sel]
    return tabela


st.sidebar.title("Filtros")

regionais = ["Todas"] + sorted(cruzamento["prefeitura_regional"].dropna().unique().tolist())
regional_sel = st.sidebar.selectbox("Prefeitura Regional", regionais)

situacoes = ["Todas"] + sorted(cruzamento["situacao"].dropna().unique().tolist())
situacao_sel = st.sidebar.selectbox("Situação", situacoes)

fontes = ["Todas"] + sorted(cruzamento["fonte_notif"].dropna().unique().tolist())
fonte_sel = st.sidebar.selectbox("Fonte da Notificação", fontes)

tema_sel = st.sidebar.radio(
    "Tema",
    ["Sistema", "Claro", "Escuro"],
    index=0,
    help="O modo Sistema segue a base configurada no Streamlit/ambiente.",
)

modo_principal = st.sidebar.radio(
    "Painel principal",
    ["Mapa", "Detalhamento"],
    index=0,
    help="Mostra apenas uma área pesada por vez para reduzir recarregamentos.",
)

tema_base = resolver_tema_base(tema_sel)
aplicar_css_tema(tema_base)
df = preparar_tabela_cruzamento(cruzamento, regional_sel, situacao_sel, fonte_sel)

st.title("Auditoria de Notificações x Recapeamentos - SP")
st.caption("Cruzamento entre notificações SGZ/Convias e a base de recapeamentos.")
st.divider()

total = len(df)
concluido = len(df[df["situacao"] == "✅ Recape concluído"])
planejado = len(df[df["situacao"] == "⚠️ Recape planejado"])
andamento = len(df[df["situacao"] == "🟡 Em andamento"])
sem_cobertura = len(df[df["situacao"] == "🔴 Sem cobertura"])
pct_cobertura = ((total - sem_cobertura) / total * 100) if total > 0 else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total de Notificações", f"{total:,}")
c2.metric("Recape Concluído", f"{concluido:,}")
c3.metric("Recape Planejado", f"{planejado:,}")
c4.metric("Sem Cobertura", f"{sem_cobertura:,}")
c5.metric("Cobertura Geral", f"{pct_cobertura:.1f}%")

st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Situação das Notificações")
    sit_count = df["situacao"].value_counts().reset_index()
    sit_count.columns = ["Situação", "Qtd"]
    st.bar_chart(sit_count.set_index("Situação"))

with col_b:
    st.subheader("Notificações por Regional")
    reg_count = df["prefeitura_regional"].value_counts().head(15).reset_index()
    reg_count.columns = ["Regional", "Qtd"]
    st.bar_chart(reg_count.set_index("Regional"))

col_c, col_d = st.columns(2)
with col_c:
    st.subheader("Notificações por Mês")
    df_t = df.dropna(subset=["data_recebimento"]).copy()
    df_t["mes"] = df_t["data_recebimento"].dt.to_period("M").astype(str)
    mensal = df_t.groupby(["mes", "situacao"]).size().unstack(fill_value=0)
    st.bar_chart(mensal)

with col_d:
    st.subheader("Status dos Recapes Correspondentes")
    rec_status = df.dropna(subset=["status_recape"])["status_recape"].value_counts().reset_index()
    rec_status.columns = ["Status Recape", "Qtd"]
    if not rec_status.empty:
        st.bar_chart(rec_status.set_index("Status Recape"))
    else:
        st.info("Nenhum recape encontrado com os filtros selecionados.")

if modo_principal == "Mapa":
    st.divider()
    st.subheader("Localização das Notificações")

    df_mapa = preparar_df_mapa(df)
    recapes_mapa = preparar_recapes_mapa(recape)

    if not df_mapa.empty or not recapes_mapa.empty:
        df_mapa["data_recebimento_fmt"] = df_mapa["data_recebimento"].dt.strftime("%d/%m/%Y").fillna("")
        df_mapa["tooltip_tipo"] = df_mapa["fonte_notif"].fillna("Notificacao")
        df_mapa["tooltip_rua"] = df_mapa["rua_notif"].fillna("")
        df_mapa["tooltip_status"] = df_mapa["situacao"].fillna("")
        df_mapa["tooltip_recape"] = df_mapa["rua_recape"].fillna("")
        df_mapa["tooltip_trecho"] = ""
        convias_mapa = df_mapa[df_mapa["fonte_notif"] == "SGZ_CONVIAS"].copy()
        sgz_156_mapa = df_mapa[df_mapa["fonte_notif"] == "SGZ_156"].copy()

        if not recapes_mapa.empty:
            recapes_mapa["tooltip_tipo"] = "RECAPE"
            recapes_mapa["tooltip_rua"] = recapes_mapa.get("rua_raw", "").fillna("")
            recapes_mapa["tooltip_status"] = recapes_mapa.get("status", "").fillna("")
            recapes_mapa["tooltip_status_visual"] = recapes_mapa["status_visual"].fillna("")
            recapes_mapa["tooltip_recape"] = recapes_mapa.get("rua_raw", "").fillna("")
            recapes_mapa["tooltip_trecho"] = recapes_mapa.get("de", "").fillna("") + " até " + recapes_mapa.get("ate", "").fillna("")
            recapes_mapa["data_recebimento_fmt"] = ""
            recapes_mapa["numero_os"] = ""
            recapes_mapa["prefeitura_regional"] = recapes_mapa.get("subprefeitura", "").fillna("")

        layers = []
        if not recapes_mapa.empty:
            layers.append(
                pdk.Layer(
                    "PathLayer",
                    data=recapes_mapa,
                    get_path="path",
                    get_color="path_color",
                    get_width=5,
                    width_min_pixels=2,
                    pickable=True,
                    auto_highlight=True,
                )
            )
        if not convias_mapa.empty:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=convias_mapa,
                    get_position="[longitude, latitude]",
                    get_fill_color=[230, 38, 25, 210],
                    get_line_color=[255, 255, 255, 180],
                    get_radius=25,
                    radius_min_pixels=3,
                    radius_max_pixels=8,
                    stroked=True,
                    line_width_min_pixels=1,
                    pickable=True,
                    auto_highlight=True,
                )
            )
        if not sgz_156_mapa.empty:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=sgz_156_mapa,
                    get_position="[longitude, latitude]",
                    get_fill_color=[245, 196, 0, 220],
                    get_line_color=[40, 40, 40, 190],
                    get_radius=25,
                    radius_min_pixels=3,
                    radius_max_pixels=8,
                    stroked=True,
                    line_width_min_pixels=1,
                    pickable=True,
                    auto_highlight=True,
                )
            )

        st.pydeck_chart(
            pdk.Deck(
                map_provider="carto",
                map_style="dark" if tema_base == "dark" else "light",
                initial_view_state=pdk.ViewState(
                    latitude=-23.62,
                    longitude=-46.62,
                    zoom=9.4,
                    pitch=0,
                ),
                layers=layers,
                tooltip={
                    "html": (
                        "<b>{tooltip_tipo}</b><br/>"
                        "OS: {numero_os}<br/>"
                        "Rua: {tooltip_rua}<br/>"
                        "Regional: {prefeitura_regional}<br/>"
                        "Recebimento: {data_recebimento_fmt}<br/>"
                        "Situacao: {tooltip_status}<br/>"
                        "<hr/>"
                        "<b>Recape</b><br/>"
                        "Rua: {tooltip_recape}<br/>"
                        "Trecho: {tooltip_trecho}<br/>"
                        "Classe: {tooltip_status_visual}<br/>"
                        "Extensao: {extensao_m} m"
                    ),
                    "style": {"backgroundColor": "#111827", "color": "white"},
                },
            ),
            use_container_width=True,
        )
        st.caption(
            f"{len(convias_mapa):,} notificações Convias em vermelho · "
            f"{len(sgz_156_mapa):,} notificações 156 em amarelo · "
            f"{len(recapes_mapa):,} trechos de recape em linha"
        )
        if recapes_mapa.empty:
            st.info("A base atual de recapes não traz geometria linear do trecho; quando houver coluna geometry/geojson/wkt/path, o mapa desenha as linhas automaticamente.")
    else:
        st.info("Sem coordenadas válidas com os filtros atuais.")
else:
    st.divider()
    st.subheader("Detalhamento do Cruzamento")
    st.caption("Cada notificação com o recapeamento correspondente encontrado.")

    cols_exibir = [
        "situacao", "numero_os", "fonte_notif", "rua_notif",
        "prefeitura_regional", "data_recebimento", "status_notif",
        "rua_recape", "status_recape", "data_termino_recape",
        "extensao_m", "area_m2", "metodo_match", "score_fuzzy", "dist_recape_km"
    ]
    cols_validas = [c for c in cols_exibir if c in df.columns]
    df_tabela = df[cols_validas].sort_values("situacao")

    st.dataframe(
        df_tabela,
        use_container_width=True,
        height=450,
        column_config={
            "situacao": st.column_config.TextColumn("Situacao"),
            "numero_os": st.column_config.TextColumn("Nº OS"),
            "fonte_notif": st.column_config.TextColumn("Fonte"),
            "rua_notif": st.column_config.TextColumn("Rua (Notificacao)"),
            "prefeitura_regional": st.column_config.TextColumn("Regional"),
            "data_recebimento": st.column_config.DateColumn("Recebimento", format="DD/MM/YYYY"),
            "status_notif": st.column_config.TextColumn("Status OS"),
            "rua_recape": st.column_config.TextColumn("Rua (Recape)"),
            "status_recape": st.column_config.TextColumn("Status Recape"),
            "data_termino_recape": st.column_config.DateColumn("Termino Recape", format="DD/MM/YYYY"),
            "extensao_m": st.column_config.NumberColumn("Extensao (m)", format="%.0f m"),
            "area_m2": st.column_config.NumberColumn("Area (m²)", format="%.0f m²"),
            "metodo_match": st.column_config.TextColumn("Como foi cruzado"),
            "score_fuzzy": st.column_config.ProgressColumn("Confianca", min_value=0, max_value=100),
            "dist_recape_km": st.column_config.NumberColumn("Dist. recape (km)", format="%.3f km"),
        },
    )

    st.divider()
    col_exp1, col_exp2 = st.columns(2)

    with col_exp1:
        csv_bytes = df_tabela.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Exportar tabela (CSV)",
            data=csv_bytes,
            file_name="cruzamento_os_recape.csv",
            mime="text/csv",
        )

    with col_exp2:
        sem_cob = df[df["situacao"] == "🔴 Sem cobertura"][cols_validas]
        if not sem_cob.empty:
            csv_sc = sem_cob.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Exportar só as SEM COBERTURA",
                data=csv_sc,
                file_name="sem_cobertura.csv",
                mime="text/csv",
            )

    st.caption(f"Exibindo {len(df):,} de {len(cruzamento):,} registros · Rode `python src/transform.py` para atualizar.")

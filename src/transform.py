import pandas as pd
import os
import re
import math
import sys
import json
import unicodedata
from rapidfuzz import process, fuzz

try:
    import geopandas as gpd
    import requests
    from shapely.geometry import Point, LineString, MultiLineString
    from shapely.ops import linemerge, nearest_points, substring, transform as shp_transform
    from pyproj import Transformer
except ImportError:
    gpd = None
    requests = None

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

PROJECT_DIR = os.path.dirname(os.path.dirname(__file__))
RAW_DIR = os.path.join(PROJECT_DIR, 'data', 'raw')
PROCESSED_DIR = os.path.join(PROJECT_DIR, 'data', 'processed')
CACHE_DIR = os.path.join(PROJECT_DIR, 'data', 'cache')
GEOSAMPA_SEGMENTOS = os.path.join(CACHE_DIR, 'geosampa_segmento_logradouro.geojson')

# ─────────────────────────────────────────
# NORMALIZAÇÃO DE NOME DE RUA
# ─────────────────────────────────────────
_MOJIBAKE_MARKERS = ('Ã', 'Â', '�', '‰', 'Š', 'Œ', 'Ž', 'š', 'œ', 'ž', 'Ÿ')

def corrigir_texto(valor):
    if not isinstance(valor, str):
        return valor
    if not any(marker in valor for marker in _MOJIBAKE_MARKERS):
        return valor
    for encoding in ('cp1252', 'latin-1'):
        try:
            return valor.encode(encoding).decode('utf-8')
        except UnicodeError:
            continue
    return valor


def corrigir_textos_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [corrigir_texto(str(col)).strip() for col in df.columns]
    for col in df.select_dtypes(include='object').columns:
        df[col] = df[col].map(corrigir_texto)
    return df


_ABREVIACOES = {
    r'\bDR\b': 'DOUTOR',
    r'\bDRA\b': 'DOUTORA',
    r'\bPROF\b': 'PROFESSOR',
    r'\bPROFA\b': 'PROFESSORA',
    r'\bPRES\b': 'PRESIDENTE',
    r'\bDEP\b': 'DEPUTADO',
    r'\bENG\b': 'ENGENHEIRO',
    r'\bENGO\b': 'ENGENHEIRO',
    r'\bPE\b': 'PADRE',
    r'\bSTA\b': 'SANTA',
    r'\bSTO\b': 'SANTO',
    r'\bS\b': 'SAO',
    r'\bCEL\b': 'CORONEL',
    r'\bCAP\b': 'CAPITAO',
    r'\bGEN\b': 'GENERAL',
    r'\bEMB\b': 'EMBAIXADOR',
}


def normalizar_cep(valor) -> str:
    if not isinstance(valor, str):
        return ''
    return re.sub(r'\D', '', valor)


def parse_data(serie):
    return pd.to_datetime(serie, dayfirst=True, errors='coerce', format='mixed')


_PREFIXOS = re.compile(
    r'^(RUA|R\.?|AVENIDA|AV\.?|ALAMEDA|AL\.?|TRAVESSA|TV\.?|'
    r'ESTRADA|EST\.?|RODOVIA|ROD\.?|PRAÇA|PC\.?|LARGO|LGO\.?|'
    r'VIELA|VL\.?|VIADUTO|VD\.?)\s+', re.IGNORECASE
)

def normalizar_rua(nome: str) -> str:
    if not isinstance(nome, str):
        return ''
    nome = corrigir_texto(nome)
    nome = nome.upper().strip()
    nome = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode('ascii')
    nome = re.sub(r'[^\w\s]', ' ', nome)   # remove pontuação
    nome = _PREFIXOS.sub('', nome)          # remove prefixo de logradouro
    for padrao, substituto in _ABREVIACOES.items():
        nome = re.sub(padrao, substituto, nome)
    nome = re.sub(r'\s+', ' ', nome).strip()
    return nome


# ─────────────────────────────────────────
# DISTÂNCIA GEOGRÁFICA (haversine, km)
# ─────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    try:
        phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi       = math.radians(float(lat2) - float(lat1))
        dlambda    = math.radians(float(lon2) - float(lon1))
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    except Exception:
        return float('inf')


def coordenada_valida(lat, lon) -> bool:
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    return -24.1 <= lat <= -23.3 and -47.0 <= lon <= -46.3


def montar_indice_espacial(df_recape: pd.DataFrame, cell_size=0.005):
    indice = {}
    coords = []
    for idx, row in df_recape.iterrows():
        lat = row.get('latitude')
        lon = row.get('longitude')
        if not coordenada_valida(lat, lon):
            continue
        lat = float(lat)
        lon = float(lon)
        regional = str(row.get('subprefeitura', '')).strip().upper()
        coords.append((idx, lat, lon, regional))
        cell = (math.floor(lat / cell_size), math.floor(lon / cell_size))
        indice.setdefault(cell, []).append((idx, lat, lon, regional))
    return indice, cell_size, coords


def recape_mais_proximo(lat, lon, indice_espacial, limite_km=0.15, regional=None, exigir_regional=False):
    if not coordenada_valida(lat, lon):
        return None, float('inf')

    indice, cell_size, _ = indice_espacial
    lat = float(lat)
    lon = float(lon)
    regional = str(regional or '').strip().upper()
    cell_lat = math.floor(lat / cell_size)
    cell_lon = math.floor(lon / cell_size)
    alcance = math.ceil((limite_km / 111) / cell_size) + 1
    melhor_idx = None
    melhor_dist = float('inf')

    for dlat in range(-alcance, alcance + 1):
        for dlon in range(-alcance, alcance + 1):
            for idx, lat_r, lon_r, reg_r in indice.get((cell_lat + dlat, cell_lon + dlon), []):
                if exigir_regional and regional and reg_r != regional:
                    continue
                dist = haversine(lat, lon, lat_r, lon_r)
                if dist < melhor_dist:
                    melhor_idx = idx
                    melhor_dist = dist

    if melhor_dist <= limite_km:
        return melhor_idx, melhor_dist
    return None, melhor_dist


# ─────────────────────────────────────────
# LEITURA — RECAPE
# ─────────────────────────────────────────
def load_recape(filename='recape.csv') -> pd.DataFrame:
    candidate = os.path.join(RAW_DIR, filename)
    if not os.path.exists(candidate):
        for ext in ('.xlsx', '.xls', '.csv'):
            cand = os.path.join(RAW_DIR, f'recape{ext}')
            if os.path.exists(cand):
                candidate = cand
                break

    ext = os.path.splitext(candidate)[1].lower()
    if ext in ('.xlsx', '.xls'):
        df = pd.read_excel(candidate, dtype=str)
    else:
        df = pd.read_csv(candidate, sep='\t', encoding='latin-1', dtype=str)

    df = corrigir_textos_df(df)
    df = df.rename(columns={
        'Número do Processo': 'numero_processo', 'Nº de OS': 'numero_os',
        'Tipo de Serviço': 'tipo_servico', 'Número': 'numero',
        'Latitude': 'latitude_raw', 'Longitude': 'longitude_raw',
        'Data Hora Recebimento': 'data_recebimento',
        'Data Hora Atualização': 'data_atualizacao',
        'Priorização': 'priorizacao', 'status': 'status',
        'id': 'id', 'Recurso': 'recurso', 'Status': 'status',
        'Data Término': 'data_termino', 'Via': 'via',
        'De': 'de', 'Até': 'ate',
        'Extensão (m)': 'extensao_m', 'Área (m²)': 'area_m2',
        'Data Criação': 'data_criacao', 'Data Última Atualização': 'data_atualizacao',
        'Data Término': 'data_termino', 'Data TÃ©rmino': 'data_termino', 'Via': 'via',
        'De': 'de', 'Até': 'ate', 'AtÃ©': 'ate',
        'Logradouro Geosampa': 'logradouro_geosampa',
        'Subprefeitura': 'subprefeitura',
        'Extensão (m)': 'extensao_m', 'ExtensÃ£o (m)': 'extensao_m',
        'Área (m²)': 'area_m2', 'Ã\x81rea (mÂ²)': 'area_m2',
        'Revestimento': 'revestimento', 'Ativo?': 'ativo',
        'Data Criação': 'data_criacao', 'Data CriaÃ§Ã£o': 'data_criacao',
        'Data Última Atualização': 'data_atualizacao', 'Data Ãšltima AtualizaÃ§Ã£o': 'data_atualizacao',
        'Ponto Geometria': 'ponto_geometria',
    })

    df['data_criacao']  = parse_data(df.get('data_criacao'))
    df['data_termino']  = parse_data(df.get('data_termino'))
    df['extensao_m']    = pd.to_numeric(df.get('extensao_m'), errors='coerce')
    df['area_m2']       = pd.to_numeric(df.get('area_m2'),    errors='coerce')
    df['status']        = df.get('status', pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    df['subprefeitura'] = df.get('subprefeitura', pd.Series(dtype=str)).astype(str).str.strip().str.upper()

    # Usar logradouro_geosampa como rua principal (mais padronizado)
    df['rua_raw'] = df.get('logradouro_geosampa', df.get('via', '')).astype(str)
    df['rua_norm'] = df['rua_raw'].apply(normalizar_rua)

    # Extrair lat/lon do campo "Ponto Geometria" → "-23.487, -46.392"
    def parse_ponto(val):
        try:
            parts = str(val).split(',')
            return float(parts[0].strip()), float(parts[1].strip())
        except Exception:
            return None, None

    coords = df.get('ponto_geometria', pd.Series(dtype=str)).apply(parse_ponto)
    df['latitude']  = coords.apply(lambda x: x[0])
    df['longitude'] = coords.apply(lambda x: x[1])
    df['fonte'] = 'RECAPE'
    return df


def baixar_segmentos_geosampa(cache_path=GEOSAMPA_SEGMENTOS, page_size=10000) -> str | None:
    if gpd is None or requests is None:
        print("   ⚠️ geopandas/requests não estão instalados; recapes ficarão sem linhas.")
        return None
    if os.path.exists(cache_path):
        return cache_path

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    url = 'https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs'
    params_base = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'GetFeature',
        'typeNames': 'geoportal:segmento_logradouro',
        'outputFormat': 'application/json',
        'count': page_size,
    }
    features = []
    start = 0
    total = None
    while total is None or start < total:
        params = {**params_base, 'startIndex': start}
        resp = requests.get(url, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        total = data.get('totalFeatures') or data.get('numberMatched') or len(data.get('features', []))
        page = data.get('features', [])
        if not page:
            break
        features.extend(page)
        start += len(page)
        print(f"   ↳ GeoSampa: {min(start, total):,}/{total:,} segmentos baixados")

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump({
            'type': 'FeatureCollection',
            'crs': {'type': 'name', 'properties': {'name': 'EPSG:31983'}},
            'features': features,
        }, f)
    return cache_path


def _componentes_linha(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        geom = linemerge(geom)
        if isinstance(geom, LineString):
            return [geom]
        return list(geom.geoms)
    return [g for g in getattr(geom, 'geoms', []) if isinstance(g, LineString)]


def _unir_linhas(geoms):
    linhas = []
    for geom in geoms:
        linhas.extend(_componentes_linha(geom))
    if not linhas:
        return None
    if len(linhas) == 1:
        return linhas[0]
    return linemerge(linhas)


def _unir_linhas_locais(geoms, referencia=None, raio_m=2500, limite_sem_raio=40):
    linhas = []
    for geom in geoms or []:
        linhas.extend(_componentes_linha(geom))
    if not linhas:
        return None
    if referencia is not None and not referencia.is_empty:
        locais = [g for g in linhas if g.distance(referencia) <= raio_m]
        if not locais:
            locais = sorted(linhas, key=lambda g: g.distance(referencia))[:limite_sem_raio]
        linhas = locais
    return _unir_linhas(linhas)


def _linha_mais_representativa(geom, referencia=None):
    linhas = _componentes_linha(geom)
    if not linhas:
        return None
    if len(linhas) == 1:
        return linhas[0]
    if referencia is not None and not referencia.is_empty:
        return min(linhas, key=lambda g: g.distance(referencia))
    return max(linhas, key=lambda g: g.length)


def _ponto_intersecao(via_geom, outra_geom, referencia=None, tolerancia_m=60):
    inter = via_geom.intersection(outra_geom)
    candidatos = []
    if inter.geom_type == 'Point':
        candidatos = [inter]
    elif inter.geom_type == 'MultiPoint':
        candidatos = list(inter.geoms)
    elif inter.geom_type == 'GeometryCollection':
        candidatos = [g for g in inter.geoms if g.geom_type == 'Point']

    if not candidatos:
        p_via, _ = nearest_points(via_geom, outra_geom)
        if p_via.distance(outra_geom) <= tolerancia_m:
            candidatos = [p_via]

    if not candidatos:
        return None
    if referencia is not None and not referencia.is_empty:
        return min(candidatos, key=lambda p: p.distance(referencia))
    return candidatos[0]


def _cortar_linha_entre_pontos(via_geom, p_ini, p_fim, referencia=None, tolerancia_m=60):
    melhor = None
    melhor_score = float('inf')
    for linha in _componentes_linha(via_geom):
        d_ini = linha.distance(p_ini)
        d_fim = linha.distance(p_fim)
        if d_ini > tolerancia_m or d_fim > tolerancia_m:
            continue
        score = d_ini + d_fim + (linha.distance(referencia) if referencia is not None else 0)
        if score < melhor_score:
            melhor = linha
            melhor_score = score
    if melhor is None:
        return None

    ini = melhor.project(p_ini)
    fim = melhor.project(p_fim)
    if abs(ini - fim) < 1:
        return None
    if ini > fim:
        ini, fim = fim, ini
    return substring(melhor, ini, fim)


def _cortar_linha_por_aproximacao(via_geom, de_geom, ate_geom, referencia=None, tolerancia_m=80):
    melhor = None
    melhor_score = float('inf')
    for linha in _componentes_linha(via_geom):
        p_ini = nearest_points(linha, de_geom)[0]
        p_fim = nearest_points(linha, ate_geom)[0]
        d_ini = p_ini.distance(de_geom)
        d_fim = p_fim.distance(ate_geom)
        if d_ini > tolerancia_m or d_fim > tolerancia_m:
            continue
        score = d_ini + d_fim + (linha.distance(referencia) if referencia is not None else 0)
        if score < melhor_score:
            melhor = linha
            melhor_score = score

    if melhor is None:
        return None

    p_ini = nearest_points(melhor, de_geom)[0]
    p_fim = nearest_points(melhor, ate_geom)[0]
    ini = melhor.project(p_ini)
    fim = melhor.project(p_fim)
    if abs(ini - fim) < 1:
        return None
    if ini > fim:
        ini, fim = fim, ini
    return substring(melhor, ini, fim)


def enriquecer_recape_com_geosampa(df_recape: pd.DataFrame) -> pd.DataFrame:
    if gpd is None:
        return df_recape

    try:
        cache_path = baixar_segmentos_geosampa()
        if not cache_path:
            return df_recape
        ruas = gpd.read_file(cache_path)
        if ruas.crs is None:
            ruas = ruas.set_crs('EPSG:31983')
        ruas = ruas.to_crs('EPSG:31983')
    except Exception as exc:
        print(f"   ⚠️ Não foi possível carregar GeoSampa: {exc}")
        return df_recape

    ruas = ruas[ruas.geometry.notna() & ~ruas.geometry.is_empty].copy()
    ruas['rua_norm'] = ruas['nm_logradouro'].astype(str).apply(normalizar_rua)
    linhas_por_rua = ruas.groupby('rua_norm')['geometry'].apply(list).to_dict()
    nomes_ruas = list(linhas_por_rua.keys())
    to_utm = Transformer.from_crs('EPSG:4326', 'EPSG:31983', always_xy=True).transform
    to_ll = Transformer.from_crs('EPSG:31983', 'EPSG:4326', always_xy=True).transform
    geom_cache = {}
    path_cache = {}

    def geom_rua(nome, threshold=92):
        nome = normalizar_rua(nome)
        if not nome:
            return None
        if nome in geom_cache:
            return geom_cache[nome]
        if nome in linhas_por_rua:
            geom_cache[nome] = linhas_por_rua[nome]
            return geom_cache[nome]
        best = process.extractOne(nome, nomes_ruas, scorer=fuzz.token_sort_ratio)
        if best and best[1] >= threshold:
            geom_cache[nome] = linhas_por_rua[best[0]]
            return geom_cache[nome]
        geom_cache[nome] = None
        return None

    paths = []
    status_paths = []
    for _, row in df_recape.iterrows():
        via_nome = row.get('logradouro_geosampa') or row.get('via') or row.get('rua_raw')
        de_nome = row.get('de')
        ate_nome = row.get('ate')
        cache_key = (normalizar_rua(via_nome), normalizar_rua(de_nome), normalizar_rua(ate_nome))
        if cache_key in path_cache:
            path, status = path_cache[cache_key]
            paths.append(path)
            status_paths.append(status)
            continue

        via_linhas = geom_rua(via_nome)
        de_linhas = geom_rua(de_nome)
        ate_linhas = geom_rua(ate_nome)
        if via_linhas is None or de_linhas is None or ate_linhas is None:
            path_cache[cache_key] = (None, 'SEM_RUA_GEOM')
            paths.append(None)
            status_paths.append('SEM_RUA_GEOM')
            continue

        referencia = None
        if pd.notna(row.get('longitude')) and pd.notna(row.get('latitude')):
            referencia = shp_transform(to_utm, Point(float(row['longitude']), float(row['latitude'])))

        via_geom = _unir_linhas_locais(via_linhas, referencia)
        de_geom = _unir_linhas_locais(de_linhas, referencia)
        ate_geom = _unir_linhas_locais(ate_linhas, referencia)
        if via_geom is None or de_geom is None or ate_geom is None:
            if via_geom is not None:
                trecho = _linha_mais_representativa(via_geom, referencia)
                if trecho is not None and not trecho.is_empty:
                    trecho_ll = shp_transform(to_ll, trecho)
                    path = json.dumps([[round(x, 7), round(y, 7)] for x, y in trecho_ll.coords], ensure_ascii=False)
                    path_cache[cache_key] = (path, 'FALLBACK_VIA')
                    paths.append(path)
                    status_paths.append('FALLBACK_VIA')
                    continue
            path_cache[cache_key] = (None, 'SEM_RUA_GEOM')
            paths.append(None)
            status_paths.append('SEM_RUA_GEOM')
            continue

        p_ini = _ponto_intersecao(via_geom, de_geom, referencia)
        p_fim = _ponto_intersecao(via_geom, ate_geom, referencia)
        trecho = None
        if p_ini is not None and p_fim is not None:
            trecho = _cortar_linha_entre_pontos(via_geom, p_ini, p_fim, referencia)
        if trecho is None or trecho.is_empty:
            trecho = _cortar_linha_por_aproximacao(via_geom, de_geom, ate_geom, referencia)
        if trecho is None or trecho.is_empty:
            trecho = _linha_mais_representativa(via_geom, referencia)
        if trecho is None or trecho.is_empty:
            path_cache[cache_key] = (None, 'SEM_TRECHO')
            paths.append(None)
            status_paths.append('SEM_TRECHO')
            continue
        status_path = 'OK' if p_ini is not None and p_fim is not None else 'FALLBACK_VIA'

        trecho_ll = shp_transform(to_ll, trecho)
        path = json.dumps([[round(x, 7), round(y, 7)] for x, y in trecho_ll.coords], ensure_ascii=False)
        path_cache[cache_key] = (path, status_path)
        paths.append(path)
        status_paths.append(status_path)

    df_recape = df_recape.copy()
    df_recape['path'] = paths
    df_recape['status_path'] = status_paths
    total_linhas = df_recape['path'].notna().sum()
    print(f"   ✅ {total_linhas:,}/{len(df_recape):,} recapes com linha GeoSampa")
    return df_recape


# ─────────────────────────────────────────
# LEITURA — SGZ CONVIAS
# ─────────────────────────────────────────
def load_sgz_convias(filename='sgz_convias.csv') -> pd.DataFrame:
    path = os.path.join(RAW_DIR, filename)
    df = pd.read_csv(path, sep='|', encoding='utf-8', dtype=str)
    df = corrigir_textos_df(df)

    df = df.rename(columns={
        'Nº Processo': 'numero_processo', 'Nº de OS': 'numero_os',
        'Tipo de Serviço': 'tipo_servico', 'CEP': 'cep',
        'Rua': 'rua_raw', 'Número': 'numero',
        'X': 'coord_x_raw', 'Y': 'coord_y_raw',
        'Observação': 'observacao', 'VISTORIADOR': 'vistoriador',
        'Prefeitura Regional': 'prefeitura_regional',
        'Data Recebimento': 'data_recebimento',
        'Executora': 'executora', 'Permissionaria': 'permissionaria',
        'Priorização': 'priorizacao', 'Status': 'status',
    })

    df = df.rename(columns={
        'Número do Processo': 'numero_processo',
        'Nº de OS': 'numero_os',
        'Tipo de Serviço': 'tipo_servico',
        'Número': 'numero',
        'Latitude': 'latitude_raw',
        'Longitude': 'longitude_raw',
        'Data Hora Recebimento': 'data_recebimento',
        'Data Hora Atualização': 'data_atualizacao',
        'Priorização': 'priorizacao',
        'status': 'status',
    })

    def parse_coord(val, inteiros=2):
        try:
            s = str(val).strip()
            if '.' in s or ',' in s:
                return float(s.replace(',', '.'))
            s_neg = s.startswith('-')
            s_clean = s.replace('-', '')
            coord = float(s_clean) / (10 ** (len(s_clean) - inteiros))
            return -coord if s_neg else coord
        except Exception:
            return None

    df['latitude']  = df.get('latitude_raw', pd.Series(dtype=str)).apply(lambda x: parse_coord(x, 2))
    df['longitude'] = df.get('longitude_raw', pd.Series(dtype=str)).apply(lambda x: parse_coord(x, 2))
    df['data_recebimento']   = pd.to_datetime(df.get('data_recebimento'), dayfirst=True, errors='coerce')
    df['status']             = df.get('status', pd.Series(dtype=str)).astype(str).str.strip()
    df['prefeitura_regional']= df.get('prefeitura_regional', pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    df['rua_raw']            = df.get('rua_raw', pd.Series(dtype=str)).astype(str)
    df['rua_norm']           = df['rua_raw'].apply(normalizar_rua)
    df['cep']                = df.get('cep', pd.Series(dtype=str)).astype(str).apply(normalizar_cep)
    df['fonte'] = 'SGZ_CONVIAS'
    return df


# ─────────────────────────────────────────
# LEITURA — SGZ 156
# ─────────────────────────────────────────
def load_sgz_156(filename='sgz_156.csv') -> pd.DataFrame:
    path = os.path.join(RAW_DIR, filename)
    df = pd.read_csv(path, sep='|', encoding='utf-8', dtype=str)
    df = corrigir_textos_df(df)

    df = df.rename(columns={
        'NumeroOS': 'numero_os', 'TipoServico': 'tipo_servico',
        'NumeroOrigem': 'numero_origem', 'Justificativa': 'justificativa',
        'CEP': 'cep', 'Endereco': 'rua_raw', 'Numero': 'numero',
        'Latitude': 'latitude', 'Longitude': 'longitude',
        'PrefeituraRegional': 'prefeitura_regional',
        'DataHoraRecebimento': 'data_recebimento',
        'UnidadeNegocio': 'unidade_negocio', 'Polo': 'polo',
        'status': 'status',
    })

    df['latitude']  = df.get('latitude',  pd.Series(dtype=str)).astype(str).str.replace(',', '.').apply(pd.to_numeric, errors='coerce')
    df['longitude'] = df.get('longitude', pd.Series(dtype=str)).astype(str).str.replace(',', '.').apply(pd.to_numeric, errors='coerce')
    df['data_recebimento']    = pd.to_datetime(
        df.get('data_recebimento', pd.Series(dtype=str)).astype(str).str.strip(),
        format='%d/%m/%Y %H: %M: %S', errors='coerce'
    )
    df['status']              = df.get('status', pd.Series(dtype=str)).astype(str).str.strip()
    df['prefeitura_regional'] = df.get('prefeitura_regional', pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    df['rua_raw']             = df.get('rua_raw', pd.Series(dtype=str)).astype(str)
    df['rua_norm']            = df['rua_raw'].apply(normalizar_rua)
    df['cep']                 = df.get('cep', pd.Series(dtype=str)).astype(str).apply(normalizar_cep)
    df['fonte'] = 'SGZ_156'
    return df


# ─────────────────────────────────────────
# CRUZAMENTO NOTIFICAÇÕES × RECAPE
# Estratégia em cascata:
#   1. Nome de rua normalizado (fuzzy ≥ 85)
#   2. Reforço: mesmo CEP ou distância ≤ 0.3 km
# ─────────────────────────────────────────
def cruzar(df_notif: pd.DataFrame, df_recape: pd.DataFrame,
           fuzzy_threshold: int = 85, dist_threshold_km: float = 0.3,
           coord_only_threshold_km: float = 0.3,
           coord_regional_threshold_km: float = 1.0,
           coord_regional_long_threshold_km: float = 1.5) -> pd.DataFrame:

    recape_norms = df_recape['rua_norm'].fillna('').tolist()
    indice_espacial = montar_indice_espacial(df_recape)
    indices_por_rua = {}
    for idx, rua in enumerate(recape_norms):
        indices_por_rua.setdefault(rua, []).append(idx)
    melhores_por_rua = {}

    resultado = []
    for _, notif in df_notif.iterrows():
        rua_n  = notif.get('rua_norm', '')
        cep_n  = notif.get('cep', '')
        lat_n  = notif.get('latitude')
        lon_n  = notif.get('longitude')
        regional_n = notif.get('prefeitura_regional')

        match_recape = None
        metodo       = 'SEM_COBERTURA'
        score        = 0
        dist_recape  = None

        # ── PASSO 1: fuzzy match no nome da rua ──────────────────────────
        if rua_n:
            if rua_n not in melhores_por_rua:
                melhores_por_rua[rua_n] = process.extractOne(rua_n, recape_norms, scorer=fuzz.token_sort_ratio)
            best = melhores_por_rua[rua_n]
            if best and best[1] >= fuzzy_threshold:
                idx_candidatos = indices_por_rua.get(best[0], [])

                # ── PASSO 2: desempate por CEP ou coordenada ─────────────
                for idx in idx_candidatos:
                    rec = df_recape.iloc[idx]

                    # CEP bate?
                    if cep_n and str(rec.get('cep', '')) == cep_n:
                        match_recape = rec
                        metodo = 'NOME+CEP'
                        score  = best[1]
                        break

                    # Coordenada próxima?
                    lat_r, lon_r = rec.get('latitude'), rec.get('longitude')
                    if all(pd.notna(v) for v in [lat_n, lon_n, lat_r, lon_r]):
                        dist = haversine(lat_n, lon_n, lat_r, lon_r)
                        if dist <= dist_threshold_km:
                            match_recape = rec
                            metodo = 'NOME+COORD'
                            score  = best[1]
                            dist_recape = dist
                            break

                # se passou no fuzzy mas sem desempate — aceita só pelo nome
                if match_recape is None and best[1] >= 90:
                    match_recape = df_recape.iloc[idx_candidatos[0]]
                    metodo = 'NOME'
                    score  = best[1]

        if match_recape is None:
            idx_proximo, dist = recape_mais_proximo(
                lat_n, lon_n, indice_espacial, limite_km=coord_only_threshold_km
            )
            if idx_proximo is not None:
                match_recape = df_recape.loc[idx_proximo]
                metodo = 'COORD_PROXIMA'
                dist_recape = dist

        if match_recape is None:
            idx_proximo, dist = recape_mais_proximo(
                lat_n,
                lon_n,
                indice_espacial,
                limite_km=coord_regional_threshold_km,
                regional=regional_n,
                exigir_regional=True,
            )
            if idx_proximo is not None:
                match_recape = df_recape.loc[idx_proximo]
                metodo = 'COORD_REGIONAL'
                dist_recape = dist

        if match_recape is None:
            idx_proximo, dist = recape_mais_proximo(
                lat_n,
                lon_n,
                indice_espacial,
                limite_km=coord_regional_long_threshold_km,
                regional=regional_n,
                exigir_regional=True,
            )
            if idx_proximo is not None:
                match_recape = df_recape.loc[idx_proximo]
                metodo = 'COORD_REGIONAL_LONGA'
                dist_recape = dist

        linha = {
            # campos da notificação
            'numero_os'          : notif.get('numero_os'),
            'fonte_notif'        : notif.get('fonte'),
            'tipo_servico'       : notif.get('tipo_servico'),
            'rua_notif'          : notif.get('rua_raw'),
            'numero'             : notif.get('numero'),
            'cep'                : cep_n,
            'prefeitura_regional': notif.get('prefeitura_regional'),
            'data_recebimento'   : notif.get('data_recebimento'),
            'status_notif'       : notif.get('status'),
            'latitude'           : lat_n,
            'longitude'          : lon_n,

            # resultado do cruzamento
            'metodo_match'       : metodo,
            'score_fuzzy'        : score,
            'dist_recape_km'      : dist_recape,

            # campos do recape encontrado
            'id_recape'          : match_recape.get('id')          if match_recape is not None else None,
            'recurso_recape'     : match_recape.get('recurso')     if match_recape is not None else None,
            'status_recape'      : match_recape.get('status')      if match_recape is not None else None,
            'rua_recape'         : match_recape.get('rua_raw')     if match_recape is not None else None,
            'subprefeitura'      : match_recape.get('subprefeitura') if match_recape is not None else None,
            'data_termino_recape': match_recape.get('data_termino') if match_recape is not None else None,
            'extensao_m'         : match_recape.get('extensao_m')  if match_recape is not None else None,
            'area_m2'            : match_recape.get('area_m2')     if match_recape is not None else None,
        }

        # ── CLASSIFICAÇÃO OPERACIONAL ─────────────────────────────────────
        if metodo == 'SEM_COBERTURA':
            linha['situacao'] = '🔴 Sem cobertura'
        elif linha['status_recape'] == 'CONCLUIDO':
            linha['situacao'] = '✅ Recape concluído'
        elif linha['status_recape'] == 'PLANEJADO':
            linha['situacao'] = '⚠️ Recape planejado'
        else:
            linha['situacao'] = '🟡 Em andamento'

        resultado.append(linha)

    return pd.DataFrame(resultado)


# ─────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────
def run():
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    print("📂 Carregando recapeamentos...")
    recape = load_recape()
    print("🧭 Calculando trechos dos recapes via GeoSampa...")
    recape = enriquecer_recape_com_geosampa(recape)
    recape.to_csv(os.path.join(PROCESSED_DIR, 'recape_clean.csv'), index=False)
    print(f"   ✅ {len(recape)} registros | status: {recape['status'].value_counts().to_dict()}")

    print("📂 Carregando SGZ Convias...")
    convias = load_sgz_convias()
    print(f"   ✅ {len(convias)} notificações")

    print("📂 Carregando SGZ 156...")
    sgz_156 = load_sgz_156()
    print(f"   ✅ {len(sgz_156)} OSs")

    print("🔗 Unificando notificações...")
    colunas = ['numero_os','tipo_servico','cep','rua_raw','rua_norm','numero',
               'latitude','longitude','prefeitura_regional','data_recebimento','status','fonte']
    frames_notificacoes = []
    for origem in (convias, sgz_156):
        frame = origem.reindex(columns=colunas).dropna(axis=1, how='all')
        frames_notificacoes.append(frame)
    notificacoes = pd.concat(frames_notificacoes, ignore_index=True)
    notificacoes.to_csv(os.path.join(PROCESSED_DIR, 'notificacoes.csv'), index=False)
    print(f"   ✅ {len(notificacoes)} notificações unificadas")

    print("🔍 Cruzando notificações × recapeamentos...")
    cruzamento = cruzar(notificacoes, recape)
    cruzamento.to_csv(os.path.join(PROCESSED_DIR, 'cruzamento.csv'), index=False)

    total = len(cruzamento)
    com_cobertura = cruzamento[cruzamento['metodo_match'] != 'SEM_COBERTURA']
    print(f"   ✅ {len(com_cobertura)}/{total} notificações com cobertura de recape ({len(com_cobertura)/total*100:.1f}%)")
    print(f"\n✅ Pipeline concluído. Dados em data/processed/")
    return recape, notificacoes, cruzamento


if __name__ == '__main__':
    run()

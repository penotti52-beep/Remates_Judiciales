from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import re
import locale
import base64  # Para mostrar el logo centrado

# --- NUEVO: fallback + diagnóstico ---
from pathlib import Path
import socket
import traceback


# ================= CONFIG APP =================
st.set_page_config(
    layout="wide",
    page_title="Remates Judiciales Bolivia",
    page_icon="🧑‍⚖️"
)

# ====== ESTILOS CSS (tabs + métricas + header + bandera) ======
st.markdown("""
    <style>
    .block-container {
        padding-top: 0.6rem;
    }

    /* TABS en modo oscuro */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 8px;
        background-color: #111827;
        color: #ffffff !important;
        border: 1px solid #374151;
    }
    .stTabs [aria-selected="true"] {
        background-color: #1f2937 !important;
        border: 1px solid #fbbf24 !important;
        color: #ffffff !important;
    }

    /* Métricas KPI (tarjetitas) */
    [data-testid="stMetric"] {
        background-color: #020617;
        padding: 0.75rem 1rem;
        border-radius: 0.75rem;
        border: 1px solid #1f2937;
        box-shadow: 0 10px 25px rgba(0,0,0,0.45);
    }
    [data-testid="stMetricLabel"] {
        text-transform: uppercase;
        font-size: 0.8rem;
        letter-spacing: 0.08em;
        color: #9ca3af;
    }
    [data-testid="stMetricValue"] {
        font-size: 2.0rem;
        font-weight: 700;
        color: #f9fafb;
    }

    /* Colores distintos para cada KPI usando envoltorios */
    .kpi-card-total [data-testid="stMetric"] {
        background: radial-gradient(circle at top left, #22c55e55, #020617);
        border-color: #16a34a;
    }
    .kpi-card-0 [data-testid="stMetric"] {
        background: radial-gradient(circle at top left, #0ea5e955, #020617);
        border-color: #0284c7;
    }
    .kpi-card-20 [data-testid="stMetric"] {
        background: radial-gradient(circle at top left, #f9731655, #020617);
        border-color: #ea580c;
    }
    .kpi-card-urg [data-testid="stMetric"] {
        background: radial-gradient(circle at top left, #ef444455, #020617);
        border-color: #b91c1c;
    }

    /* HEADER: logo + título centrados */
    .app-header {
        text-align: center;
        margin-top: 0.2rem;
        margin-bottom: 1.0rem;
    }
    .app-header img {
        display: block;
        margin-left: auto;
        margin-right: auto;
        margin-top: 30px;
        margin-bottom: 10px;
    }
    .app-header-title {
        font-size: 3rem;
        font-weight: 800;
        margin-top: 0.3rem;
        margin-bottom: 0.2rem;
    }

    /* Bandera Bolivia hecha con spans */
    .bandera-bo {
        display: inline-flex;
        margin-left: 0.5rem;
        vertical-align: middle;
    }
    .franja {
        width: 12px;
        height: 12px;
        margin-left: 2px;
        border-radius: 2px;
    }
    .franja.rojo    { background-color: #d01c1f; }
    .franja.amarillo{ background-color: #ffd600; }
    .franja.verde   { background-color: #007a33; }

    </style>
""", unsafe_allow_html=True)

# ----- CONFIGURACIÓN LOCALIDAD -----
try:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
except Exception:
    pass


# ================= SCRAPING (MEJORADO PARA STREAMLIT CLOUD) =================
url = "https://thor.organojudicial.gob.bo/"
CACHE_FILE = Path("/tmp/thor_cache.html")  # Streamlit Cloud permite escribir en /tmp


@st.cache_data(ttl=600, show_spinner=False)  # cache 10 min (evita pedir a cada rerun)
def descargar_html_online(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
        ),
        "Accept-Language": "es-BO,es;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "close",
    }

    s = requests.Session()
    retries = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))

    r = s.get(url, headers=headers, timeout=(25, 90))  # (connect, read)
    r.raise_for_status()
    return r.text


def obtener_html_con_fallback(url: str) -> str:
    try:
        html = descargar_html_online(url)

        # Guardar caché local (último HTML bueno)
        CACHE_FILE.write_text(html, encoding="utf-8", errors="ignore")
        st.session_state["thor_cache_ts"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return html

    except Exception as e:
        # Mostrar diagnóstico (para ver el error real en Cloud)
        with st.expander("🧪 Diagnóstico (solo si falla)"):
            try:
                st.write("DNS:", socket.gethostbyname("thor.organojudicial.gob.bo"))
            except Exception as dns_e:
                st.write("DNS error:", repr(dns_e))
            st.write("Excepción:", repr(e))
            st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))

        # Fallback a caché si existe
        if CACHE_FILE.exists():
            ts = st.session_state.get("thor_cache_ts", "sin fecha")
            st.warning(f"⚠️ THOR no respondió. Usando caché local (última descarga: {ts}).")
            return CACHE_FILE.read_text(encoding="utf-8", errors="ignore")

        # Si no hay caché, detenemos (no hay con qué continuar)
        st.error("⚠️ No se pudo conectar con 'thor.organojudicial.gob.bo' desde Streamlit Cloud. "
                 "Puede ser lentitud del sitio o bloqueo por IP/GeoIP.")
        if st.button("🔄 Reintentar conexión"):
            descargar_html_online.clear()
            try:
                CACHE_FILE.unlink(missing_ok=True)
            except Exception:
                pass
            st.rerun()
        st.stop()


html_content = obtener_html_con_fallback(url)

soup = BeautifulSoup(html_content, 'html.parser')
remates = soup.find_all('li', class_='clearfix')


# ================= PARSEO =================
tipos_inmuebles = []
valores = []
fechas_publicacion = []
juzgados = []
ubicaciones = []
numeros_proceso = []
rebaja = []
iconos = []
descripciones = []

patron = r"(\d{1,2}) de (\w+) de (\d{4})"


def extraer_fecha(fecha_str: str):
    match = re.search(patron, fecha_str)
    if match:
        dia, mes, anio = match.groups()
        try:
            fecha_formateada = datetime.strptime(
                f"{dia} {mes} {anio}", "%d %B %Y"
            ).strftime("%d/%m/%Y")
            return fecha_formateada
        except Exception:
            return None
    return None


def limpiar_descripcion(descripcion: str):
    return descripcion.replace('Descripción:Tipo Inmueble ', '')


def limpiar_valor(valor: str):
    valor_limpio = valor.replace('Valor Original: ', '').split('Empoce:')[0].strip()
    return valor_limpio


def limpiar_juzgado(juzgado: str):
    juzgado_limpio = juzgado.replace('Juzgado N° ', '').replace('Juzgado Público', '').strip()
    return juzgado_limpio


def extraer_ciudad(ubicacion: str):
    """Toma la última parte de la ubicación como ciudad (después de '-' o ',')."""
    if not isinstance(ubicacion, str):
        return None
    parte = ubicacion.split('-')[-1]
    parte = parte.split(',')[-1]
    return parte.strip()


for remate in remates:
    try:
        tipo_inmueble = remate.find('strong', class_='primary-font').text.strip()
    except Exception:
        tipo_inmueble = "No disponible"

    try:
        valor = remate.find('i', class_='fa-money').text.strip()
    except Exception:
        valor = "No disponible"

    try:
        fecha_publicacion = remate.find('small', class_='pull-right').text.strip()
    except Exception:
        fecha_publicacion = "No disponible"

    try:
        juzgado = remate.find('i', class_='fa-university').text.strip()
    except Exception:
        juzgado = "No disponible"

    try:
        ubicacion = remate.find('i', class_='fa-map-marker').text.strip()
    except Exception:
        ubicacion = "No disponible"

    # Número de proceso (seguro)
    try:
        nodo_proc = remate.find('i', class_='fa-server')
        numero_proceso = nodo_proc.text.split('N° Proceso: ')[-1].strip() if nodo_proc else "No disponible"
    except Exception:
        numero_proceso = "No disponible"

    # Descripción (con tu lógica actual)
    descripcion = remate.find('i', class_='fa-server')
    descripcion_texto = descripcion.text.strip() if descripcion else "Descripción no disponible"
    descripcion_limpia = limpiar_descripcion(descripcion_texto)

    rebaja_value = '0%'
    if isinstance(valor, str) and 'Rebaja' in valor:
        try:
            rebaja_value = valor.split('Rebaja: ')[-1].split('%')[0] + '%'
        except Exception:
            rebaja_value = '0%'

    fecha_str = extraer_fecha(fecha_publicacion)

    # Cálculo de días para el color
    try:
        fecha_remate = datetime.strptime(fecha_str, "%d/%m/%Y")
        diff = fecha_remate - datetime.now()
        days_left = diff.days

        if days_left <= 2:
            iconos.append('🟥')
        elif 3 <= days_left <= 7:
            iconos.append('🟨')
        elif 8 <= days_left <= 14:
            iconos.append('🟩')
        elif days_left > 14:
            iconos.append('🟦')
        else:
            iconos.append('🟥')
    except Exception:
        iconos.append('🟦')

    valor_limpio = limpiar_valor(valor) if isinstance(valor, str) else "No disponible"
    juzgado_limpio = limpiar_juzgado(juzgado) if isinstance(juzgado, str) else "No disponible"

    tipos_inmuebles.append(tipo_inmueble)
    valores.append(valor_limpio)
    fechas_publicacion.append(fecha_publicacion)
    juzgados.append(juzgado_limpio)
    ubicaciones.append(ubicacion)
    numeros_proceso.append(numero_proceso)
    rebaja.append(rebaja_value)
    descripciones.append(descripcion_limpia)


# --------- FAVORITOS en Session State ---------
if 'favoritos' not in st.session_state:
    st.session_state['favoritos'] = []


# ================= DATAFRAME BASE =================
data = {
    '': iconos,
    'Tipo de Inmueble': tipos_inmuebles,
    'Descripción': descripciones,
    'Valor Original del Inmueble': valores,
    'Fecha de Remate del Inmueble': fechas_publicacion,
    'Juzgado': juzgados,
    'Ubicación': ubicaciones,
    'Número de Proceso': numeros_proceso,
    'Rebaja': rebaja
}
df = pd.DataFrame(data)

df['FechaFormateada'] = df['Fecha de Remate del Inmueble'].apply(extraer_fecha)
df['FechaDate'] = pd.to_datetime(df['FechaFormateada'], format="%d/%m/%Y", errors="coerce")
df['Ciudad'] = df['Ubicación'].apply(extraer_ciudad)


# ================= SIDEBAR: LEYENDA + FILTROS =================
st.sidebar.markdown("### Leyenda de colores")

st.sidebar.markdown(
    "🟥 **Rojo**<br/>"
    "Menor o igual a 2 días para el remate.",
    unsafe_allow_html=True
)
st.sidebar.markdown(
    "🟨 **Amarillo**<br/>"
    "Menor o igual a 1 semana para el remate.",
    unsafe_allow_html=True
)
st.sidebar.markdown(
    "🟩 **Verde**<br/>"
    "Menor o igual a 2 semanas para el remate.",
    unsafe_allow_html=True
)
st.sidebar.markdown(
    "🟦 **Azul**<br/>"
    "Más de 2 semanas para el remate.",
    unsafe_allow_html=True
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Filtros")

# Filtro por ciudad (una sola)
ciudades_unicas = sorted(df['Ciudad'].dropna().unique())
opciones_ciudad = ["Todas las ciudades"] + ciudades_unicas

default_ciudad = "Chuquisaca"
if default_ciudad in opciones_ciudad:
    default_index = opciones_ciudad.index(default_ciudad)
else:
    default_index = 0  # fallback: "Todas las ciudades"

ciudad_sel = st.sidebar.selectbox(
    "Ciudad",
    opciones_ciudad,
    index=default_index
)

# Filtro texto
texto_busqueda = st.sidebar.text_input("Buscar (descripción o N° proceso)")

# Filtro rango fechas
min_fecha = df['FechaDate'].min()
max_fecha = df['FechaDate'].max()
fecha_ini, fecha_fin = None, None

if pd.notnull(min_fecha) and pd.notnull(max_fecha):
    st.sidebar.markdown("**📅 Rango de fecha de remate**")
    rango_fechas = st.sidebar.date_input(
        "Rango de fecha de remate",
        (min_fecha.date(), max_fecha.date()),
        label_visibility="collapsed",
    )
    if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
        fecha_ini, fecha_fin = rango_fechas
    else:
        fecha_ini, fecha_fin = min_fecha.date(), max_fecha.date()

# Aplicar filtros básicos (tipo inmueble y ciudad)
df_filtered = df[df['Tipo de Inmueble'].str.contains('INMUEBLE', case=False, na=False)]

if ciudad_sel != "Todas las ciudades":
    df_filtered = df_filtered[df_filtered['Ciudad'] == ciudad_sel]

if texto_busqueda:
    mask_desc = df_filtered['Descripción'].str.contains(texto_busqueda, case=False, na=False)
    mask_proc = df_filtered['Número de Proceso'].str.contains(texto_busqueda, case=False, na=False)
    df_filtered = df_filtered[mask_desc | mask_proc]

if fecha_ini and fecha_fin:
    mask_fecha = (df_filtered['FechaDate'] >= pd.to_datetime(fecha_ini)) & \
                 (df_filtered['FechaDate'] <= pd.to_datetime(fecha_fin))
    df_filtered = df_filtered[mask_fecha]


# ================= CABECERA: LOGO + TÍTULO =================
def header_con_logo_y_titulo():
    try:
        with open("logo2.png", "rb") as f:
            img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        st.markdown(
            f"""
            <div class="app-header">
                <img src="data:image/png;base64,{img_b64}" width="220" alt="Logo">
                <div class="app-header-title">
                    Remates Judiciales Bolivia
                    <span class="bandera-bo">
                        <span class="franja rojo"></span>
                        <span class="franja amarillo"></span>
                        <span class="franja verde"></span>
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    except Exception:
        st.markdown(
            """
            <div class="app-header">
                <div class="app-header-title">
                    Remates Judiciales Bolivia
                    <span class="bandera-bo">
                        <span class="franja rojo"></span>
                        <span class="franja amarillo"></span>
                        <span class="franja verde"></span>
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )


header_con_logo_y_titulo()


# ================= KPIs =================
col_k1, col_k2, col_k3, col_k4 = st.columns(4)
total = len(df_filtered)
total_0 = len(df_filtered[df_filtered["Rebaja"] == "0%"])
total_20 = len(df_filtered[df_filtered["Rebaja"] == "20%"])
total_urgentes = len(df_filtered[df_filtered[''].isin(['🟥', '🟨'])])

with col_k1:
    st.markdown('<div class="kpi-card-total">', unsafe_allow_html=True)
    st.metric("Total remates", total)
    st.markdown('</div>', unsafe_allow_html=True)

with col_k2:
    st.markdown('<div class="kpi-card-0">', unsafe_allow_html=True)
    st.metric("0% de rebaja", total_0)
    st.markdown('</div>', unsafe_allow_html=True)

with col_k3:
    st.markdown('<div class="kpi-card-20">', unsafe_allow_html=True)
    st.metric("20% de rebaja", total_20)
    st.markdown('</div>', unsafe_allow_html=True)

with col_k4:
    st.markdown('<div class="kpi-card-urg">', unsafe_allow_html=True)
    st.metric("Remates urgentes", total_urgentes)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")


# ================= FUNCIÓN VISTA DETALLADA =================
def mostrar_detalle(df_detalle: pd.DataFrame, titulo: str):
    """Muestra una lista de expanders con enumeración 1,2,3..."""
    st.markdown(f"### {titulo}")

    if df_detalle.empty:
        st.info("No hay remates para mostrar en detalle.")
        return

    df_detalle = df_detalle.sort_values('FechaDate')

    for i, (idx, row) in enumerate(df_detalle.iterrows(), start=1):
        fecha_txt = row.get('FechaFormateada') or row.get('Fecha de Remate del Inmueble', '')
        titulo_exp = (
            f"{i}. {row.get('', '')} {fecha_txt} | {row.get('Tipo de Inmueble', '')}"
        )
        with st.expander(titulo_exp):
            st.write(f"**N° en listado:** {idx + 1}")
            st.write(f"**Descripción:** {row.get('Descripción', 'Sin descripción')}")
            st.write(f"**Valor original:** {row.get('Valor Original del Inmueble', 'No registrado')}")
            st.write(f"**Rebaja:** {row.get('Rebaja', 'No especificada')}")
            st.write(f"**Fecha de remate:** {fecha_txt}")
            st.write(f"**Número de Proceso:** {row.get('Número de Proceso', 'No registrado')}")
            st.write(f"**Juzgado:** {row.get('Juzgado', 'No registrado')}")
            st.write(f"**Ciudad:** {row.get('Ciudad', 'Sin ciudad')}")
            st.write(f"**Ubicación completa:** {row.get('Ubicación', 'Sin ubicación')}")


# ================= REMATES MÁS URGENTES =================
st.markdown("### Remates más urgentes (Rojo y Amarillo) 🟥🟨")

urgentes = df_filtered[df_filtered[''].isin(['🟥', '🟨'])].copy()
urgentes = urgentes.sort_values('FechaDate').head(30)

if urgentes.empty:
    st.info("No hay remates urgentes (rojo o amarillo) con los filtros actuales.")
else:
    mostrar_detalle(urgentes, "Detalle de remates más urgentes")

st.markdown("---")


# ================= FUNCIÓN PARA TABLAS CON FAVORITOS =================
def marcar_favorito(df_visible: pd.DataFrame, tabla_key: str):
    """
    Muestra una tabla con:
      - Columna N° al inicio (posición del aviso = index + 1)
      - Columna Favorito después de N°
      - Número de Proceso a la derecha de Fecha de Remate del Inmueble
      - Solo la columna Favorito es editable.
    """
    df_visible = df_visible.copy()

    # N° = índice + 1 (posición en el listado filtrado)
    df_visible.insert(0, "N°", range(1, len(df_visible) + 1))

    # Estado de favoritos desde session_state
    favoritos = st.session_state.get('favoritos', [])
    df_visible['Favorito'] = df_visible.index.isin(favoritos)

    # Mover Favorito a la segunda columna
    cols = df_visible.columns.tolist()
    cols.remove('Favorito')
    cols.insert(1, 'Favorito')
    df_visible = df_visible[cols]

    # Mover Número de Proceso justo después de Fecha de Remate del Inmueble
    if 'Número de Proceso' in df_visible.columns and 'Fecha de Remate del Inmueble' in df_visible.columns:
        cols = df_visible.columns.tolist()
        cols.remove('Número de Proceso')
        idx_fecha = cols.index('Fecha de Remate del Inmueble')
        cols.insert(idx_fecha + 1, 'Número de Proceso')
        df_visible = df_visible[cols]

    # Combinar ícono de color con fecha para mostrar
    display_df = df_visible.assign(
        **{
            'Fecha de Remate del Inmueble': df_visible[''].fillna('') +
                                           ' ' +
                                           df_visible['Fecha de Remate del Inmueble']
        }
    ).drop(columns=['', 'FechaDate', 'FechaFormateada', 'Ciudad'], errors='ignore')

    disabled_cols = [c for c in display_df.columns if c != 'Favorito']

    edited = st.data_editor(
        display_df,
        key=tabla_key,
        column_config={
            "Favorito": st.column_config.CheckboxColumn(
                "Favorito",
                help="Marcar como favorito"
            )
        },
        use_container_width=True,
        hide_index=True,
        disabled=disabled_cols,
    )

    # Actualizar favoritos en session_state según la vista editada
    favoritos_en_tabla = edited[edited['Favorito']].index.tolist()
    fav_set = set(st.session_state['favoritos'])
    fav_set.update(favoritos_en_tabla)

    for idx in df_visible.index:
        if idx not in favoritos_en_tabla and idx in fav_set:
            fav_set.remove(idx)

    st.session_state['favoritos'] = list(fav_set)

    return edited


# ================= LISTADO DE REMATES =================
st.subheader("Listado de remates")
modo_detalle = st.checkbox("🔍 Activar vista detallada (expanders por remate)")

tab0, tab20, tabAll = st.tabs(["0% de Rebaja", "20% de Rebaja", "Todos los remates"])

# ----- TAB 0% -----
with tab0:
    st.write("Remates sin rebaja registrada.")

    df_0_base = df_filtered[df_filtered['Rebaja'] == '0%']
    df_0_tabla = df_0_base

    if df_0_tabla.empty:
        st.info("No hay remates con 0% de rebaja con los filtros actuales.")
    else:
        marcar_favorito(df_0_tabla, 'tabla0')

        if modo_detalle:
            mostrar_detalle(df_0_base, "Vista detallada de remates con 0% de rebaja")

# ----- TAB 20% -----
with tab20:
    st.write("Remates con rebaja del 20%.")

    df_20_base = df_filtered[df_filtered['Rebaja'] == '20%']
    df_20_tabla = df_20_base

    if df_20_tabla.empty:
        st.info("No hay remates con 20% de rebaja con los filtros actuales.")
    else:
        marcar_favorito(df_20_tabla, 'tabla20')

        if modo_detalle:
            mostrar_detalle(df_20_base, "Vista detallada de remates con 20% de rebaja")

# ----- TAB TODOS -----
with tabAll:
    st.write("Todos los remates que cumplen los filtros seleccionados.")

    if df_filtered.empty:
        st.info("No hay remates con los filtros actuales.")
    else:
        marcar_favorito(df_filtered, 'tablaAll')

        if modo_detalle:
            mostrar_detalle(df_filtered, "Vista detallada de todos los remates filtrados")


# ================= SECCIÓN FAVORITOS =================
st.markdown("---")
favoritos_actualizados = st.session_state['favoritos']

if favoritos_actualizados:
    st.subheader("Remates fijados / favoritos")

    # Tomamos solo los favoritos desde el df filtrado actual
    favoritos_view = df_filtered.loc[df_filtered.index.intersection(favoritos_actualizados)].copy()

    if not favoritos_view.empty:
        # Quitamos columnas internas que no deben verse
        favoritos_view = favoritos_view.drop(
            columns=['FechaDate', 'FechaFormateada', 'Ciudad'],
            errors='ignore'
        )

        # Orden opcional: por índice original, para que sea estable
        favoritos_view = favoritos_view.sort_index()

        # Columna N° enumerada 1, 2, 3, ...
        favoritos_view.insert(0, "N°", range(1, len(favoritos_view) + 1))

        # Reordenar columnas en favoritos: proceso a la derecha de fecha
        cols = favoritos_view.columns.tolist()
        if "Número de Proceso" in cols and "Fecha de Remate del Inmueble" in cols:
            cols.remove("Número de Proceso")
            idx_fecha = cols.index("Fecha de Remate del Inmueble")
            cols.insert(idx_fecha + 1, "Número de Proceso")
            favoritos_view = favoritos_view[cols]

        st.dataframe(
            favoritos_view,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Los favoritos actuales no coinciden con los filtros seleccionados.")
else:
    st.info("No tienes favoritos seleccionados todavía.")

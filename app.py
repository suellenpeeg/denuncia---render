import streamlit as st
import pandas as pd
import os
import psycopg2
from datetime import datetime
import hashlib
from fpdf import FPDF

# =========================================
# CONFIGURAÇÃO DA PÁGINA
# =========================================
st.set_page_config(page_title="URB Fiscalização - Denúncias", layout="wide")

# =========================================
# CONFIGURAÇÃO DO BANCO DE DADOS
# =========================================
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if not DATABASE_URL:
        st.error("Erro: A variável de ambiente DATABASE_URL não foi encontrada.")
        st.stop()
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        st.error(f"Erro ao conectar ao banco de dados: {e}")
        st.stop()

# =========================================
# LISTAS DE OPÇÕES E CONSTANTES
# =========================================
OPCOES_BAIRROS = [
    "AGAMENON MAGALHÃES","ALTO DO MOURA","CAIUCÁ","CEDRO","CENTENÁRIO","CIDADE ALTA","CIDADE JARDIM",
    "DEPUTADO JOSÉ ANTÔNIO LIBERATO","DISTRITO INDUSTRIAL","DIVINÓPOLIS","INDIANÓPOLIS","JARDIM BOA VISTA",
    "JARDIM PANORAMA","JOÃO MOTA","JOSÉ CARLOS DE OLIVEIRA","KENNEDY","LUIZ GONZAGA","MANOEL BEZERRA LOPES",
    "MARIA AUXILIADORA","MAURÍCIO DE NASSAU","MORRO BOM JESUS","NINA LIBERATO","NOSSA SENHORA DAS DORES",
    "NOSSA SENHORA DAS GRAÇAS","NOVA CARUARU","PETRÓPOLIS","PINHEIRÓPOLIS","RENDEIRAS","RIACHÃO","SALGADO",
    "SANTA CLARA","SANTA ROSA","SÃO FRANCISCO","SÃO JOÃO DA ESCÓCIA","SÃO JOSÉ","SERRAS DO VALE",
    "SEVERINO AFONSO","UNIVERSITÁRIO","VASSOURAL","VILA PADRE INÁCIO","VERDE","VILA ANDORINHA","XIQUE-XIQUE"
]

OPCOES_ORIGEM = ['Pessoalmente','Telefone','Whatsapp','Ministério Publico','Administração','Ouvidoria','Disk Denuncia']
OPCOES_TIPO = ['Urbana','Ambiental','Urbana e Ambiental']
OPCOES_ZONA = ['NORTE','SUL','LESTE','OESTE','CENTRO','1° DISTRITO','2° DISTRITO','3° DISTRITO','4° DISTRITO','Zona rural']
OPCOES_FISCAIS = ['EDVALDO WILSON BEZERRA DA SILVA - 000.323','PATRICIA MIRELLY BEZERRA CAMPOS - 000.332','RAIANY NAYARA DE LIMA - 000.362','SUELLEN BEZERRA DO NASCIMENTO - 000.417']
OPCOES_STATUS = ['Pendente', 'Em monitoramento', 'Concluída']

# =========================================
# FUNÇÕES AUXILIARES
# =========================================
def safe_index(lista, valor, padrao=0):
    try:
        return lista.index(valor)
    except ValueError:
        return padrao

def hash_password(password: str):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

# =========================================
# SCHEMA E MIGRATION
# =========================================
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Tabela de Usuários
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            full_name TEXT,
            is_admin BOOLEAN DEFAULT FALSE
        );
    ''')
    
    # Criar admin padrão
    cur.execute("SELECT * FROM users WHERE username = %s", ('admin',))
    if not cur.fetchone():
        pass_hash = hash_password('fisc2023')
        cur.execute("INSERT INTO users (username, password, full_name, is_admin) VALUES (%s, %s, %s, %s)", 
                    ('admin', pass_hash, 'Administrador', True))

    # 2. Tabela de Denúncias
    cur.execute('''
        CREATE TABLE IF NOT EXISTS denuncias (
            id SERIAL PRIMARY KEY,
            external_id TEXT UNIQUE,
            created_at TIMESTAMP,
            origem TEXT,
            tipo TEXT,
            rua TEXT,
            numero TEXT,
            bairro TEXT,
            zona TEXT,
            latitude TEXT,
            longitude TEXT,
            descricao TEXT,
            quem_recebeu TEXT,
            status TEXT DEFAULT 'Pendente'
        );
    ''')

    # 3. Atualização de Schema (Adicionar coluna acao_noturna)
    try:
        cur.execute("ALTER TABLE denuncias ADD COLUMN IF NOT EXISTS acao_noturna BOOLEAN DEFAULT FALSE;")
    except Exception:
        conn.rollback() 
        # Ignora se der erro, assume que já existe ou algo assim

    # 4. Tabela de Reincidências
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reincidencias (
            id SERIAL PRIMARY KEY,
            denuncia_id INTEGER REFERENCES denuncias(id) ON DELETE CASCADE,
            created_at TIMESTAMP,
            fonte TEXT,
            descricao TEXT
        );
    ''')

    conn.commit()
    cur.close()
    conn.close()

# =========================================
# USER MANAGEMENT
# =========================================
def add_user(username, password, full_name=""):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        pass_hash = hash_password(password)
        cur.execute("INSERT INTO users (username, password, full_name, is_admin) VALUES (%s, %s, %s, %s)", 
                    (username, pass_hash, full_name, False))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def verify_user(username, password):
    conn = get_db_connection()
    cur = conn.cursor()
    pass_hash = hash_password(password)
    cur.execute("SELECT username, full_name, is_admin FROM users WHERE username = %s AND password = %s", 
                (username, pass_hash))
    user_data = cur.fetchone()
    cur.close()
    conn.close()
    if user_data:
        return {'username': user_data[0], 'full_name': user_data[1], 'is_admin': user_data[2]}
    return None

def get_all_users():
    conn = get_db_connection()
    df = pd.read_sql("SELECT username, full_name, is_admin FROM users", conn)
    conn.close()
    return df

# =========================================
# LÓGICA DE DENÚNCIAS
# =========================================
def generate_external_id():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT COALESCE(MAX(id), 0) FROM denuncias')
    max_id = cur.fetchone()[0]
    conn.close()
    next_id = (max_id + 1)
    year = datetime.now().year
    return f"{next_id:04d}/{year}"

def insert_denuncia(record):
    conn = get_db_connection()
    cur = conn.cursor()
    # Forçar booleano puro do Python para evitar erro de tipo
    noturna_bool = bool(record.get('acao_noturna', False))
    
    cur.execute('''
        INSERT INTO denuncias (external_id, created_at, origem, tipo, rua, numero, bairro, zona, latitude, longitude, descricao, quem_recebeu, status, acao_noturna) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        record['external_id'], record['created_at'], record['origem'], record['tipo'], 
        record['rua'], record['numero'], record['bairro'], record['zona'], 
        record['latitude'], record['longitude'], record['descricao'], 
        record['quem_recebeu'], record.get('status','Pendente'), noturna_bool
    ))
    conn.commit()
    cur.close()
    conn.close()

def insert_reincidencia(denuncia_id, fonte, descricao):
    conn = get_db_connection()
    cur = conn.cursor()
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # cast int() aqui para garantir
    cur.execute('''
        INSERT INTO reincidencias (denuncia_id, created_at, fonte, descricao)
        VALUES (%s, %s, %s, %s)
    ''', (int(denuncia_id), created_at, fonte, descricao))
    conn.commit()
    cur.close()
    conn.close()

def fetch_reincidencias(denuncia_id):
    conn = get_db_connection()
    cur = conn.cursor()
    # cast int() aqui para garantir
    cur.execute("SELECT * FROM reincidencias WHERE denuncia_id = %s ORDER BY created_at ASC", (int(denuncia_id),))
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(zip(cols, row)) for row in rows]

def fetch_all_denuncias():
    conn = get_db_connection()
    query = '''
        SELECT d.*, 
        (SELECT COUNT(*) FROM reincidencias r WHERE r.denuncia_id = d.id) as num_reincidencias
        FROM denuncias d 
        ORDER BY d.id DESC
    '''
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def fetch_denuncia_by_id(id_):
    conn = get_db_connection()
    cur = conn.cursor()
    # cast int()
    cur.execute('SELECT * FROM denuncias WHERE id = %s', (int(id_),))
    if cur.description:
        colnames = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        if row:
            record = dict(zip(colnames, row))
            cur.close()
            conn.close()
            return record
    cur.close()
    conn.close()
    return None

def update_denuncia_status(id_, status):
    conn = get_db_connection()
    cur = conn.cursor()
    # cast int()
    cur.execute('UPDATE denuncias SET status = %s WHERE id = %s', (status, int(id_)))
    conn.commit()
    cur.close()
    conn.close()

def delete_denuncia(id_):
    conn = get_db_connection()
    cur = conn.cursor()
    # cast int()
    cur.execute('DELETE FROM denuncias WHERE id = %s', (int(id_),))
    conn.commit()
    cur.close()
    conn.close()

def update_denuncia_full(id_, row):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Garante tipos Python nativos
    noturna_bool = bool(row['acao_noturna'])
    
    cur.execute('''UPDATE denuncias SET origem=%s, tipo=%s, rua=%s, numero=%s, bairro=%s, zona=%s, latitude=%s, longitude=%s, descricao=%s, quem_recebeu=%s, status=%s, acao_noturna=%s WHERE id=%s''', (
        row['origem'], row['tipo'], row['rua'], row['numero'], row['bairro'], row['zona'], 
        row['latitude'], row['longitude'], row['descricao'], 
        row['quem_recebeu'], row['status'], noturna_bool, int(id_)
    ))
    conn.commit()
    cur.close()
    conn.close()

# =========================================
# GERAÇÃO DE PDF (CORRIGIDA)
# =========================================
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'URB Fiscalização - Ordem de Serviço', 0, 1, 'C')

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Página %s' % self.page_no(), 0, 0, 'C')

def create_pdf_from_record(record, reincidencias=None):
    pdf = PDF()
    
    # --- PÁGINA 1: Denúncia Principal ---
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Header Info
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"Ordem de Serviço Nº {record['external_id']}", ln=True, align='L')
    pdf.ln(2)

    pdf.set_font("Arial", "", 11)
    
    noturna_txt = "SIM" if record.get('acao_noturna') else "NÃO"

    # Detalhes
    pdf.multi_cell(0, 6, f"""
Data/Hora Registro: {record['created_at']}
Origem: {record['origem']}
Tipo: {record['tipo']}
Ação Noturna: {noturna_txt}
Endereço: {record['rua']}, {record['numero']}
Bairro/Zona: {record['bairro']} / {record['zona']}
Latitude/Longitude: {record['latitude']} / {record['longitude']}
Quem recebeu: {record['quem_recebeu']}
Status Atual: {record['status']}
""")
    pdf.ln(4)

    # Descrição
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 6, "DESCRIÇÃO DA ORDEM DE SERVIÇO:", ln=True)

    pdf.set_font("Arial", "", 10)
    pdf.set_fill_color(240, 240, 240)
    desc_text = record['descricao'] if record['descricao'] else "Sem descrição."
    # Tratamento para caracteres especiais
    try:
        pdf.multi_cell(0, 5, desc_text, 1, 'L', 1)
    except:
        pdf.multi_cell(0, 5, "Erro na codificação do texto. Verifique caracteres especiais.", 1, 'L', 1)
        
    pdf.ln(6)

    # Campo Observações
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 6, "OBSERVAÇÕES DE CAMPO / AÇÕES REALIZADAS:", ln=True)
    pdf.multi_cell(0, 6, " " * 100 + "\n"*5, 1, 'L', 0) 
    pdf.ln(1)
    
    # --- PÁGINAS SEGUINTES: Reincidências ---
    if reincidencias:
        for i, reinc in enumerate(reincidencias):
            pdf.add_page()
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, f"Reincidência #{i+1} - {record['external_id']}", ln=True, align='L')
            pdf.ln(5)
            
            pdf.set_font("Arial", "", 11)
            pdf.multi_cell(0, 6, f"""
Data da Reincidência: {reinc['created_at']}
Fonte da Informação: {reinc['fonte']}
""")
            pdf.ln(4)
            
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 6, "DESCRIÇÃO DA REINCIDÊNCIA:", ln=True)
            
            pdf.set_font("Arial", "", 10)
            pdf.set_fill_color(255, 250, 240)
            r_desc = reinc['descricao'] if reinc['descricao'] else "Sem descrição."
            pdf.multi_cell(0, 5, r_desc, 1, 'L', 1)

    # CORREÇÃO CRÍTICA DO PDF: Retornar bytes codificados em latin-1
    return pdf.output(dest="S").encode('latin-1')

# =========================================
# CALLBACKS
# =========================================
def handle_form_submit(external_id, created_at, origem, tipo, rua, numero, bairro, zona, lat, lon, descricao, quem_recebeu, acao_noturna):
    record = {
        'external_id': external_id,
        'created_at': created_at,
        'origem': origem,
        'tipo': tipo,
        'rua': rua,
        'numero': numero,
        'bairro': bairro,
        'zona': zona,
        'latitude': lat,
        'longitude': lon,
        'descricao': descricao,
        'quem_recebeu': quem_recebeu,
        'status': 'Pendente',
        'acao_noturna': acao_noturna
    }
    try:
        insert_denuncia(record)
        st.success('Denúncia salva com sucesso!')
        
        # Gera PDF inicial
        pdf_bytes = create_pdf_from_record(record, [])
        
        if pdf_bytes: 
            st.session_state['download_pdf_data'] = pdf_bytes
            st.session_state['download_pdf_id'] = external_id
            if 'last_edited_pdf' in st.session_state: del st.session_state['last_edited_pdf']
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

# =========================================
# INICIALIZAÇÃO E UI
# =========================================
init_db()
if 'user' not in st.session_state:
    st.session_state['user'] = None

st.markdown("""
<style>
header {visibility: hidden}
footer {visibility: hidden}
.sidebar .sidebar-content {background: linear-gradient(#0b3b2e, #2f6f4f);}
.h1-urb {font-weight:800; color: #003300;}
[data-testid="stSidebar"] .st-emotion-cache-p5m9y8 p {color: #DAA520; font-weight: bold; font-size: 1.1em;}
.stButton>button[kind="primary"] {background-color: #E53935; border: none;}
</style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1,4])
with col2:
    st.markdown("<h1 class='h1-urb'>URB <span style='color:#DAA520'>Fiscalização - Denúncias</span></h1>", unsafe_allow_html=True)

# ---------------------- Login ----------------------
if st.session_state['user'] is None:
    st.subheader("Login")
    login_col1, login_col2 = st.columns(2)
    with login_col1:
        username = st.text_input('Usuário')
    with login_col2:
        password = st.text_input('Senha', type='password')
    if st.button('Entrar'):
        user = verify_user(username.strip(), password)
        if user:
            st.session_state['user'] = user
            st.rerun()
        else:
            st.error('Usuário ou senha incorretos')
    st.info("Admin padrão: 'admin' / 'fisc2023'")
    st.stop()

user = st.session_state['user']
st.sidebar.markdown("<h3 style='color:#DAA520; font-weight:bold;'>URB Fiscalização</h3>", unsafe_allow_html=True)
st.sidebar.markdown("---") 
st.sidebar.markdown(f"**Usuário:** {user['full_name']} ({user['username']})")
if user.get('is_admin'):
    st.sidebar.success('Administrador')

# ---------------------- Navegação ----------------------
pages = ["Registro da denuncia", "Historico"]
if user.get('is_admin'):
    pages.insert(0, 'Admin - Gestão de Usuários')
page = st.sidebar.selectbox('Navegação', pages)

# ---------------------- Página Admin ----------------------
if page == 'Admin - Gestão de Usuários':
    st.header('Administração - Cadastrar novos usuários')
    with st.form('add_user'):
        new_username = st.text_input('Nome de usuário')
        new_fullname = st.text_input('Nome completo')
        new_password = st.text_input('Senha', type='password')
        submitted = st.form_submit_button('Adicionar usuário')
        if submitted:
            if new_username and new_password:
                ok = add_user(new_username.strip(), new_password.strip(), new_fullname.strip())
                if ok: st.success('Usuário criado com sucesso')
                else: st.error('Usuário já existe')
            else:
                st.error('Preencha usuário e senha')
    st.markdown('---')
    dfu = get_all_users()
    st.dataframe(dfu)
    st.stop()

# ---------------------- Página Registro ----------------------
if page == 'Registro da denuncia':
    st.header('Registro da Denúncia')
    with st.form('registro'):
        external_id = generate_external_id()
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        st.write(f"**Id da denúncia (Prévia):** {external_id} | **Data:** {created_at}")

        origem = st.selectbox('Origem da denúncia', OPCOES_ORIGEM)
        c_tipo, c_noturna = st.columns([3,1])
        tipo = c_tipo.selectbox('Tipo de denúncia', OPCOES_TIPO)
        acao_noturna = c_noturna.checkbox("Ação Noturna?")

        c1, c2 = st.columns(2)
        rua = c1.text_input('Nome da rua')
        numero = c2.text_input('Número')

        bairro = st.selectbox('Bairro', OPCOES_BAIRROS)
        zona = st.selectbox('Zona', OPCOES_ZONA)

        c3, c4 = st.columns(2)
        lat = c3.text_input('Latitude')
        lon = c4.text_input('Longitude')

        if lat and lon:
            maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            st.markdown(f"[Abrir localização no Google Maps]({maps_link})")

        descricao = st.text_area('Descrição da Ordem de Serviço', height=150)
        quem_recebeu = st.selectbox('Quem recebeu a denúncia', OPCOES_FISCAIS)

        st.form_submit_button(
            'Salvar denúncia',
            on_click=handle_form_submit,
            args=(external_id, created_at, origem, tipo, rua, numero, bairro, zona, lat, lon, descricao, quem_recebeu, acao_noturna)
        )

    # Download PDF
    if 'download_pdf_data' in st.session_state and 'download_pdf_id' in st.session_state:
        pdf_data = st.session_state['download_pdf_data']
        pdf_id = st.session_state['download_pdf_id']
        st.markdown("---")
        col_down, col_clear = st.columns([1,1])
        with col_down:
            st.download_button(
                label='📥 Baixar Ordem de Serviço (PDF)', 
                data=pdf_data, 
                file_name=f"OS_{pdf_id.replace('/', '_')}.pdf", 
                mime='application/pdf'
            )
        with col_clear:
            if st.button("Limpar / Novo Registro"):
                del st.session_state['download_pdf_data']
                del st.session_state['download_pdf_id']
                if 'last_edited_pdf' in st.session_state: del st.session_state['last_edited_pdf']
                st.rerun()

# ---------------------- Página Histórico ----------------------
if page == 'Historico':
    st.header('Histórico de Denúncias')
    df = fetch_all_denuncias()

    if df.empty:
        st.info('Nenhuma denúncia registrada ainda.')
        st.stop()

    display_df = df.copy()
    display_df['created_at'] = pd.to_datetime(display_df['created_at'])
    
    # Filtros
    st.subheader('Pesquisar / Filtrar')
    cols = st.columns(4)
    q_ext = cols[0].text_input('Id (ex: 0001/2025)')
    q_status = cols[2].selectbox('Status', options=['Todos'] + OPCOES_STATUS)
    q_text = cols[3].text_input('Texto na descrição')

    mask = pd.Series([True]*len(display_df))
    if q_ext: mask = mask & display_df['external_id'].str.contains(q_ext, na=False)
    if q_status and q_status != 'To
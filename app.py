import streamlit as st
import pandas as pd
import os
import psycopg2
from datetime import datetime
import hashlib
from fpdf import FPDF

# Configuração da Página
st.set_page_config(page_title="URB Fiscalização - Denúncias", layout="wide")

# --- CONFIGURAÇÃO DO BANCO DE DADOS (Postgres) ---
# O Render fornece a URL do banco na variável de ambiente DATABASE_URL
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    """Estabelece conexão com o Postgres."""
    if not DATABASE_URL:
        st.error("Erro: A variável de ambiente DATABASE_URL não foi encontrada.")
        st.stop()
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        st.error(f"Erro ao conectar ao banco de dados: {e}")
        st.stop()

# Listas de Opções Globais
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

# ---------------------- Utilities & DB Init ----------------------

def safe_index(lista, valor, padrao=0):
    try:
        return lista.index(valor)
    except ValueError:
        return padrao

def init_db():
    """Cria tabelas no Postgres se não existirem."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Tabela de Denúncias (Sem fotos)
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
    
    # 2. Tabela de Usuários (Substitui o JSON)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            full_name TEXT,
            is_admin BOOLEAN DEFAULT FALSE
        );
    ''')

    # Cria usuário Admin padrão se não existir
    cur.execute("SELECT * FROM users WHERE username = %s", ('admin',))
    if not cur.fetchone():
        # Senha padrão: fisc2023
        pass_hash = hashlib.sha256('fisc2023'.encode('utf-8')).hexdigest()
        cur.execute("INSERT INTO users (username, password, full_name, is_admin) VALUES (%s, %s, %s, %s)", 
                    ('admin', pass_hash, 'Administrador', True))

    conn.commit()
    cur.close()
    conn.close()

def hash_password(password: str):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

# ---------------------- User Management (Postgres) ----------------------

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
        conn.rollback() # Usuário já existe
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
        # Retorna dicionário compatível com a lógica anterior
        return {'username': user_data[0], 'full_name': user_data[1], 'is_admin': user_data[2]}
    return None

def get_all_users():
    conn = get_db_connection()
    df = pd.read_sql("SELECT username, full_name, is_admin FROM users", conn)
    conn.close()
    return df

# ---------------------- Denuncias Logic (Postgres) ----------------------

def generate_external_id():
    """Gera ID sequencial."""
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
    # Sintaxe do Postgres usa %s
    cur.execute('''
        INSERT INTO denuncias (external_id, created_at, origem, tipo, rua, numero, bairro, zona, latitude, longitude, descricao, quem_recebeu, status) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        record['external_id'], record['created_at'], record['origem'], record['tipo'], 
        record['rua'], record['numero'], record['bairro'], record['zona'], 
        record['latitude'], record['longitude'], record['descricao'], 
        record['quem_recebeu'], record.get('status','Pendente')
    ))
    conn.commit()
    cur.close()
    conn.close()

def fetch_all_denuncias():
    conn = get_db_connection()
    df = pd.read_sql_query('SELECT * FROM denuncias ORDER BY id DESC', conn)
    conn.close()
    return df

def fetch_denuncia_by_id(id_):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM denuncias WHERE id = %s', (id_,))
    
    # Obter nomes das colunas para criar dicionário
    if cur.description:
        colnames = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        if row:
            record = dict(zip(colnames, row))
            return record
            
    cur.close()
    conn.close()
    return None

def update_denuncia_status(id_, status):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE denuncias SET status = %s WHERE id = %s', (status, id_))
    conn.commit()
    cur.close()
    conn.close()

def delete_denuncia(id_):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM denuncias WHERE id = %s', (id_,))
    conn.commit()
    cur.close()
    conn.close()

def update_denuncia_full(id_, row):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''UPDATE denuncias SET origem=%s, tipo=%s, rua=%s, numero=%s, bairro=%s, zona=%s, latitude=%s, longitude=%s, descricao=%s, quem_recebeu=%s, status=%s WHERE id=%s''', (
        row['origem'], row['tipo'], row['rua'], row['numero'], row['bairro'], row['zona'], 
        row['latitude'], row['longitude'], row['descricao'], 
        row['quem_recebeu'], row['status'], id_
    ))
    conn.commit()
    cur.close()
    conn.close()

# ---------------------- PDF Generation ----------------------
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'URB Fiscalização - Ordem de Serviço', 0, 1, 'C')

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Página %s' % self.page_no(), 0, 0, 'C')

def create_pdf_from_record(record):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    
    # Header Info
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"Ordem de Serviço Nº {record['external_id']}", ln=True, align='L')
    pdf.ln(2)

    pdf.set_font("Arial", "", 11)
    
    # Detalhes
    pdf.multi_cell(0, 6, f"""
Data/Hora: {record['created_at']}
Origem: {record['origem']}
Tipo: {record['tipo']}
Endereço: {record['rua']}, {record['numero']}
Bairro/Zona: {record['bairro']} / {record['zona']}
Latitude/Longitude: {record['latitude']} / {record['longitude']}
Quem recebeu: {record['quem_recebeu']}
Status: {record['status']}
""")
    pdf.ln(4)
    
    # Descrição
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 6, "DESCRIÇÃO DA ORDEM DE SERVIÇO:", ln=True)
    
    pdf.set_font("Arial", "", 10)
    pdf.set_fill_color(240, 240, 240)
    
    # Tratamento para None caso descrição venha vazia do banco
    desc_text = record['descricao'] if record['descricao'] else "Sem descrição."
    pdf.multi_cell(0, 5, desc_text, 1, 'L', 1)
    
    pdf.ln(6)
    
    # Campo Observações
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 6, "OBSERVAÇÕES DE CAMPO / AÇÕES REALIZADAS:", ln=True)
    pdf.multi_cell(0, 6, " " * 100, 1, 'L', 0) 
    pdf.ln(1)

    pdf_bytes = pdf.output(dest="S") 
    return pdf_bytes

# ---------------------- Callback ----------------------

def handle_form_submit(external_id, created_at, origem, tipo, rua, numero, bairro, zona, lat, lon, descricao, quem_recebeu):
    """Callback simplificado (sem fotos)."""
    
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
        'status': 'Pendente'
    }
    
    try:
        insert_denuncia(record)
        st.success('Denúncia salva com sucesso!')

        # Gerar PDF
        pdf_bytes = create_pdf_from_record(record)
        
        if isinstance(pdf_bytes, bytearray):
            pdf_bytes = bytes(pdf_bytes) 
            
        if pdf_bytes and isinstance(pdf_bytes, bytes): 
            st.session_state['download_pdf_data'] = pdf_bytes
            st.session_state['download_pdf_id'] = external_id
            
            if 'last_edited_pdf' in st.session_state:
                 del st.session_state['last_edited_pdf']
        else:
            st.warning("⚠️ Falha na geração do PDF.")

    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
    
    # Não usamos st.rerun() dentro do callback, deixamos o fluxo seguir ou usamos no main
    # O form_submit_button já causará um rerun natural do script ao finalizar o callback.

# ---------------------- Inicialização ----------------------
init_db()
if 'user' not in st.session_state:
    st.session_state['user'] = None

# ---------------------- Layout & CSS ----------------------
st.markdown("""
<style>
header {visibility: hidden}
footer {visibility: hidden}
.sidebar .sidebar-content {background: linear-gradient(#0b3b2e, #2f6f4f);}
.h1-urb {font-weight:800; color: #003300;}
[data-testid="stSidebar"] .st-emotion-cache-p5m9y8 p {color: #DAA520; font-weight: bold; font-size: 1.1em;}
</style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1,4])
with col2:
    st.markdown("<h1 class='h1-urb'>URB <span style='color:#DAA520'>Fiscalização - Denúncias</span></h1>", unsafe_allow_html=True)
    st.write("")

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
    st.info("Administrador padrão: usuário 'admin' / senha 'fisc2023'")
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

# ---------------------- Página: Admin ----------------------
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
                if ok:
                    st.success('Usuário criado com sucesso')
                else:
                    st.error('Usuário já existe')
            else:
                st.error('Preencha usuário e senha')
    st.markdown('---')
    dfu = get_all_users()
    st.dataframe(dfu)
    st.stop()

# ---------------------- Página: Registro ----------------------
if page == 'Registro da denuncia':
    st.header('Registro da Denúncia')

    with st.form('registro'):
        external_id = generate_external_id()
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        st.write(f"**Id da denúncia (Prévia):** {external_id}")
        st.write(f"**Data e Hora:** {created_at}")

        origem = st.selectbox('Origem da denúncia', OPCOES_ORIGEM, key='f_origem')
        tipo = st.selectbox('Tipo de denúncia', OPCOES_TIPO, key='f_tipo')
        
        c1, c2 = st.columns(2)
        rua = c1.text_input('Nome da rua', key='f_rua')
        numero = c2.text_input('Número', key='f_numero')
        
        bairro = st.selectbox('Bairro', OPCOES_BAIRROS, key='f_bairro')
        zona = st.selectbox('Zona', OPCOES_ZONA, key='f_zona')
        
        c3, c4 = st.columns(2)
        lat = c3.text_input('Latitude', key='f_lat')
        lon = c4.text_input('Longitude', key='f_lon')
        
        if lat and lon:
            maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            st.markdown(f"[Abrir localização no Google Maps]({maps_link})")
            
        descricao = st.text_area('Descrição da Ordem de Serviço', height=150, key='f_descricao')
        # FOTOS REMOVIDAS CONFORME SOLICITADO
        quem_recebeu = st.selectbox('Quem recebeu a denúncia', OPCOES_FISCAIS, key='f_quem_recebeu')

        st.form_submit_button(
            'Salvar denúncia',
            on_click=handle_form_submit,
            args=(external_id, created_at, origem, tipo, rua, numero, bairro, zona, lat, lon, descricao, quem_recebeu)
        )

    # Download PDF
    if 'download_pdf_data' in st.session_state and 'download_pdf_id' in st.session_state:
        pdf_data = st.session_state['download_pdf_data']
        pdf_id = st.session_state['download_pdf_id']
        
        st.markdown("---")
        st.subheader("Documento Gerado")
        
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
                if 'last_edited_pdf' in st.session_state:
                      del st.session_state['last_edited_pdf']
                st.rerun()

# ---------------------- Página: Histórico ----------------------
if page == 'Historico':
    st.header('Histórico de Denúncias')
    df = fetch_all_denuncias()
    
    if df.empty:
        st.info('Nenhuma denúncia registrada ainda.')
        st.stop()

    display_df = df.copy()
    display_df['created_at'] = pd.to_datetime(display_df['created_at'])
    display_df['dias_passados'] = (pd.Timestamp(datetime.now()) - display_df['created_at']).dt.days

    # Filtros
    st.subheader('Pesquisar / Filtrar')
    cols = st.columns(4)
    q_ext = cols[0].text_input('Id (ex: 0001/2025)')
    q_status = cols[2].selectbox('Status', options=['Todos','Pendente','Concluída'])
    q_text = cols[3].text_input('Texto na descrição')

    mask = pd.Series([True]*len(display_df))
    if q_ext:
        mask = mask & display_df['external_id'].str.contains(q_ext, na=False)
    if q_status and q_status != 'Todos':
        mask = mask & (display_df['status'] == q_status)
    if q_text:
        mask = mask & display_df['descricao'].str.contains(q_text, na=False)

    filtered = display_df[mask]

    # Exibição
    st.subheader(f'Resultados ({len(filtered)})')
    
    styled_df = filtered[['id','external_id','created_at','origem','tipo','bairro','quem_recebeu','status','dias_passados']].copy()
    styled_df['created_at'] = styled_df['created_at'].dt.strftime('%d/%m/%Y %H:%M')

    st.dataframe(styled_df, use_container_width=True)

    # Ações em Lote
    sel_ids = st.multiselect('Selecione IDs para Ações em Massa', options=filtered['id'].tolist())
    
    if sel_ids:
        action_col1, action_col2, action_col3 = st.columns(3)
        with action_col1:
            if st.button('✅ Marcar como Concluída'):
                for i in sel_ids:
                    update_denuncia_status(i, 'Concluída')
                st.success('Atualizado!')
                st.rerun()
        with action_col2:
            if st.button('🗑️ Excluir Selecionados'):
                for i in sel_ids:
                    delete_denuncia(i)
                st.success('Excluído(s)!')
                st.rerun()
        with action_col3:
            if st.button('⬇️ Exportar CSV'):
                export_df = df[df['id'].isin(sel_ids)].copy()
                csv = export_df.to_csv(index=False)
                st.download_button('Baixar CSV', csv, file_name='denuncias_selecionadas.csv', mime='text/csv')

    st.markdown('---')
    
    # ---------------------- Editar Denúncia ----------------------
    st.subheader('Editar Detalhes')
    edit_id = st.number_input('ID interno da denúncia a editar', min_value=1, step=1, key='edit_id_input')
    
    if st.button('Carregar para edição'):
        st.session_state['edit_mode_id'] = int(edit_id)
        if 'download_pdf_data' in st.session_state:
             del st.session_state['download_pdf_data']
             del st.session_state['download_pdf_id']
        if 'last_edited_pdf' in st.session_state:
             del st.session_state['last_edited_pdf']

    if 'edit_mode_id' in st.session_state:
        target_id = st.session_state['edit_mode_id']
        rec = fetch_denuncia_by_id(target_id)
        
        if not rec:
            st.error('ID não encontrado')
        else:
            st.info(f"Editando ID: {rec['external_id']}")
            
            with st.form('edit_form'):
                idx_origem = safe_index(OPCOES_ORIGEM, rec['origem'])
                idx_tipo = safe_index(OPCOES_TIPO, rec['tipo'])
                idx_bairro = safe_index(OPCOES_BAIRROS, rec['bairro'])
                idx_zona = safe_index(OPCOES_ZONA, rec['zona'])
                idx_fiscal = safe_index(OPCOES_FISCAIS, rec['quem_recebeu'])
                
                c_e1, c_e2 = st.columns(2)
                origem_e = c_e1.selectbox('Origem', OPCOES_ORIGEM, index=idx_origem)
                tipo_e = c_e2.selectbox('Tipo', OPCOES_TIPO, index=idx_tipo)
                
                rua_e = st.text_input('Rua', value=rec['rua'])
                numero_e = st.text_input('Número', value=rec['numero'])
                
                bairro_e = st.selectbox('Bairro', OPCOES_BAIRROS, index=idx_bairro)
                zona_e = st.selectbox('Zona', OPCOES_ZONA, index=idx_zona)
                
                lat_e = st.text_input('Latitude', value=rec['latitude'])
                lon_e = st.text_input('Longitude', value=rec['longitude'])
                desc_e = st.text_area('Descrição', value=rec['descricao'])
                
                quem_e = st.selectbox('Quem recebeu', OPCOES_FISCAIS, index=idx_fiscal)
                
                status_atual = rec['status']
                idx_status = 0 if status_atual == 'Pendente' else 1
                status_e = st.selectbox('Status', ['Pendente','Concluída'], index=idx_status)
                
                submitted_e = st.form_submit_button('Salvar alterações')
                
                if submitted_e:
                    newrow = {
                        'origem': origem_e,
                        'tipo': tipo_e,
                        'rua': rua_e,
                        'numero': numero_e,
                        'bairro': bairro_e,
                        'zona': zona_e,
                        'latitude': lat_e,
                        'longitude': lon_e,
                        'descricao': desc_e,
                        'quem_recebeu': quem_e,
                        'status': status_e
                    }
                    update_denuncia_full(target_id, newrow)
                    st.success('Registro atualizado com sucesso!')

                    # PDF Pós Edição
                    updated_record = fetch_denuncia_by_id(target_id)
                    try:
                        pdf_bytes = create_pdf_from_record(updated_record)
                        if isinstance(pdf_bytes, bytearray):
                            pdf_bytes = bytes(pdf_bytes) 

                        if pdf_bytes and isinstance(pdf_bytes, bytes): 
                            st.session_state['last_edited_pdf'] = {
                                'data': pdf_bytes,
                                'external_id': updated_record['external_id']
                            }
                            if 'download_pdf_data' in st.session_state:
                                del st.session_state['download_pdf_data']
                                del st.session_state['download_pdf_id']
                        else:
                            st.warning("⚠️ PDF atualizado falhou.")
                    except Exception as e:
                        st.error(f"Erro PDF: {e}")

                    del st.session_state['edit_mode_id']
                    st.rerun()

    # Download Pós-Edição
    if 'last_edited_pdf' in st.session_state:
        pdf_info = st.session_state['last_edited_pdf']
        st.markdown("---")
        st.subheader("📥 Baixar PDF Atualizado")
        
        c_down, c_info = st.columns([1,2])
        with c_down:
            st.download_button(
                label='Baixar Ordem de Serviço Editada', 
                data=pdf_info['data'], 
                file_name=f"OS_{pdf_info['external_id'].replace('/', '_')}_EDITADA.pdf", 
                mime='application/pdf'
            )
        with c_info:
             st.info(f"PDF gerado para OS Nº {pdf_info['external_id']}.")
        
        if st.button("Esconder Download"):
            del st.session_state['last_edited_pdf']
            st.rerun()

st.markdown('---')
st.caption('Aplicação URB Fiscalização - Postgres/Render Edition')
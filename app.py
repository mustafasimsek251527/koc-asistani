import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
import uuid
import io
import random
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- GOOGLE SHEETS BAĞLANTI AYARLARI ---
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS_FILE = "credentials.json"
SPREADSHEET_NAME = "EgitimKocuDB"

def get_gsheets_client():
    # Streamlit Cloud üzerinde secrets kullanılıyorsa ona bak
    if "gcp_service_account" in st.secrets:
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    # Yerel geliştirme ortamında credentials.json dosyasına bak
    elif os.path.exists(CREDS_FILE):
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    else:
        st.error("Kimlik doğrulama verisi bulunamadı! (secrets veya credentials.json eksik)")
        st.stop()
        
    client = gspread.authorize(creds)
    return client

def init_gsheets():
    client = get_gsheets_client()
    try:
        sh = client.open(SPREADSHEET_NAME)
    except gspread.SpreadsheetNotFound:
        sh = client.create(SPREADSHEET_NAME)
        # Tabloyu paylaştıysanız (credentials içindeki mail ile) burası çalışır.
        # Manuel paylaşım gerekebilir.
        
    # Kullanicilar Sayfası
    try:
        u_sheet = sh.worksheet("Kullanicilar")
    except gspread.WorksheetNotFound:
        u_sheet = sh.add_worksheet(title="Kullanicilar", rows="100", cols="3")
        u_sheet.append_row(["KullaniciAdi", "Sifre", "Rol"])
        u_sheet.append_row(["admin", "1234", "admin"]) # Varsayılan admin
        
    # Ogrenciler Sayfası
    try:
        o_sheet = sh.worksheet("Ogrenciler")
    except gspread.WorksheetNotFound:
        o_sheet = sh.add_worksheet(title="Ogrenciler", rows="1000", cols="7")
        o_sheet.append_row(["Ad", "Soyad", "TC", "Devre", "Koc", "Kaynaklar", "Odevler"])
    
    return sh

# Global Sheet Connection
try:
    SHEET_DB = init_gsheets()
except Exception as e:
    st.error(f"Google Sheets bağlantı hatası: {e}")
    st.stop()

# --- KULLANICI YÖNETİM SİSTEMİ ---
def load_users():
    sheet = SHEET_DB.worksheet("Kullanicilar")
    records = sheet.get_all_records()
    # Sheet sütun isimlerini kod içindeki isimlere eşle
    return [{"kullanici_adi": r["KullaniciAdi"], "sifre": str(r["Sifre"]), "rol": r["Rol"]} for r in records]

def save_users(users):
    sheet = SHEET_DB.worksheet("Kullanicilar")
    sheet.clear()
    sheet.append_row(["KullaniciAdi", "Sifre", "Rol"])
    for u in users:
        sheet.append_row([u["kullanici_adi"], u["sifre"], u["rol"]])

def login():
    st.title("🔐 Eğitim Koçluğu Giriş")
    users = load_users()
    with st.form("login_form"):
        kullanici = st.text_input("Kullanıcı Adı")
        sifre = st.text_input("Şifre", type="password")
        if st.form_submit_button("Giriş Yap"):
            user_found = next((u for u in users if u["kullanici_adi"] == kullanici and u["sifre"] == sifre), None)
            if user_found:
                st.session_state.logged_in = True
                st.session_state.user = kullanici
                st.session_state.user_rol = user_found["rol"]
                st.success("Giriş Başarılı!")
                st.rerun()
            else:
                st.error("Hatalı kullanıcı adı veya şifre!")

# --- PDF FONT AYARI (Türkçe Karakter Desteği) ---
try:
    pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
    PDF_FONT = 'Arial'
except:
    PDF_FONT = 'Helvetica'

# --- YARDIMCI FONKSİYONLAR ---
def tr_upper(text):
    if not text: return ""
    # Türkçe karakterler için özel dönüşüm
    text = text.replace('i', 'İ').replace('ı', 'I').upper()
    return text

def slugify_tr(text):
    if not text: return ""
    char_map = {
        'ç': 'c', 'ğ': 'g', 'ı': 'i', 'ö': 'o', 'ş': 's', 'ü': 'u',
        'Ç': 'c', 'Ğ': 'g', 'İ': 'i', 'Ö': 'o', 'Ş': 's', 'Ü': 'u',
        'I': 'i'
    }
    for tr, en in char_map.items():
        text = text.replace(tr, en)
    text = text.lower().strip().replace(" ", "_")
    # Alfanümerik ve alt çizgi dışındakileri temizle (opsiyonel ama iyi olur)
    text = "".join(c for c in text if c.isalnum() or c == "_")
    return text

# --- DINAMIK MÜFREDAT VERİTABANI (Devre Bazlı) ---
MUFREDAT = {
    "5. Sınıf": {
        "Türkçe": ["Sözcükte Anlam", "Cümlede Anlam", "Paragraf / Metin Yorumlama", "Ses Bilgisi", "Yazım Kuralları", "Noktalama İşaretleri", "Sözcükte Yapı (Kök-Ek)", "Söz Sanatları", "Metin Türleri"],
        "Matematik": ["Doğal Sayılar", "Doğal Sayılarla İşlemler", "Kesirler", "Kesirlerle İşlemler", "Ondalık Gösterim", "Yüzdeler", "Temel Geometrik Kavramlar", "Üçgen ve Dörtgenler", "Veri İşleme", "Uzunluk ve Zaman Ölçme", "Alan Ölçme", "Geometrik Cisimler"],
        "Fen Bilimleri": ["Güneş, Dünya ve Ay", "Canlılar Dünyası", "Kuvvetin Ölçülmesi ve Sürtünme", "Madde ve Değişim", "Işığın Yayılması", "İnsan ve Çevre", "Elektrik Devre Elemanları"],
        "Sosyal Bilgiler": ["Birey ve Toplum", "Kültür ve Miras", "İnsanlar, Yerler ve Çevreler", "Bilim, Teknoloji ve Toplum", "Üretim, Dağıtım ve Tüketim", "Etkin Vatandaşlık", "Küresel Bağlantılar"],
        "İngilizce": ["Hello!", "My Town", "Games and Hobbies", "My Daily Routine", "Health", "Movies", "Party Time", "Fitness", "The Animal Shelter", "Festivals"],
        "Din Kültürü": ["Allah İnancı", "Ramazan ve Oruç", "Adap ve Nezaket", "Hz. Muhammed'in Aile Hayatı", "Çevremizde Dinin İzleri"]
    },
    "6. Sınıf": {
        "Türkçe": ["Sözcükte Anlam", "Cümlede Anlam", "Paragraf", "İsimler", "Sıfatlar", "Zamirler", "Tamlamalar", "Edat-Bağlaç-Ünlem", "Yazım-Noktalama", "Metin Türleri"],
        "Matematik": ["Doğal Sayılarla İşlemler", "Çarpanlar ve Katlar", "Kümeler", "Tam Sayılar", "Kesirlerle İşlemler", "Ondalık Gösterim", "Oran", "Cebirsel İfadeler", "Veri Analizi", "Açılar", "Alan Ölçme", "Çember", "Geometrik Cisimler", "Sıvı Ölçme"],
        "Fen Bilimleri": ["Güneş Sistemi ve Tutulmalar", "Vücudumuzdaki Sistemler (Destek-Hareket, Sindirim, Dolaşım, Solunum, Boşaltım)", "Kuvvet ve Hareket", "Madde ve Isı", "Ses ve Özellikleri", "Vücudumuzdaki Sistemler ve Sağlığı (Denetleyici-Düzenleyici)", "Elektriğin İletimi"],
        "Sosyal Bilgiler": ["Biz ve Değerlerimiz", "Tarihe Yolculuk", "Yeryüzünde Yaşam", "Bilim ve Teknoloji Hayatımızda", "Üretim, Tüketim ve Ekonomi", "Yönetime Katılıyorum", "Uluslararası İlişkilerimiz"],
        "İngilizce": ["Life", "Yummy Breakfast", "Downtown", "Weather and Emotions", "At the Fair", "Vacation", "Occupations", "Detectives at Work", "Saving the Planet", "Democracy"],
        "Din Kültürü": ["Peygamber ve İlahi Kitap İnancı", "Namaz", "Zararlı Alışkanlıklar", "Hz. Muhammed'in Hayatı", "Temel Değerlerimiz"]
    },
    "7. Sınıf": {
        "Türkçe": ["Sözcükte Anlam", "Cümlede Anlam", "Paragraf", "Fiiller (Kip ve Kişi)", "Ek Fiil", "Zarflar", "Fiillerin Yapısı", "Anlatım Bozuklukları", "Yazım-Noktalama"],
        "Matematik": ["Tam Sayılarla İşlemler", "Rasyonel Sayılar", "Rasyonel Sayılarla İşlemler", "Cebirsel İfadeler", "Eşitlik ve Denklem", "Oran ve Orantı", "Yüzdeler", "Doğrular ve Açılar", "Çokgenler", "Çember ve Daire", "Veri Analizi"],
        "Fen Bilimleri": ["Güneş Sistemi ve Ötesi", "Hücre ve Bölünmeler", "Kuvvet ve Enerji", "Saf Madde ve Karışımlar", "Işığın Madde ile Etkileşimi", "Canlılarda Üreme, Büyüme ve Gelişme", "Elektrik Devreleri"],
        "Sosyal Bilgiler": ["Birey ve Toplum", "Türk Tarihinde Yolculuk", "Ülkemizde Nüfus", "Zaman İçinde Bilim", "Ekonomi ve Sosyal Hayat", "Yaşayan Demokrasi", "Ülkeler Arası Köprüler"],
        "İngilizce": ["Appearance and Personality", "Sports", "Biographies", "Wild Animals", "Television", "Celebrations", "Dreams", "Public Buildings", "Environment", "Planets"],
        "Din Kültürü": ["Melek ve Ahiret İnancı", "Hac ve Kurban", "Ahlaki Davranışlar", "Allah'ın Kulu ve Elçisi Hz. Muhammed", "İslam Düşüncesinde Yorumlar"]
    },
    "8. Sınıf": {
        "Türkçe": ["Fiilimsiler", "Sözcükte Anlam", "Cümlede Anlam", "Paragraf / Görsel Okuma", "Cümlenin Ögeleri", "Fiilde Çatı", "Cümle Türleri", "Anlatım Bozuklukları", "Yazım Kuralları", "Noktalama İşaretleri", "Sözel Mantık ve Muhakeme"],
        "Matematik": ["Çarpanlar ve Katlar", "Üslü İfadeler", "Kareköklü İfadeler", "Veri Analizi", "Basit Olayların Olma Olasılığı", "Cebirsel İfadeler ve Özdeşlikler", "Doğrusal Denklemler", "Eşitsizlikler", "Üçgenler", "Eşlik ve Benzerlik", "Dönüşüm Geometrisi", "Geometrik Cisimler"],
        "Fen Bilimleri": ["Mevsimlerin Oluşumu ve İklim", "DNA ve Genetik Kod", "Basınç", "Madde ve Endüstri", "Basit Makineler", "Enerji Dönüşümleri ve Çevre Bilimi", "Elektrik Yükleri ve Elektrik Enerjisi"],
        "T.C. İnkılap Tarihi": ["Bir Kahraman Doğuyor", "Milli Uyanış", "Ya İstiklal Ya Ölüm", "Atatürkçülük ve Çağdaşlaşan Türkiye", "Demokratikleşme Çabaları", "Atatürk Dönemi Dış Politika", "Atatürk'ün Ölümü ve Sonrası"],
        "İngilizce": ["Friendship", "Teen Life", "In the Kitchen", "On the Phone", "The Internet", "Adventures", "Tourism", "Chores", "Science", "Natural Forces"],
        "Din Kültürü": ["Kader İnancı", "Zekat ve Sadaka", "Din ve Hayat", "Hz. Muhammed'in Örnekliği", "Kuran-ı Kerim ve Özellikleri"]
    }
}

# --- PDF OLUŞTURMA FONKSİYONU ---
def create_homework_pdf(student, homeworks):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    # Başlık Stilleri
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName=PDF_FONT, fontSize=18, alignment=1, spaceAfter=20)
    info_style = ParagraphStyle('InfoStyle', parent=styles['Normal'], fontName=PDF_FONT, fontSize=12, alignment=0, spaceAfter=10)
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontName=PDF_FONT, fontSize=10)
    
    # PDF Başlığı ve Öğrenci Bilgisi
    elements.append(Paragraph("EĞİTİM KOÇLUĞU ÖDEV PROGRAMI", title_style))
    elements.append(Paragraph(f"<b>Öğrenci:</b> {student['ad']} {student['soyad']} - {student['devre']}", info_style))
    elements.append(Paragraph(f"<b>Tarih:</b> {datetime.now().strftime('%d.%m.%Y')}", info_style))
    elements.append(Spacer(1, 12))
    
    # Ödev Tablosu
    data = [["Ders", "Konu", "Kaynak", "Test Aralığı", "Teslim Tarihi"]]
    incomplete_hw = [hw for hw in homeworks if not hw["tamamlandi"]]
    for hw in incomplete_hw:
        # Türkçe karakterleri korumak için string dönüşümü (Reportlab zaten Arial ile destekler ama emin olalım)
        data.append([
            str(hw["ders"]), 
            str(hw["konu"]), 
            str(hw["kaynak"]), 
            str(hw["detay"]), 
            str(hw["tarih"])
        ])
    
    if len(data) > 1:
        t = Table(data, colWidths=[90, 110, 120, 100, 70])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), PDF_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(t)
    else:
        elements.append(Paragraph("Atanmış ve bekleyen ödev bulunmamaktadır.", normal_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- VERİ YÖNETİMİ ---
def load_data():
    try:
        sheet = SHEET_DB.worksheet("Ogrenciler")
        records = sheet.get_all_records()
        students = []
        for r in records:
            students.append({
                "ad": r["Ad"],
                "soyad": r["Soyad"],
                "tc": str(r["TC"]),
                "devre": r["Devre"],
                "koc": r["Koc"],
                "kitaplar": json.loads(r["Kaynaklar"]) if r["Kaynaklar"] else [],
                "odevler": json.loads(r["Odevler"]) if r["Odevler"] else [],
                "id": str(uuid.uuid4())
            })
        return migrate_data(students)
    except Exception as e:
        st.error(f"Öğrenci verisi yükleme hatası: {e}")
        return []

def save_data(data):
    try:
        sheet = SHEET_DB.worksheet("Ogrenciler")
        sheet.clear()
        sheet.append_row(["Ad", "Soyad", "TC", "Devre", "Koc", "Kaynaklar", "Odevler"])
        rows = []
        for s in data:
            rows.append([
                s.get("ad", ""),
                s.get("soyad", ""),
                str(s.get("tc", "")),
                s.get("devre", ""),
                s.get("koc", ""),
                json.dumps(s.get("kitaplar", []), ensure_ascii=False),
                json.dumps(s.get("odevler", []), ensure_ascii=False)
            ])
        if rows:
            sheet.append_rows(rows)
    except Exception as e:
        st.error(f"Öğrenci verisi kaydetme hatası: {e}")

def migrate_data(data):
    # Yeni yapıya göç: (Ad, Soyad, TC, Devre)
    for student in data:
        # Eski 'sinif' anahtarını 'devre'ye taşı
        if "sinif" in student and "devre" not in student:
            s_val = str(student.pop("sinif"))
            if not s_val.endswith(". Sınıf"):
                student["devre"] = f"{s_val}. Sınıf"
            else:
                student["devre"] = s_val
        
        # 'telefon' varsa 'tc'ye taşı veya default ata
        if "tc" not in student:
            student["tc"] = student.pop("telefon", "00000000000")
            
        # Ad ve Soyad ayrımı (Eğer sadece 'ad' varsa ve içinde boşluk varsa)
        if "soyad" not in student or not student["soyad"]:
            full_name = student.get("ad", "İsimsiz").split()
            if len(full_name) > 1:
                student["ad"] = " ".join(full_name[:-1])
                student["soyad"] = full_name[-1]
            else:
                student["ad"] = full_name[0] if full_name else "İsimsiz"
                student["soyad"] = "-"

        # Kitap yapısı kontrolü
        new_books = []
        for book in student.get("kitaplar", []):
            if isinstance(book, str):
                new_books.append({"ders": "Bilinmiyor", "kitap_adi": book, "konu_testleri": {}})
            else:
                new_books.append(book)
        student["kitaplar"] = new_books
        
        if "odevler" not in student:
            student["odevler"] = []
            
        # 'koc' alanı kontrolü
        if "koc" not in student:
            student["koc"] = "admin" # Eski verilere varsayılan koç ata
            
    return data

# --- APP CONFIG ---
st.set_page_config(page_title="Ortaokul Koçluk Sistemi", layout="wide")

# Initialize Session State
if 'students' not in st.session_state:
    st.session_state.students = load_data()
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# --- LOGIN KONTROLÜ ---
if not st.session_state.logged_in:
    login()
    st.stop()

# Giriş yapan koça göre öğrencileri filtrele
def get_filtered_students():
    if st.session_state.user_rol == "admin":
        return st.session_state.students
    return [s for s in st.session_state.students if s.get("koc") == st.session_state.user]

filtered_students = get_filtered_students()

# --- SIDEBAR ---
st.sidebar.title(f"🎓 {st.session_state.user}")
st.sidebar.write(f"Rol: {st.session_state.user_rol.capitalize()}")
if st.sidebar.button("Çıkış Yap"):
    st.session_state.logged_in = False
    st.rerun()

menu_options = ["Öğrenci Listesi", "Yeni Öğrenci Ekle", "Öğrenci Detayları", "Ayarlar / Yedekleme", "Hesap Ayarları"]
if st.session_state.user_rol == "admin":
    menu_options.append("Ayarlar / Koç Yönetimi")

menu = st.sidebar.radio("Menü", menu_options)

# --- SAYFALAR ---

if menu == "Öğrenci Listesi":
    st.header("📋 Kayıtlı Öğrenciler")
    if filtered_students:
        df = pd.DataFrame(filtered_students)
        display_cols = ['ad', 'soyad', 'tc', 'devre']
        df_display = df[display_cols]
        df_display.columns = ["Ad", "Soyad", "TC", "Devre"]
        search = st.text_input("TC veya İsim ile Ara...", "")
        if search:
            mask = (df_display["Ad"].str.contains(search, case=False) | 
                    df_display["Soyad"].str.contains(search, case=False) |
                    df_display["TC"].str.contains(search, case=False))
            df_display = df_display[mask]
        st.dataframe(df_display, use_container_width=True)
    else:
        st.info("Henüz kayıtlı öğrenci bulunmuyor.")

elif menu == "Yeni Öğrenci Ekle":
    st.header("👤 Yeni Öğrenci Kaydı")
    tab1, tab2 = st.tabs(["Manuel Ekle", "Excel ile Toplu Yükle"])
    with tab1:
        with st.form("manuel_form"):
            col1, col2 = st.columns(2)
            with col1:
                ad, soyad = st.text_input("Ad"), st.text_input("Soyad")
            with col2:
                tc = st.text_input("TC Kimlik No", max_chars=11)
                devre = st.selectbox("Devre", ["5. Sınıf", "6. Sınıf", "7. Sınıf", "8. Sınıf"])
            if st.form_submit_button("Kaydet"):
                if ad and soyad and tc:
                    ad_up = tr_upper(ad)
                    soyad_up = tr_upper(soyad)
                    st.session_state.students.append({
                        "id": str(uuid.uuid4()), 
                        "ad": ad_up, "soyad": soyad_up, 
                        "tc": tc, "devre": devre, 
                        "koc": st.session_state.user, # Koç otomatik atanır
                        "kitaplar": [], "odevler": []
                    })
                    save_data(st.session_state.students)
                    st.success(f"{ad_up} {soyad_up} ({devre}) kaydedildi!")
    with tab2:
        st.info("Excel dosyanızda şu başlıklar bulunmalıdır: **Ad, Soyad, TC, Devre**")
        uploaded_file = st.file_uploader("Excel Dosyası Seçin", type=["xlsx"])
        if uploaded_file and st.button("Verileri İçe Aktar"):
            try:
                df_excel = pd.read_excel(uploaded_file)
                # Sütun isimlerini normalize et (Büyük-küçük harf duyarlılığını azaltmak için)
                df_excel.columns = [c.strip().title() for c in df_excel.columns]
                
                required_cols = ["Ad", "Soyad", "Tc", "Devre"]
                if not all(col in df_excel.columns for col in required_cols):
                    st.error(f"Eksik sütunlar mevcut. Gerekli sütunlar: {', '.join(required_cols)}")
                else:
                    count = 0
                    for _, row in df_excel.iterrows():
                        d_val = str(row["Devre"])
                        if not d_val.endswith(". Sınıf"):
                            d_val = f"{d_val}. Sınıf"
                            
                        st.session_state.students.append({
                            "id": str(uuid.uuid4()), 
                            "ad": tr_upper(str(row["Ad"])), 
                            "soyad": tr_upper(str(row["Soyad"])), 
                            "tc": str(row["Tc"]), # pandas sütun adını 'Tc' olarak normalize ettik
                            "devre": d_val, 
                            "koc": st.session_state.user, # Koç otomatik atanır
                            "kitaplar": [], "odevler": []
                        })
                        count += 1
                    save_data(st.session_state.students)
                    st.success(f"{count} öğrenci başarıyla aktarıldı!")
            except Exception as e:
                st.error(f"Excel okuma hatası: {e}")

elif menu == "Öğrenci Detayları":
    st.header("🔍 Öğrenci Detayları")
    if not filtered_students:
        st.warning("Kayıtlı öğrenciniz yok.")
    else:
        student_list = [f"{s['ad']} {s['soyad']} ({s['tc']})" for s in filtered_students]
        selected_label = st.selectbox("Öğrenci Seçin", student_list)
        student = filtered_students[student_list.index(selected_label)]
        
        st.info(f"🎓 **Öğrenci:** {student['ad']} {student['soyad']} | **Devre:** {student['devre']} | **TC:** {student['tc']}")
        
        tab_books, tab_homework = st.tabs(["📚 Kaynak Kitaplar", "📝 Ödev Atama"])
        
        # Öğrencinin devresine göre müfredat derslerini belirle
        ogrenci_devre = student['devre']
        mufredat_dersleri = list(MUFREDAT.get(ogrenci_devre, {}).keys())
        
        with tab_books:
            with st.form("book_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1: b_ders = st.selectbox("Ders", mufredat_dersleri, key="add_book_ders")
                with col2: b_name = st.text_input("Kitap Adı", key="add_book_name")
                if st.form_submit_button("Kitabı Ekle") and b_name:
                    student["kitaplar"].append({"ders": b_ders, "kitap_adi": b_name, "konu_testleri": {}})
                    save_data(st.session_state.students); st.success(f"'{b_name}' eklendi.")
            
            st.subheader("Mevcut Kitaplar")
            if 'deleting_book_idx' in st.session_state and st.session_state.deleting_book_idx is not None:
                idx = st.session_state.deleting_book_idx
                st.warning(f"⚠️ '{student['kitaplar'][idx]['kitap_adi']}' silinsin mi?")
                col_y, col_n = st.columns(2)
                if col_y.button("Evet, Sil"):
                    student["kitaplar"].pop(idx)
                    save_data(st.session_state.students); st.session_state.deleting_book_idx = None; st.rerun()
                if col_n.button("İptal"): st.session_state.deleting_book_idx = None; st.rerun()
            else:
                for i, b in enumerate(student["kitaplar"]):
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"**[{b['ders']}]** {b['kitap_adi']}")
                    if c2.button("Sil", key=f"del_book_{i}"): st.session_state.deleting_book_idx = i; st.rerun()

        with tab_homework:
            st.subheader("Yeni Ödev Tanımla")
            if not mufredat_dersleri:
                st.error("Bu öğrencinin devresi için müfredat bulunamadı.")
            else:
                col1, col2 = st.columns(2)
                with col1:
                    h_ders = st.selectbox("Ders Seçin", mufredat_dersleri, key=f"hw_ders_{student['id']}")
                    h_konu = st.selectbox("Konu Seçin", MUFREDAT[ogrenci_devre][h_ders], key=f"hw_konu_{student['id']}_{h_ders}")
                
                with col2:
                    relevant_books = [b for b in student["kitaplar"] if b["ders"] == h_ders]
                    if not relevant_books:
                        st.warning(f"Bu ders için ({h_ders}) henüz kitap eklenmemiş.")
                        h_kitap_name = None
                    else:
                        h_kitap_name = st.selectbox("Kitap Seçin", [b["kitap_adi"] for b in relevant_books], key=f"hw_kitap_{student['id']}_{h_ders}")
                    h_date = st.date_input("Teslim Tarihi", datetime.now(), key=f"hw_date_{student['id']}")

                if h_kitap_name:
                    book_obj = next(b for b in relevant_books if b["kitap_adi"] == h_kitap_name)
                    total_tests = book_obj["konu_testleri"].get(h_konu, 0)
                    
                    if total_tests == 0:
                        st.info(f"'{h_kitap_name}' kitabında '{h_konu}' konusu için test sayısı tanımlanmamış.")
                        new_total = st.number_input(f"Toplam Test Sayısı ({h_konu})", min_value=1, value=10, key=f"total_input_{student['id']}_{h_kitap_name}_{h_konu}")
                        if st.button("Test Sayısını Kaydet ve Devam Et", key=f"save_total_{student['id']}"):
                            book_obj["konu_testleri"][h_konu] = int(new_total)
                            save_data(st.session_state.students); st.success("Test sayısı kaydedildi!"); st.rerun()
                    else:
                        st.write(f"📊 **Konu Bilgisi:** Toplam **{total_tests}** test var.")
                        c3, c4 = st.columns(2)
                        start_t = c3.number_input("Başlangıç Test No", min_value=1, max_value=total_tests, value=1, key=f"start_{student['id']}")
                        end_t = c4.number_input("Bitiş Test No", min_value=1, max_value=total_tests, value=1, key=f"end_{student['id']}")
                        
                        if st.button("🚀 Ödevi Kaydet", key=f"hw_save_btn_{student['id']}"):
                            if end_t < start_t:
                                st.error("❌ Hata: Bitiş başlangıçtan küçük olamaz!")
                            else:
                                detay = f"Test {int(start_t)}-{int(end_t)}"
                                duplicate = any(hw["ders"] == h_ders and hw["konu"] == h_konu and hw["kaynak"] == h_kitap_name and hw["detay"] == detay for hw in student["odevler"])
                                if duplicate:
                                    st.warning(f"⚠️ Bu ödev ({detay}) zaten atanmış.")
                                else:
                                    student["odevler"].append({
                                        "id": str(uuid.uuid4()), "ders": h_ders, "konu": h_konu, 
                                        "kaynak": h_kitap_name, "detay": detay, 
                                        "tarih": h_date.strftime("%Y-%m-%d"), "tamamlandi": False
                                    })
                                    save_data(st.session_state.students); st.success("✅ Ödev atandı!"); st.rerun()
                else: st.info("Ödev atamak için bu derse bir kitap eklemelisiniz.")

            st.divider()
            c_t, c_p = st.columns([3, 1])
            c_t.subheader("📌 Ödev Takip Listesi")
            pdf_data = create_homework_pdf(student, student["odevler"])
            c_p.download_button(label="📄 PDF İndir", data=pdf_data, file_name=f"{student['ad']}_{student['soyad']}_odev.pdf", mime="application/pdf")
            
            for i, hw in enumerate(student["odevler"]):
                co1, co2, co3 = st.columns([1, 6, 2])
                if co1.checkbox("", value=hw["tamamlandi"], key=f"ch_{hw['id']}") != hw["tamamlandi"]:
                    student["odevler"][i]["tamamlandi"] = not hw["tamamlandi"]; save_data(st.session_state.students); st.rerun()
                co2.write(f"{status} **{hw['ders']}** - {hw['konu']} ({hw['kaynak']}: {hw['detay']})")
                co3.write(f"📅 {hw['tarih']}")

elif menu == "Ayarlar / Yedekleme":
    st.header("⚙️ Ayarlar ve Yedekleme")
    st.subheader("📥 Veri Yedekle")
    # Mevcut session state'i JSON formatında indir
    backup_json = json.dumps(st.session_state.students, ensure_ascii=False, indent=4)
    st.download_button(label="JSON Yedeği İndir", data=backup_json, file_name=f"yedek_students_{datetime.now().strftime('%Y%m%d_%H%M')}.json", mime="application/json")
    
    st.divider()
    st.subheader("📤 Yedek Yükle")
    uploaded_backup = st.file_uploader("JSON Dosyası Seçin", type=["json"])
    if uploaded_backup:
        try:
            backup_data = json.load(uploaded_backup)
            if isinstance(backup_data, list):
                if st.button("Yedeği Geri Yükle (Mevcut Veriler Silinir!)"):
                    st.session_state.students = migrate_data(backup_data)
                    save_data(st.session_state.students)
                    st.success("Yedek başarıyla yüklendi!")
                    st.rerun()
            else: st.error("Geçersiz yedek dosyası yapısı.")
        except Exception as e: st.error(f"Hata: {e}")

elif menu == "Ayarlar / Koç Yönetimi" and st.session_state.user_rol == "admin":
    st.header("👥 Koç ve Kullanıcı Yönetimi")
    users = load_users()
    
    tab_list, tab_add = st.tabs(["Kullanıcı Listesi", "Yeni Koç Ekle"])
    
    with tab_list:
        df_users = pd.DataFrame(users)
        st.table(df_users[["kullanici_adi", "rol"]])
        
        st.divider()
        st.subheader("Kullanıcı Sil")
        to_delete = st.selectbox("Silinecek Kullanıcıyı Seçin", [u["kullanici_adi"] for u in users if u["kullanici_adi"] != st.session_state.user])
        if st.button("Seçili Kullanıcıyı Sil"):
            if to_delete == "admin" and len([u for u in users if u["rol"] == "admin"]) == 1:
                st.error("Sistemdeki son admini silemezsiniz!")
            else:
                users = [u for u in users if u["kullanici_adi"] != to_delete]
                save_users(users)
                st.success(f"'{to_delete}' başarıyla silindi.")
                st.rerun()

    with tab_add:
        with st.form("add_user_form"):
            oc_name = st.text_input("Koç Adı Soyadı (Örn: Ayşe Yılmaz)")
            if st.form_submit_button("🚀 Otomatik Oluştur ve Kaydet"):
                if oc_name:
                    # 1. Kullanıcı Adı Üretimi
                    base_username = slugify_tr(oc_name)
                    final_username = base_username
                    
                    # 2. Çakışma Kontrolü
                    if any(u["kullanici_adi"] == final_username for u in users):
                        suffix = random.randint(10, 99)
                        final_username = f"{base_username}_{suffix}"
                    
                    # 3. Şifre Üretimi
                    gen_pass = str(random.randint(100000, 999999))
                    
                    # 4. Kayıt
                    users.append({
                        "kullanici_adi": final_username, 
                        "sifre": gen_pass, 
                        "rol": "koc",
                        "gercek_ad": oc_name # Opsiyonel: Gerçek adı da saklayalım
                    })
                    save_users(users)
                    
                    # 5. Başarı Mesajı
                    st.success("✅ Kayıt Başarılı!")
                    st.code(f"Koç Adı: {oc_name}\nKullanıcı Adı: {final_username}\nŞifre: {gen_pass}", language="text")
                    st.info("⚠️ Lütfen bu bilgileri koç ile paylaşın. Şifre bir daha görüntülenemez.")
                    # st.rerun() # Rerun yapmıyoruz ki kullanıcı bilgileri görebilsin
                else:
                    st.warning("Lütfen koçun adını ve soyadını girin.")

elif menu == "Hesap Ayarları":
    st.header("👤 Hesap Ayarları")
    st.subheader("Şifre Değiştir")
    
    with st.form("password_change_form"):
        old_pass = st.text_input("Mevcut Şifre", type="password")
        new_pass = st.text_input("Yeni Şifre", type="password")
        confirm_pass = st.text_input("Yeni Şifre (Tekrar)", type="password")
        
        if st.form_submit_button("Şifreyi Güncelle"):
            users = load_users()
            current_user_obj = next((u for u in users if u["kullanici_adi"] == st.session_state.user), None)
            
            if not (old_pass and new_pass and confirm_pass):
                st.warning("Lütfen tüm alanları doldurun.")
            elif old_pass != current_user_obj["sifre"]:
                st.error("Mevcut şifre hatalı!")
            elif new_pass != confirm_pass:
                st.error("Yeni şifreler eşleşmiyor!")
            elif len(new_pass) < 4:
                st.error("Yeni şifre en az 4 karakter olmalıdır!")
            else:
                # Şifreyi güncelle
                for u in users:
                    if u["kullanici_adi"] == st.session_state.user:
                        u["sifre"] = new_pass
                        break
                save_users(users)
                st.success("Şifreniz başarıyla güncellendi!")

import streamlit as st
import streamlit.components.v1 as components
import google.generativeai as genai
from groq import Groq
import json
import re
import time 
import requests
from requests.auth import HTTPBasicAuth
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from PIL import Image
import io

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="SwissWelle V79",
    page_icon="✍️",
    layout="wide"
)

# --- CSS (High Contrast & Stability) ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #fff; }
    .stTextInput>div>div>input { background-color: #262730; color: white; }
    .stTextArea>div>div>textarea { background-color: #262730; color: white; }
    
    /* Content Preview Box - Always White/Black */
    .preview-container {
        background-color: #ffffff !important;
        color: #000000 !important;
        padding: 30px;
        border-radius: 8px;
        border: 1px solid #ddd;
    }
</style>
""", unsafe_allow_html=True)

# --- SECRETS ---
def get_secret(key): return st.secrets.get(key, "")

# --- SESSION STATE ---
if 'data_store' not in st.session_state:
    st.session_state.data_store = {
        'images': [],
        'context': "",
        'p_name': "",
        'seo_data': {},
        'lsi_keys': []
    }

# --- FUNCTIONS ---

# 1. ROBUST SCRAPER (Memory Safe)
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def scrape_data(url):
    driver = None
    text = ""
    imgs = []
    status = "Done"
    
    try:
        driver = get_driver()
        driver.set_page_load_timeout(30)
        driver.get(url)
        time.sleep(3) # Wait for JS
        
        # A. GET TEXT (Body)
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            text = body.text[:8000] # Limit char count
        except: text = ""

        # B. GET IMAGES
        elements = driver.find_elements(By.TAG_NAME, "img")
        for e in elements:
            src = e.get_attribute("src")
            if src and src.startswith("http"):
                if not any(x in src for x in ['icon', 'logo', 'gif', 'svg', '1x1', 'pixel']):
                    if "aliexpress" in url: src = src.split('_')[0]
                    else: src = src.split('?')[0]
                    imgs.append(src)
        
        imgs = list(set(imgs)) # Remove duplicates
        
    except Exception as e:
        status = f"Error: {str(e)}"
    finally:
        if driver:
            driver.quit() # CRITICAL: Close browser to save RAM
    
    return status, text, imgs

# 2. AI CONTENT WRITER (Long Form Logic)
def run_ai(provider, api_key, p_name, context):
    prompt = f"""
    Du bist ein professioneller, deutscher Content Writer für 'SwissWelle.ch' (E-Commerce, Boho-Chic Nische).
    
    INPUT:
    - Produkt: "{p_name}"
    - Kontext-Daten: \"\"\"{context[:10000]}\"\"\"
    
    AUFGABE:
    Schreibe eine **ausführliche** (400-500 Wörter), SEO-optimierte Produktbeschreibung.
    
    STRUKTUR & INHALT (Muss exakt befolgt werden):
    1. **SEO Title**: Catchy, inkl. Keywords.
    2. **Einleitung (100+ Wörter)**: Emotionales Storytelling. Wie fühlt sich das Produkt an? Warum braucht man es?
    3. **Features (Bullet Points)**: 5-6 wichtige Punkte.
    4. **Vorteile im Detail (150+ Wörter)**: Beschreibe den Nutzen (Comfort, Style, Langlebigkeit).
    5. **Spezifikationen (HTML Tabelle)**: Erstelle eine Tabelle mit Material, Maße, Farbe, Pflege. (Nimm Daten aus Kontext, erfinde nichts Falsches).
    6. **Fazit & CTA**: Kaufaufforderung.
    
    IMAGE SEO:
    - Erstelle 10 deutsche LSI-Keywords (z.B. "makramee-wandbehang-gross", "boho-deko-wohnzimmer") für die Bildbenennung.
    
    FORMAT (JSON):
    {{
        "seo_title": "...",
        "meta_description": "...",
        "html_content": "<h1>...</h1><p>...</p>...",
        "lsi_keywords": ["kw1", "kw2"...]
    }}
    """
    
    try:
        if provider == "Groq":
            client = Groq(api_key=api_key)
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
        else:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(res.text)
    except Exception as e:
        return {"error": str(e)}

# 3. UPLOAD & OPTIMIZE
def upload_image(item, keyword, wp_url, user, password):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        clean_key = re.sub(r'[^a-zA-Z0-9-]', '', keyword.lower().replace(" ", "-"))
        filename = f"{clean_key}.jpg"
        
        buf = io.BytesIO()
        if item['type'] == 'file':
            img = Image.open(item['data'])
        else:
            r = requests.get(item['data'], timeout=10)
            img = Image.open(io.BytesIO(r.content))
            
        img = img.convert('RGB')
        img.save(buf, format='JPEG', quality=85, optimize=True)
        
        headers = {'Content-Disposition': f'attachment; filename={filename}', 'Content-Type': 'image/jpeg'}
        res = requests.post(api_url, data=buf.getvalue(), headers=headers, auth=HTTPBasicAuth(user, password))
        
        if res.status_code == 201:
            pid = res.json()['id']
            requests.post(f"{api_url}/{pid}", json={"alt_text": keyword, "title": keyword}, auth=HTTPBasicAuth(user, password))
            return pid
    except: return None
    return None

def publish_wc(data, img_ids, feat_id, wp_url, ck, cs):
    imgs = [{"id": feat_id}] + [{"id": i} for i in img_ids if i != feat_id]
    payload = {
        "name": data['seo_title'],
        "description": data['html_content'],
        "short_description": data['meta_description'],
        "status": "draft",
        "type": "simple",
        "images": imgs,
        "meta_data": [{"key": "rank_math_focus_keyword", "value": data['seo_title']}]
    }
    return requests.post(f"{wp_url}/wp-json/wc/v3/products", auth=HTTPBasicAuth(ck, cs), json=payload)

# --- UI START ---
# SIDEBAR
with st.sidebar:
    st.header("⚙️ Settings")
    if st.button("🧹 New Post"):
        st.session_state.data_store = {'images': [], 'context': "", 'p_name': "", 'seo_data': {}, 'lsi_keys': []}
        st.rerun()
    
    provider = st.radio("AI Provider", ["Groq", "Gemini"])
    if provider == "Groq": key = st.text_input("Groq Key", value=get_secret("groq_api_key"), type="password")
    else: key = st.text_input("Gemini Key", value=get_secret("gemini_api_key"), type="password")

st.title("🌿 SwissWelle V79 (Content Pro)")

# 1. IDENTITY & SCRAPE
c1, c2 = st.columns([1, 2])
with c1:
    st.session_state.data_store['p_name'] = st.text_input("Product Name (Primary Keyword)", value=st.session_state.data_store['p_name'])
with c2:
    scrape_url_input = st.text_input("Scrape URL (Amazon/Ali)")
    if st.button("🔍 Get Data"):
        if scrape_url_input:
            with st.spinner("Scraping..."):
                stat, txt, imgs = scrape_data(scrape_url_input)
                st.session_state.data_store['context'] += f"\nSOURCE: {txt}"
                for i in imgs: st.session_state.data_store['images'].append({'type': 'url', 'data': i})
                st.success(f"Extracted {len(imgs)} images & {len(txt)} chars text.")
                st.rerun()

# 2. MEDIA & CONTEXT
c_media, c_text = st.columns(2)

with c_media:
    st.markdown("### 🖼️ Images")
    # File Upload
    upl = st.file_uploader("Upload Files", accept_multiple_files=True)
    if upl:
        for f in upl:
            if not any(x['data'].name == f.name for x in st.session_state.data_store['images'] if x['type'] == 'file'):
                st.session_state.data_store['images'].append({'type': 'file', 'data': f})
    
    # Image Link Input (User Requested)
    img_link_input = st.text_area("Paste Image Links (One per line)", height=100)
    if st.button("Add Image Links"):
        if img_link_input:
            links = img_link_input.split('\n')
            for l in links:
                if l.strip(): st.session_state.data_store['images'].append({'type': 'url', 'data': l.strip()})
            st.rerun()

with c_text:
    st.markdown("### 📝 Context / Description")
    st.caption("AI will use this text. If scraping failed, PASTE details here.")
    manual_txt = st.text_area("Product Details", height=250, value=st.session_state.data_store['context'])
    st.session_state.data_store['context'] = manual_txt

# 3. REVIEW IMAGES
if st.session_state.data_store['images']:
    st.divider()
    cols = st.columns(6)
    for i, img in enumerate(st.session_state.data_store['images']):
        with cols[i % 6]:
            if img['type'] == 'file': st.image(img['data'], use_container_width=True)
            else: st.image(img['data'], use_container_width=True)
            if st.button("❌", key=f"del_{i}"):
                st.session_state.data_store['images'].pop(i)
                st.rerun()

# 4. GENERATE & PREVIEW
st.divider()

if st.button("🪄 Write Long-Form Content (400+ Words)", type="primary"):
    if not key or not st.session_state.data_store['p_name']:
        st.error("Name & Key required!")
    else:
        with st.spinner("Writing detailed content..."):
            res = run_ai(provider, key, st.session_state.data_store['p_name'], st.session_state.data_store['context'])
            if "error" in res: st.error(res['error'])
            else:
                st.session_state.data_store['seo_data'] = res
                st.session_state.data_store['lsi_keys'] = res.get('lsi_keywords', [])
                st.rerun()

if st.session_state.data_store.get('seo_data'):
    data = st.session_state.data_store['seo_data']
    
    # PREVIEW BOX (White BG forced)
    st.subheader("👁️ Content Preview")
    html_preview = f"""
    <div style="background-color: white; color: black; padding: 30px; border-radius: 10px; font-family: sans-serif; line-height: 1.6;">
        <h1 style="color: #2c3e50;">{data.get('seo_title', 'Title')}</h1>
        <p><strong>Meta:</strong> {data.get('meta_description', '')}</p>
        <hr style="border: 1px solid #ccc;">
        {data.get('html_content', '')}
    </div>
    """
    components.html(html_preview, height=600, scrolling=True)
    
    # PUBLISH SECTION
    st.divider()
    c_pub, c_stat = st.columns([1, 2])
    with c_pub:
        total_imgs = len(st.session_state.data_store['images'])
        feat_idx = st.number_input("Featured Image #", 1, total_imgs if total_imgs > 0 else 1, 1) - 1
        
        if st.button("📤 Publish to Site"):
            status = st.status("Processing...")
            lsi = st.session_state.data_store['lsi_keys']
            if not lsi: lsi = [st.session_state.data_store['p_name']]
            
            uploaded_ids = []
            for i, img in enumerate(st.session_state.data_store['images']):
                kw = lsi[i % len(lsi)]
                if i >= len(lsi): kw += f"-{i}"
                status.write(f"Uploading: {kw}.jpg")
                pid = upload_image(img, kw, get_secret("wp_url"), get_secret("wp_user"), get_secret("wp_app_pass"))
                if pid: uploaded_ids.append(pid)
            
            if uploaded_ids:
                fid = uploaded_ids[feat_idx] if feat_idx < len(uploaded_ids) else uploaded_ids[0]
                res = publish_wc(data, uploaded_ids, fid, get_secret("wp_url"), get_secret("wc_ck"), get_secret("wc_cs"))
                if res.status_code == 201:
                    status.update(label="Done!", state="complete")
                    st.success("Published Successfully!")
                    st.markdown(f"[View Product]({res.json()['permalink']})")
                else:
                    status.update(label="Error", state="error")
                    st.error(res.text)
            else:
                status.update(label="Upload Failed", state="error")

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
    page_title="SwissWelle V78",
    page_icon="🛡️",
    layout="wide"
)

# --- CSS (Minimal & Clean) ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #fff; }
    .block-container { padding-top: 2rem; }
    .stButton>button { width: 100%; border-radius: 6px; font-weight: bold; }
    div[data-testid="stImage"] { border: 1px solid #444; border-radius: 6px; }
    .success-box { padding: 10px; background: #06402b; border-radius: 5px; color: #00ff00; }
</style>
""", unsafe_allow_html=True)

# --- SECRETS ---
def get_secret(key): return st.secrets.get(key, "")

# --- STATE MANAGEMENT ---
if 'data_store' not in st.session_state:
    st.session_state.data_store = {
        'images': [],      # List of dicts: {'type': 'url'/'file', 'data': ...}
        'context': "",     # Scraped text
        'p_name': "",
        'seo_data': {},    # Holds generated title, desc, html
        'lsi_keys': []     # Holds LSI keywords
    }

# --- FUNCTIONS ---

# 1. LIGHTWEIGHT SCRAPER
@st.cache_resource
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu") # Save Memory
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def scrape_data(url):
    driver = get_driver()
    text = ""
    imgs = []
    status = "Done"
    
    try:
        driver.get(url)
        time.sleep(2) # Minimal wait
        
        # A. GET TEXT
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            text = body.text[:6000] # Limit to prevent crash
        except: text = "Text scrape failed."

        # B. GET IMAGES
        elements = driver.find_elements(By.TAG_NAME, "img")
        for e in elements:
            src = e.get_attribute("src")
            if src and src.startswith("http"):
                if not any(x in src for x in ['icon', 'logo', 'gif', 'svg', '1x1']):
                    if "aliexpress" in url: src = src.split('_')[0]
                    else: src = src.split('?')[0]
                    imgs.append(src)
        
        # Unique images only
        imgs = list(set(imgs))
        
    except Exception as e:
        status = f"Error: {str(e)}"
    
    return status, text, imgs

# 2. AI GENERATOR (SAFE MODE)
def run_ai(provider, api_key, p_name, context):
    # Truncate context to avoid token overflow/crash
    safe_context = context[:8000] 
    
    prompt = f"""
    Rolle: Deutscher SEO Copywriter für 'SwissWelle.ch' (Boho-Chic).
    
    INPUT:
    - Produkt: "{p_name}"
    - Daten: \"\"\"{safe_context}\"\"\"
    
    AUFGABE:
    Erstelle ein JSON mit Beschreibung & LSI Keywords.
    
    REGELN:
    1. Nutze NUR Fakten aus den Daten (Material, Maße). Erfinde nichts.
    2. Generiere 8-10 deutsche LSI Keywords für Bilder (z.B. 'makramee-wandbehang-gross').
    
    JSON FORMAT:
    {{
        "seo_title": "...",
        "meta_description": "...",
        "html_content": "HTML (<h2>, <ul>, <table>)...",
        "lsi_keywords": ["kw1", "kw2", "kw3"]
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
        # Sanitize filename
        clean_key = re.sub(r'[^a-zA-Z0-9-]', '', keyword.lower().replace(" ", "-"))
        filename = f"{clean_key}.jpg"
        
        # Optimize Image
        buf = io.BytesIO()
        if item['type'] == 'file':
            img = Image.open(item['data'])
        else:
            r = requests.get(item['data'], timeout=10)
            img = Image.open(io.BytesIO(r.content))
            
        img = img.convert('RGB')
        img.save(buf, format='JPEG', quality=80, optimize=True) # Optimized
        
        # Upload
        headers = {'Content-Disposition': f'attachment; filename={filename}', 'Content-Type': 'image/jpeg'}
        res = requests.post(api_url, data=buf.getvalue(), headers=headers, auth=HTTPBasicAuth(user, password))
        
        if res.status_code == 201:
            pid = res.json()['id']
            # Set SEO Meta
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
        "meta_data": [
            {"key": "rank_math_focus_keyword", "value": data['seo_title']}
        ]
    }
    return requests.post(f"{wp_url}/wp-json/wc/v3/products", auth=HTTPBasicAuth(ck, cs), json=payload)

# --- MAIN UI ---

# SIDEBAR
with st.sidebar:
    st.header("⚙️ Settings")
    if st.button("🧹 Clear / New"):
        st.session_state.data_store = {'images': [], 'context': "", 'p_name': "", 'seo_data': {}, 'lsi_keys': []}
        st.rerun()
        
    provider = st.radio("AI Provider", ["Groq", "Gemini"])
    if provider == "Groq": key = st.text_input("Groq Key", value=get_secret("groq_api_key"), type="password")
    else: key = st.text_input("Gemini Key", value=get_secret("gemini_api_key"), type="password")

# APP CONTENT
st.title("🌿 SwissWelle V78 (Stable)")

# 1. IDENTITY & SCRAPE
st.subheader("1. Source Data")
col_name, col_url = st.columns([1, 2])
with col_name:
    st.session_state.data_store['p_name'] = st.text_input("Product Name", value=st.session_state.data_store['p_name'])
with col_url:
    scrape_url_input = st.text_input("Reference URL (Amazon/Ali/Walmart)")
    if st.button("🔍 Scrape & Get Data"):
        if scrape_url_input:
            with st.spinner("Scraping..."):
                stat, txt, imgs = scrape_data(scrape_url_input)
                st.session_state.data_store['context'] += f"\nSOURCE ({stat}):\n{txt}"
                for i in imgs:
                    st.session_state.data_store['images'].append({'type': 'url', 'data': i})
                st.success(f"Found {len(imgs)} images. Text length: {len(txt)}")
                st.rerun()

# 2. MANUAL MEDIA & TEXT (SIDE BY SIDE)
st.subheader("2. Add Media & Details")
c1, c2 = st.columns(2)

with c1:
    st.markdown("**📂 Upload / Image Links**")
    # File Upload
    upl = st.file_uploader("Upload Files", accept_multiple_files=True)
    if upl:
        for f in upl:
            # Check duplicates
            if not any(x['data'].name == f.name for x in st.session_state.data_store['images'] if x['type'] == 'file'):
                st.session_state.data_store['images'].append({'type': 'file', 'data': f})
    
    # URL Input (Next to Upload)
    img_urls = st.text_area("Or Paste Image URLs (One per line)", height=100)
    if st.button("Add Image URLs"):
        if img_urls:
            urls = img_urls.split('\n')
            for u in urls:
                if u.strip(): st.session_state.data_store['images'].append({'type': 'url', 'data': u.strip()})
            st.rerun()

with c2:
    st.markdown("**📝 Manual Description**")
    manual_txt = st.text_area("Paste product details here if scrape failed", height=200, value=st.session_state.data_store['context'])
    st.session_state.data_store['context'] = manual_txt

# 3. REVIEW IMAGES
if st.session_state.data_store['images']:
    st.divider()
    st.write(f"**Total Images: {len(st.session_state.data_store['images'])}**")
    cols = st.columns(6)
    for i, img in enumerate(st.session_state.data_store['images']):
        with cols[i % 6]:
            if img['type'] == 'file': st.image(img['data'], use_container_width=True)
            else: st.image(img['data'], use_container_width=True)
            if st.button("❌", key=f"del_{i}"):
                st.session_state.data_store['images'].pop(i)
                st.rerun()

# 4. GENERATE & PUBLISH
st.divider()
ac1, ac2 = st.columns(2)

with ac1:
    if st.button("🪄 Generate Content + LSI", type="primary"):
        if not key or not st.session_state.data_store['p_name']:
            st.error("Name & Key required!")
        else:
            with st.spinner("Generating..."):
                res = run_ai(provider, key, st.session_state.data_store['p_name'], st.session_state.data_store['context'])
                if "error" in res: st.error(res['error'])
                else:
                    st.session_state.data_store['seo_data'] = res
                    st.session_state.data_store['lsi_keys'] = res.get('lsi_keywords', [])
                    st.rerun()

    # PREVIEW
    if st.session_state.data_store.get('seo_data'):
        data = st.session_state.data_store['seo_data']
        st.markdown("---")
        st.markdown(f"### {data.get('seo_title')}")
        st.info(f"LSI Keys: {st.session_state.data_store['lsi_keys']}")
        components.html(data.get('html_content', ''), height=400, scrolling=True)

with ac2:
    if st.session_state.data_store.get('seo_data'):
        total_imgs = len(st.session_state.data_store['images'])
        feat_idx = st.number_input("Featured Image #", 1, total_imgs if total_imgs > 0 else 1, 1) - 1
        
        if st.button("📤 Publish to WordPress"):
            status = st.status("Publishing...")
            
            # Keywords
            lsi = st.session_state.data_store['lsi_keys']
            if not lsi: lsi = [st.session_state.data_store['p_name']]
            
            uploaded_ids = []
            
            # Upload Loop
            for i, img in enumerate(st.session_state.data_store['images']):
                kw = lsi[i % len(lsi)]
                if i >= len(lsi): kw += f"-{i}"
                
                status.write(f"Uploading Img #{i+1} as {kw}.jpg...")
                pid = upload_image(img, kw, get_secret("wp_url"), get_secret("wp_user"), get_secret("wp_app_pass"))
                if pid: uploaded_ids.append(pid)
            
            if uploaded_ids:
                # Determine Featured ID
                fid = uploaded_ids[feat_idx] if feat_idx < len(uploaded_ids) else uploaded_ids[0]
                
                status.write("Creating Product...")
                res = publish_wc(st.session_state.data_store['seo_data'], uploaded_ids, fid, get_secret("wp_url"), get_secret("wc_ck"), get_secret("wc_cs"))
                
                if res.status_code == 201:
                    status.update(label="Success!", state="complete")
                    st.balloons()
                    st.success("✅ Published!")
                    st.markdown(f"[View Product]({res.json()['permalink']})")
                else:
                    status.update(label="Error", state="error")
                    st.error(res.text)
            else:
                status.update(label="Failed", state="error")
                st.error("Image upload failed.")

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
from PIL import Image
import io

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="SwissWelle Admin",
    page_icon="🌿",
    layout="wide"
)

# --- SECRETS ---
def get_secret(key): return st.secrets.get(key, "")

# --- SESSION STATE ---
if 'final_images' not in st.session_state: st.session_state.final_images = []
if 'p_name' not in st.session_state: st.session_state.p_name = ""
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'seo_title' not in st.session_state: st.session_state.seo_title = ""
if 'generated' not in st.session_state: st.session_state.generated = False

# --- FUNCTIONS ---

# 1. Scraper
@st.cache_resource
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def scrape_images(url):
    driver = get_driver()
    candidates = set()
    title = ""
    try:
        driver.get(url)
        time.sleep(2)
        title = driver.title.split('|')[0].strip()
        if "login" in title.lower() or "security" in title.lower(): title = ""
        
        page_source = driver.page_source
        matches = re.findall(r'(https?://[^"\s\'>]+?\.alicdn\.com/[^"\s\'>]+?\.(?:jpg|jpeg|png|webp))', page_source)
        for m in matches:
            m = m.split('?')[0]
            if '32x32' not in m and '50x50' not in m and 'search' not in m:
                candidates.add(m)
    except: pass
    return title, list(candidates)

# 2. Content Generator
def generate_content(provider, api_key, p_name):
    prompt = f"""
    Du bist ein erfahrener deutscher Senior Content Writer für 'SwissWelle.ch'. 
    Unsere Nische: Boho-Chic, Makramee, Nachhaltige Wohnkultur.
    
    PRODUKT: {p_name}
    
    AUFGABE:
    Schreibe eine hochkonvertierende, SEO-optimierte Produktbeschreibung in HTML.
    
    ANFORDERUNGEN:
    1. **Tonalität**: Professionell, Emotional, Boho-Vibe.
    2. **Struktur**:
       - **SEO Titel**: Catchy & Relevant.
       - **Intro**: Emotionaler Hook.
       - **Spezifikationen (Tabelle)**: Erstelle eine HTML Tabelle (<table>) mit: Material, Stil, Maße (schätzen wenn nicht bekannt), Farbe.
       - **Features**: Bullet Points (<ul>).
       - **CTA**: Kaufaufruf.
    3. **Format**: Nutze <h2>, <ul>, <p>, <table>. KEINE <html> Tags.
    
    OUTPUT FORMAT (JSON):
    {{
        "seo_title": "...",
        "meta_description": "...",
        "html_content": "..."
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
            
        elif provider == "Gemini":
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
            
    except Exception as e:
        return {"error": str(e)}

# 3. Uploader
def upload_to_wp(item, p_name, wp_url, user, password):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        clean_name = re.sub(r'[^a-zA-Z0-9]', '-', p_name).lower()
        filename = f"{clean_name}-{int(time.time())}.jpg"
        
        if item['type'] == 'file':
            img_byte_arr = io.BytesIO()
            image = Image.open(item['data'])
            image = image.convert('RGB')
            image.save(img_byte_arr, format='JPEG', quality=85)
            img_data = img_byte_arr.getvalue()
        else:
            r = requests.get(item['data'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code != 200: return None
            img_data = r.content

        headers = {'Content-Disposition': f'attachment; filename={filename}','Content-Type': 'image/jpeg'}
        res = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password))
        
        if res.status_code == 201:
            pid = res.json()['id']
            requests.post(f"{api_url}/{pid}", json={"alt_text": p_name, "title": p_name}, auth=HTTPBasicAuth(user, password))
            return pid
    except: return None
    return None

def publish_product(p_data, image_ids, feat_id, wp_url, ck, cs):
    final_images = [{"id": feat_id}] + [{"id": i} for i in image_ids if i != feat_id]
    payload = {
        "name": p_data['seo_title'],
        "description": p_data['html_content'],
        "short_description": p_data['meta_description'],
        "status": "draft",
        "type": "simple",
        "images": final_images,
        "meta_data": [
            {"key": "rank_math_title", "value": p_data['seo_title']},
            {"key": "rank_math_description", "value": p_data['meta_description']},
            {"key": "rank_math_focus_keyword", "value": p_data['seo_title']}
        ]
    }
    try:
        return requests.post(f"{wp_url}/wp-json/wc/v3/products", auth=HTTPBasicAuth(ck, cs), json=payload)
    except Exception as e: return str(e)


# --- UI LAYOUT ---
with st.sidebar:
    st.title("🌿 SwissWelle Admin")
    if st.button("🔄 Reset App", type="primary"):
        st.session_state.clear()
        st.rerun()
    
    with st.expander("⚙️ Settings", expanded=True):
        provider = st.radio("AI Provider:", ["Groq", "Gemini"])
        if provider == "Groq":
            api_key = st.text_input("Groq Key", value=get_secret("groq_api_key"), type="password")
        else:
            api_key = st.text_input("Gemini Key", value=get_secret("gemini_api_key"), type="password")

# --- MAIN ---
st.title("🛍️ Create New Product")

# 1. INPUTS
col1, col2 = st.columns(2)
with col1:
    url_input = st.text_input("🔗 AliExpress URL (Scrape)")
    if st.button("🔍 Fetch Images"):
        if url_input:
            with st.spinner("Scraping..."):
                t, imgs = scrape_images(url_input)
                if t: st.session_state.p_name = t
                if imgs:
                    for i in imgs: st.session_state.final_images.append({'type': 'url', 'data': i})
                    st.success(f"Found {len(imgs)} images")
                else: st.error("No images found.")

with col2:
    upl_files = st.file_uploader("📂 Bulk Upload Images", accept_multiple_files=True)
    if upl_files:
        existing = [x['data'].name for x in st.session_state.final_images if x['type'] == 'file']
        for f in upl_files:
            if f.name not in existing:
                st.session_state.final_images.append({'type': 'file', 'data': f})

with st.expander("🔗 Bulk URL Import"):
    bulk_urls = st.text_area("Paste URLs (Line by line)")
    if st.button("Add URLs"):
        if bulk_urls:
            urls = [u.strip() for u in bulk_urls.split('\n') if u.strip()]
            for u in urls: st.session_state.final_images.append({'type': 'url', 'data': u})

# 2. IMAGE GRID
st.divider()
p_name_input = st.text_input("✨ Product Name (German)", value=st.session_state.p_name)
st.session_state.p_name = p_name_input

if st.session_state.final_images:
    st.subheader(f"Image Manager ({len(st.session_state.final_images)})")
    cols = st.columns(6)
    for i, item in enumerate(st.session_state.final_images):
        with cols[i % 6]:
            if item['type'] == 'file': st.image(item['data'], use_container_width=True)
            else: st.image(item['data'], use_container_width=True)
            st.caption(f"Image #{i+1}")
            if st.button(f"❌", key=f"del_{i}"):
                st.session_state.final_images.pop(i)
                st.rerun()

    st.divider()
    
    # 3. ACTIONS
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("Content")
        if st.button("🪄 Write Content", type="primary"):
            if not api_key or not st.session_state.p_name:
                st.error("Check Key/Name")
            else:
                with st.status("Writing Expert Content..."):
                    res = generate_content(provider, api_key, st.session_state.p_name)
                    if "error" in res: st.error(res['error'])
                    else:
                        st.session_state.html_content = res.get('html_content', '')
                        st.session_state.meta_desc = res.get('meta_description', '')
                        st.session_state.seo_title = res.get('seo_title', st.session_state.p_name)
                        st.session_state.generated = True
                        st.rerun()

    with c2:
        st.subheader("Publish")
        if st.session_state.generated:
            feat_num = st.number_input("⭐ Featured Image #:", min_value=1, max_value=len(st.session_state.final_images), value=1)
            
            if st.button("📤 Publish to Site"):
                feat_idx = feat_num - 1
                status = st.status("Publishing...")
                
                status.write("Uploading Featured...")
                feat_id = upload_to_wp(st.session_state.final_images[feat_idx], st.session_state.seo_title, get_secret("wp_url"), get_secret("wp_user"), get_secret("wp_app_pass"))
                
                if feat_id:
                    gallery_ids = []
                    for idx, img in enumerate(st.session_state.final_images):
                        if idx != feat_idx:
                            status.write(f"Uploading Gallery {idx+1}...")
                            pid = upload_to_wp(img, st.session_state.seo_title, get_secret("wp_url"), get_secret("wp_user"), get_secret("wp_app_pass"))
                            if pid: gallery_ids.append(pid)
                    
                    status.write("Creating Product...")
                    p_data = {
                        "seo_title": st.session_state.seo_title,
                        "html_content": st.session_state.html_content,
                        "meta_description": st.session_state.meta_desc
                    }
                    res = publish_product(p_data, gallery_ids, feat_id, get_secret("wp_url"), get_secret("wc_ck"), get_secret("wc_cs"))
                    
                    if hasattr(res, 'status_code') and res.status_code == 201:
                        status.update(label="Published!", state="complete")
                        st.balloons()
                        st.success("✅ Success!")
                        st.markdown(f"[👉 **View Product**]({res.json().get('permalink')})")
                    else:
                        status.update(label="Error", state="error")
                        st.error(f"Error: {res.text if hasattr(res, 'text') else res}")
                else:
                    status.update(label="Failed", state="error")
                    st.error("Featured Image Failed")

# 4. PREVIEW (VISUAL FIX)
if st.session_state.generated:
    st.divider()
    st.subheader("👁️ Content Preview")
    
    # HARDCODED WHITE BACKGROUND FOR VISIBILITY
    preview_html = f"""
    <div style="background-color: white; color: black; padding: 30px; border-radius: 10px; font-family: sans-serif; line-height: 1.6;">
        <h1 style="color: #2c3e50;">{st.session_state.seo_title}</h1>
        <p style="color: #666; font-style: italic;">{st.session_state.meta_desc}</p>
        <hr style="border: 1px solid #eee;">
        {st.session_state.html_content}
    </div>
    """
    components.html(preview_html, height=800, scrolling=True)

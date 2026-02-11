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
    page_title="SwissWelle V77",
    page_icon="🌿",
    layout="wide"
)

# --- CSS STYLING (Modern & Readable) ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .source-box { border: 1px solid #444; padding: 15px; border-radius: 8px; background: #1f2937; margin-bottom: 10px; }
    .status-ok { color: #00ff00; font-weight: bold; }
    .status-err { color: #ff4b4b; font-weight: bold; }
    div[data-testid="stImage"] { border: 1px solid #333; border-radius: 8px; }
    .preview-box { background: white; color: black; padding: 30px; border-radius: 8px; font-family: 'Helvetica', sans-serif; }
</style>
""", unsafe_allow_html=True)

# --- SECRETS ---
def get_secret(key): return st.secrets.get(key, "")

# --- SESSION STATE ---
if 'final_images' not in st.session_state: st.session_state.final_images = []
if 'p_name' not in st.session_state: st.session_state.p_name = ""
if 'context_data' not in st.session_state: st.session_state.context_data = "" 
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'seo_title' not in st.session_state: st.session_state.seo_title = ""
if 'lsi_keywords' not in st.session_state: st.session_state.lsi_keywords = [] # Store LSI keywords
if 'generated' not in st.session_state: st.session_state.generated = False

# --- FUNCTIONS ---

# 1. Advanced Scraper
@st.cache_resource
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") # Modern headless
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled") # Anti-detect
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def scrape_url(url):
    driver = get_driver()
    candidates = set()
    text_content = ""
    status = "Success"
    
    try:
        driver.get(url)
        time.sleep(4) # Slightly longer wait for JS
        
        # Check Block
        title = driver.title.lower()
        if any(x in title for x in ["robot", "captcha", "security", "access denied"]):
            status = "Blocked (Anti-Bot)"
        
        # A. Extract Text
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            text_content = body.text[:8000]
        except: text_content = ""

        # B. Extract Images (Advanced)
        images = driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            src = img.get_attribute("src")
            # Filter logic
            if src and src.startswith("http"):
                if not any(x in src for x in ['icon', 'logo', 'loader', 'gif', '1x1', 'pixel']):
                    # Clean URL
                    if "aliexpress" in url: src = src.split('_')[0] # Ali specific cleaning
                    else: src = src.split('?')[0]
                    
                    # Size check (skip tiny images if possible)
                    candidates.add(src)
                    
    except Exception as e:
        status = f"Error: {str(e)}"
        
    return status, text_content, list(candidates)

# 2. AI Content + LSI Generator
def generate_content_and_lsi(provider, api_key, p_name, context):
    prompt = f"""
    Du bist ein Senior Copywriter für 'SwissWelle.ch' (Nische: Boho-Chic, Home Decor).
    
    INPUT:
    1. PRODUKT: "{p_name}"
    2. QUELLEN-DATEN:
    \"\"\"
    {context[:12000]}
    \"\"\"
    
    AUFGABE:
    Erstelle ein JSON Objekt mit Produktbeschreibung UND LSI Keywords für Image-SEO.
    
    REGELN:
    1. **Inhalt**: Nutze NUR Fakten aus den Quellen (Material, Maße). 
       - Tonalität: Emotional, Boho, Deutsch (Sie/Du Mix passend zur Brand).
    2. **Image SEO (LSI)**: Erstelle eine Liste von 10-15 relevanten deutschen Suchbegriffen (LSI Keywords) basierend auf dem Produkt (z.B. "wandbehang-makramee-gross", "boho-wanddeko-beige"). Diese nutzen wir für Dateinamen.
    
    OUTPUT JSON FORMAT:
    {{
        "seo_title": "...",
        "meta_description": "...",
        "html_content": "HTML Code (<h2>, <ul>, <table>)...",
        "lsi_keywords": ["keyword-1", "keyword-2", "keyword-3", ...]
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
            
    except Exception as e: return {"error": str(e)}

# 3. Optimized Upload with LSI Filenames
def upload_image_optimized(item, filename_keyword, wp_url, user, password):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        
        # 1. Prepare Filename (Clean LSI Keyword)
        clean_name = re.sub(r'[^a-zA-Z0-9-]', '', filename_keyword.lower().replace(" ", "-"))
        final_filename = f"{clean_name}.jpg"
        
        # 2. Optimize Image (Pillow)
        img_byte_arr = io.BytesIO()
        
        if item['type'] == 'file':
            image = Image.open(item['data'])
        else:
            r = requests.get(item['data'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code != 200: return None
            image = Image.open(io.BytesIO(r.content))
            
        # Convert to RGB & Compress
        image = image.convert('RGB')
        image.save(img_byte_arr, format='JPEG', quality=85, optimize=True)
        img_data = img_byte_arr.getvalue()

        # 3. Upload to WP
        headers = {
            'Content-Disposition': f'attachment; filename={final_filename}',
            'Content-Type': 'image/jpeg'
        }
        res = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password))
        
        if res.status_code == 201:
            pid = res.json()['id']
            # 4. Set ALT Text & Title to LSI Keyword
            seo_update = {
                "alt_text": filename_keyword.replace("-", " "),
                "title": filename_keyword.replace("-", " "),
                "caption": filename_keyword.replace("-", " ")
            }
            requests.post(f"{api_url}/{pid}", json=seo_update, auth=HTTPBasicAuth(user, password))
            return pid
    except Exception as e: 
        print(f"Upload Error: {e}")
        return None
    return None

def publish_final_product(p_data, image_ids, feat_id, wp_url, ck, cs):
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
    try: return requests.post(f"{wp_url}/wp-json/wc/v3/products", auth=HTTPBasicAuth(ck, cs), json=payload)
    except Exception as e: return str(e)


# --- UI SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V77")
    if st.button("🔄 New Post", type="primary"):
        st.session_state.clear()
        st.rerun()
    
    with st.expander("⚙️ Settings", expanded=True):
        provider = st.radio("AI Provider:", ["Groq", "Gemini"])
        if provider == "Groq":
            api_key = st.text_input("Groq Key", value=get_secret("groq_api_key"), type="password")
        else:
            api_key = st.text_input("Gemini Key", value=get_secret("gemini_api_key"), type="password")

# --- MAIN UI ---

# 1. IDENTITY
st.subheader("1. Product Identity")
p_name_input = st.text_input("Product Name (Primary Keyword)", value=st.session_state.p_name)
st.session_state.p_name = p_name_input

# 2. DATA SOURCES
st.subheader("2. Data Sources (Context)")
c1, c2 = st.columns([1, 1])

with c1:
    with st.expander("🔗 Scrape URLs (Amazon/Ali/Walmart)", expanded=True):
        urls_input = st.text_area("Paste URLs (One per line)", height=100)
        if st.button("🔍 Fetch Data"):
            if urls_input:
                urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
                prog = st.progress(0)
                
                for i, url in enumerate(urls):
                    status, txt, imgs = scrape_url(url)
                    
                    # Append Text
                    header = f"\n=== SOURCE: {url} | STATUS: {status} ===\n"
                    st.session_state.context_data += header + txt
                    
                    # Append Images
                    for img in imgs:
                        st.session_state.final_images.append({'type': 'url', 'data': img})
                    
                    prog.progress((i + 1) / len(urls))
                
                st.success(f"Done. Images Found: {len(st.session_state.final_images)}")
                st.rerun()

with c2:
    with st.expander("📝 Manual Data (Fallback)", expanded=True):
        st.caption("If scraper fails (e.g. Amazon Block), paste description here:")
        manual_txt = st.text_area("Product Details", height=135, placeholder="Paste product specs, size, material here...")
        if manual_txt:
            st.session_state.context_data += "\n=== MANUAL DATA ===\n" + manual_txt

# 3. IMAGE MANAGER
st.subheader(f"3. Image Manager ({len(st.session_state.final_images)})")
upl_files = st.file_uploader("Upload Manual Images", accept_multiple_files=True)
if upl_files:
    for f in upl_files:
        st.session_state.final_images.append({'type': 'file', 'data': f})
    st.rerun()

if st.session_state.final_images:
    cols = st.columns(6)
    for i, item in enumerate(st.session_state.final_images):
        with cols[i % 6]:
            with st.container():
                if item['type'] == 'file': st.image(item['data'], use_container_width=True)
                else: st.image(item['data'], use_container_width=True)
                st.caption(f"Image #{i+1}")
                if st.button("❌", key=f"del_{i}"):
                    st.session_state.final_images.pop(i)
                    st.rerun()

# 4. GENERATE & PREVIEW
st.divider()

if st.button("🪄 Generate Content & LSI Keywords", type="primary"):
    if not api_key or not st.session_state.p_name:
        st.error("Missing Name or API Key")
    else:
        # Combine all data
        full_context = st.session_state.context_data
        if len(full_context) < 10:
            st.warning("No data found! Please scrape a URL or paste text manually.")
        else:
            with st.status("AI Working (Content + LSI Research)..."):
                res = generate_content_and_lsi(provider, api_key, st.session_state.p_name, full_context)
                if "error" in res: st.error(res['error'])
                else:
                    st.session_state.html_content = res.get('html_content', '')
                    st.session_state.meta_desc = res.get('meta_description', '')
                    st.session_state.seo_title = res.get('seo_title', st.session_state.p_name)
                    st.session_state.lsi_keywords = res.get('lsi_keywords', [])
                    st.session_state.generated = True
                    st.rerun()

# PREVIEW SECTION
if st.session_state.generated:
    st.divider()
    c_prev, c_pub = st.columns([2, 1])
    
    with c_prev:
        st.subheader("👁️ Preview")
        
        # Show LSI Keywords
        with st.expander("📊 Generated LSI Keywords (For Images)"):
            st.write(st.session_state.lsi_keywords)
        
        # Visual Preview
        preview_html = f"""
        <div class="preview-box">
            <h1>{st.session_state.seo_title}</h1>
            <p><em>{st.session_state.meta_desc}</em></p>
            <hr>
            {st.session_state.html_content}
        </div>
        """
        components.html(preview_html, height=600, scrolling=True)
        
    with c_pub:
        st.subheader("🚀 Publish")
        total = len(st.session_state.final_images)
        feat_num = st.number_input("Featured Image #:", min_value=1, max_value=total if total else 1, value=1)
        
        if st.button("📤 Upload & Publish"):
            if total == 0:
                st.error("No images!")
            else:
                feat_idx = feat_num - 1
                status = st.status("Starting Publish Process...")
                
                # Get Keywords
                lsi_list = st.session_state.lsi_keywords
                if not lsi_list: lsi_list = [st.session_state.seo_title]
                
                uploaded_ids = []
                
                # Upload Loop with LSI Renaming
                for idx, img in enumerate(st.session_state.final_images):
                    # Pick a keyword (Loop if images > keywords)
                    keyword = lsi_list[idx % len(lsi_list)]
                    # Add number to avoid duplicate filenames if looping
                    if idx >= len(lsi_list): keyword += f"-{idx}"
                    
                    status.write(f"Optimizing & Uploading Image #{idx+1} as '{keyword}.jpg'...")
                    
                    pid = upload_image_optimized(img, keyword, get_secret("wp_url"), get_secret("wp_user"), get_secret("wp_app_pass"))
                    if pid: uploaded_ids.append(pid)
                
                if not uploaded_ids:
                    status.update(label="Upload Failed", state="error")
                    st.error("No images could be uploaded.")
                else:
                    # Identify Featured ID
                    # Note: We uploaded in order, so feat_idx corresponds to uploaded_ids index
                    if feat_idx < len(uploaded_ids):
                        final_feat_id = uploaded_ids[feat_idx]
                    else:
                        final_feat_id = uploaded_ids[0] # Fallback
                    
                    status.write("Creating Product Draft...")
                    
                    p_data = {
                        "seo_title": st.session_state.seo_title,
                        "html_content": st.session_state.html_content,
                        "meta_description": st.session_state.meta_desc
                    }
                    
                    res = publish_final_product(p_data, uploaded_ids, final_feat_id, get_secret("wp_url"), get_secret("wc_ck"), get_secret("wc_cs"))
                    
                    if hasattr(res, 'status_code') and res.status_code == 201:
                        status.update(label="Published!", state="complete")
                        st.balloons()
                        st.success("✅ Product Live!")
                        st.markdown(f"[👉 **Click to Edit**]({res.json().get('permalink')})")
                    else:
                        status.update(label="Publish Error", state="error")
                        st.error(f"Error: {res.text if hasattr(res, 'text') else res}")

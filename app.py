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
from bs4 import BeautifulSoup
from PIL import Image
import io

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="SwissWelle Pro Suite",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CUSTOM CSS ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; }
    .stTextInput>div>div>input { border-radius: 8px; }
    div[data-testid="stImage"] { border-radius: 10px; overflow: hidden; border: 1px solid #333; }
    .img-label { text-align: center; font-weight: bold; margin-top: 5px; color: #00ff00; }
    
    /* Content Preview Styling */
    .content-box {
        background: white; 
        color: #333; 
        padding: 30px; 
        border-radius: 8px; 
        font-family: 'Helvetica', sans-serif;
        line-height: 1.6;
    }
    .content-box h2 { color: #2c3e50; border-bottom: 2px solid #e67e22; padding-bottom: 10px; margin-top: 20px; }
    .content-box ul { background: #f9f9f9; padding: 20px 40px; border-radius: 5px; }
    .content-box table { width: 100%; border-collapse: collapse; margin: 20px 0; }
    .content-box th, .content-box td { border: 1px solid #ddd; padding: 12px; text-align: left; }
    .content-box th { background-color: #f2f2f2; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- SECRETS ---
def get_secret(key): return st.secrets.get(key, "")

# --- SESSION STATE ---
if 'final_images' not in st.session_state: st.session_state.final_images = []
if 'p_name' not in st.session_state: st.session_state.p_name = ""
if 'scraped_text' not in st.session_state: st.session_state.scraped_text = ""
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'seo_title' not in st.session_state: st.session_state.seo_title = ""
if 'generated' not in st.session_state: st.session_state.generated = False

# --- FUNCTIONS ---

# 1. Universal Scraper (Text + Images)
@st.cache_resource
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def scrape_url_data(url):
    driver = get_driver()
    candidates = set()
    text_content = ""
    title = ""
    
    try:
        driver.get(url)
        time.sleep(3) # Wait for load
        
        # A. Extract Title
        title = driver.title.split('|')[0].strip()
        if "login" in title.lower() or "security" in title.lower() or "robot" in title.lower():
            title = "" # Blocked likely
        
        # B. Extract Text Content (Visible text)
        body = driver.find_element(By.TAG_NAME, "body")
        text_content = body.text[:5000] # Limit to 5000 chars to save tokens
        
        # C. Extract Images (Generic)
        # 1. Look for img tags
        images = driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            src = img.get_attribute("src")
            if src and src.startswith("http"):
                # Filter small icons/trackers
                if not any(x in src for x in ['icon', 'logo', 'tracking', '1x1', '32x32', '50x50']):
                    # Clean AliExpress URLs if present
                    src = src.split('?')[0]
                    candidates.add(src)
        
        # 2. Look for OG Image (Meta)
        try:
            og_img = driver.find_element(By.CSS_SELECTOR, 'meta[property="og:image"]').get_attribute("content")
            if og_img: candidates.add(og_img)
        except: pass
        
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        
    return title, text_content, list(candidates)

# 2. Content Generator (Context Aware)
def generate_content(provider, api_key, p_name, context_text):
    # Prompt with Source Data
    prompt = f"""
    Du bist ein erfahrener deutscher Senior Content Writer für 'SwissWelle.ch'. 
    Unsere Nische: Boho-Chic, Makramee, Nachhaltige Wohnkultur.
    
    PRODUKT: {p_name}
    
    QUELLEN-INFORMATION (Nutze diese Daten für Fakten wie Material, Größe, Farbe):
    \"\"\"
    {context_text[:8000]} 
    \"\"\"
    
    AUFGABE:
    Schreibe eine hochkonvertierende, SEO-optimierte Produktbeschreibung in HTML basierend auf den oben genannten Fakten, aber im "SwissWelle"-Stil.
    
    ANFORDERUNGEN:
    1. **Tonalität**: Professionell, Emotional, Boho-Vibe, "Du"-Ansprache.
    2. **Inhalt**:
       - Nutze die FAKTEN aus dem Quelltext (Material, Maße etc.). Erfinde nichts Falsches, aber schmücke es schön aus.
       - Wenn Fakten fehlen, nutze generisches Boho-Wissen (z.B. "hochwertige Verarbeitung").
    3. **Struktur**:
       - **SEO Titel**: Catchy & Relevant.
       - **Intro**: Emotionaler Hook.
       - **Spezifikationen (Tabelle)**: HTML <table> mit: Material, Stil, Maße, Farbe, Besonderheiten.
       - **Vorteile**: Bullet Points (<ul>).
       - **CTA**: Kaufaufruf.
    4. **Format**: Nur HTML Code (<h2>, <p>, <ul>, <table>). KEINE <html>/<body> Tags.
    
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
        clean_name = clean_name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
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
            # SEO Alt Text
            requests.post(f"{api_url}/{pid}", json={"alt_text": p_name, "title": p_name, "caption": p_name}, auth=HTTPBasicAuth(user, password))
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
    if st.button("🔄 Reset / New Post", type="primary"):
        st.session_state.clear()
        st.rerun()
    
    with st.expander("⚙️ Settings", expanded=True):
        provider = st.radio("AI Provider:", ["Groq", "Gemini"])
        if provider == "Groq":
            api_key = st.text_input("Groq Key", value=get_secret("groq_api_key"), type="password")
        else:
            api_key = st.text_input("Gemini Key", value=get_secret("gemini_api_key"), type="password")

# --- MAIN ---

# SECTION 1: SOURCES
st.subheader("1. Product Sources (Content & Images)")

# A. URLs
with st.expander("🔗 Resource URLs (Amazon, AliExpress, etc.)", expanded=True):
    urls_input = st.text_area("Paste URLs (One per line) - We will fetch Text & Images", height=100)
    if st.button("🔍 Analyze URLs"):
        if urls_input:
            urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
            
            progress_text = "Analyzing sources..."
            my_bar = st.progress(0, text=progress_text)
            
            total_text = ""
            total_imgs = 0
            
            for i, url in enumerate(urls):
                t_title, t_content, t_imgs = scrape_url_data(url)
                
                # Append Text to Knowledge Base
                total_text += f"\n\n--- SOURCE: {url} ---\nTITLE: {t_title}\nCONTENT: {t_content}\n"
                
                # Set Name if empty
                if not st.session_state.p_name and t_title:
                    st.session_state.p_name = t_title
                
                # Add Images
                for img in t_imgs:
                    st.session_state.final_images.append({'type': 'url', 'data': img})
                    total_imgs += 1
                
                my_bar.progress((i + 1) / len(urls), text=f"Scraped {url}...")
            
            # Save scraped text
            st.session_state.scraped_text += total_text
            st.success(f"Done! Found {total_imgs} images and extracted product details.")
            st.rerun()

# B. Manual Content
with st.expander("📝 Manual Content / Notes (Optional)"):
    manual_text = st.text_area("Paste raw product description here if scraping fails, or add specific instructions.", height=150)

# C. Manual Images
with st.expander("📂 Upload Images"):
    upl_files = st.file_uploader("Bulk Upload", accept_multiple_files=True)
    if upl_files:
        existing = [x['data'].name for x in st.session_state.final_images if x['type'] == 'file']
        for f in upl_files:
            if f.name not in existing:
                st.session_state.final_images.append({'type': 'file', 'data': f})
        st.success(f"Added {len(upl_files)} files")

# SECTION 2: REVIEW
st.divider()
col_a, col_b = st.columns([2, 1])

with col_a:
    st.subheader("2. Image Manager")
    p_name_input = st.text_input("Product Name (German)", value=st.session_state.p_name)
    st.session_state.p_name = p_name_input
    
    if st.session_state.final_images:
        cols = st.columns(4)
        for i, item in enumerate(st.session_state.final_images):
            with cols[i % 4]:
                if item['type'] == 'file': st.image(item['data'], use_container_width=True)
                else: st.image(item['data'], use_container_width=True)
                st.caption(f"Image #{i+1}")
                if st.button(f"🗑️", key=f"del_{i}"):
                    st.session_state.final_images.pop(i)
                    st.rerun()

with col_b:
    st.subheader("3. Actions")
    
    # GENERATE
    if st.button("🪄 Write Content", type="primary"):
        if not api_key or not st.session_state.p_name:
            st.error("Missing Info")
        else:
            # Combine Scraped + Manual Text
            full_context = st.session_state.scraped_text + "\n\nMANUAL NOTES:\n" + manual_text
            
            with st.status("Reading Sources & Writing..."):
                res = generate_content(provider, api_key, st.session_state.p_name, full_context)
                if "error" in res: st.error(res['error'])
                else:
                    st.session_state.html_content = res.get('html_content', '')
                    st.session_state.meta_desc = res.get('meta_description', '')
                    st.session_state.seo_title = res.get('seo_title', st.session_state.p_name)
                    st.session_state.generated = True
                    st.rerun()
    
    # PUBLISH
    if st.session_state.generated:
        st.divider()
        st.write("Ready to Publish!")
        feat_num = st.number_input("Featured Image #:", min_value=1, max_value=len(st.session_state.final_images), value=1)
        
        if st.button("📤 Upload & Publish"):
            feat_idx = feat_num - 1
            status = st.status("Publishing...")
            
            # Upload Featured
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

# 4. PREVIEW
if st.session_state.generated:
    st.divider()
    st.subheader("👁️ Content Preview")
    preview_html = f"""
    <div style="background-color: white; color: black; padding: 30px; border-radius: 10px; font-family: sans-serif; line-height: 1.6;">
        <h1 style="color: #2c3e50;">{st.session_state.seo_title}</h1>
        <p style="color: #666; font-style: italic;">{st.session_state.meta_desc}</p>
        <hr style="border: 1px solid #eee;">
        {st.session_state.html_content}
    </div>
    """
    components.html(preview_html, height=800, scrolling=True)

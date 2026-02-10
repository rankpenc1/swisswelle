import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import google.generativeai as genai
from PIL import Image
from io import BytesIO
import json
import shutil
import os
import urllib3
import streamlit.components.v1 as components
import re
import random
import time 
import requests
from fake_useragent import UserAgent
from woocommerce import API
from requests.auth import HTTPBasicAuth
from duckduckgo_search import DDGS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="SwissWelle V31 (Boho+SEO)", page_icon="🌿", layout="wide")

# --- 1. SECURITY & SECRETS ---
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["app_login_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else: st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Enter Admin Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Enter Admin Password", type="password", on_change=password_entered, key="password")
        st.error("❌ Password incorrect")
        return False
    else: return True

if not check_password(): st.stop()

def get_secret(key):
    return st.secrets[key] if key in st.secrets else ""

# Initialize
default_api_key = get_secret("gemini_api_key")
default_wp_url = get_secret("wp_url")
default_wc_ck = get_secret("wc_ck")
default_wc_cs = get_secret("wc_cs")
default_wp_user = get_secret("wp_user")
default_wp_app_pass = get_secret("wp_app_pass")

if 'generated' not in st.session_state: st.session_state.generated = False
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'image_map' not in st.session_state: st.session_state.image_map = {}
if 'p_name' not in st.session_state: st.session_state.p_name = ""

# --- SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V31")
    st.caption("Boho Edition + RankMath SEO")
    
    with st.expander("AI Settings", expanded=True):
        api_key = st.text_input("Gemini API Key", value=default_api_key, type="password")
        valid_model = None
        if api_key:
            try:
                genai.configure(api_key=api_key)
                models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                preferred = ['models/gemini-1.5-pro', 'models/gemini-1.5-flash']
                valid_model = next((m for p in preferred for m in models if p in m), models[0] if models else None)
                if valid_model: st.success(f"Brain: {valid_model.split('/')[-1]}")
            except: pass

    with st.expander("Website Config", expanded=True):
        wp_url = st.text_input("URL", value=default_wp_url)
        wc_ck = st.text_input("CK", value=default_wc_ck, type="password")
        wc_cs = st.text_input("CS", value=default_wc_cs, type="password")
        wp_user = st.text_input("User", value=default_wp_user)
        wp_app_pass = st.text_input("Pass", value=default_wp_app_pass, type="password")

# --- LOGIC ---
def clean_url(url):
    url = re.sub(r'\?v=.*', '', url)
    if 'aliexpress' in url: url = re.sub(r'_\d+x\d+\.(jpg|png|webp).*', '.\g<1>', url)
    if 'shopify' in url or 'amazon' in url: return re.sub(r'_(small|thumb|medium|large|compact|\d+x\d+)', '', url).split('?')[0]
    return url

def get_images_from_search(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=10))
            return [r['image'] for r in results]
    except: return []

def scrape(url):
    try:
        scraper = cloudscraper.create_scraper()
        time.sleep(2)
        r = scraper.get(url, timeout=20)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # Get Images
        candidates = set()
        if 'aliexpress' in url:
            ali_matches = re.findall(r'"(https://[^"]+?\.(?:jpg|jpeg|png|webp))"', soup.get_text())
            for m in ali_matches: 
                if 'ae01' in m or 'alicdn' in m: candidates.add(clean_url(m))
        for s in soup.find_all('script'):
            if s.string:
                matches = re.findall(r'https?://[^\s"\'<>]+?\.(?:jpg|jpeg|png|webp)', s.string)
                for m in matches: 
                    if 'media-amazon' in m: m = re.sub(r'\._AC_.*_\.', '.', m)
                    candidates.add(clean_url(m))
        for img in soup.find_all(['img', 'a']):
            for k, v in img.attrs.items():
                if isinstance(v, str) and 'http' in v:
                    if any(ext in v.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']): candidates.add(clean_url(v))
        
        final = []
        for c in candidates:
            if any(x in c.lower() for x in ['icon', 'logo', 'avatar', 'gif', 'svg', 'blank']): continue
            if c.startswith('http'): final.append(c)
            
        for s in soup(["script", "style", "nav", "footer"]): s.extract()
        return soup.get_text(separator=' ', strip=True)[:30000], list(set(final))
    except: return "", []

def ai_process(key, model_name, p_name, text, imgs):
    genai.configure(api_key=key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""Role: Senior German Copywriter for 'swisswelle.ch'.
    Tone: **Boho-Chic, Free-spirited, Artistic, Emotional, High-Quality.**
    Target Audience: Women who love unique, handmade, and soulful jewelry.
    
    Product: {p_name}
    
    TASKS:
    1. Write a product description in HTML (h2, h3, ul, p).
       - NO Em-Dashes. Short sentences.
       - Focus on the "Boho Vibe" (freedom, nature, art, individuality).
    2. Write a **RankMath SEO Meta Description** (max 160 chars) in German.
    3. Select 15-20 BEST images. Rename them with German keywords (no extensions).
    
    Candidate Images: {imgs[:400]}
    Context: {text[:50000]}
    
    OUTPUT JSON: {{ 
        "html_content": "...", 
        "meta_description": "...",
        "image_map": {{ "original_url": "german-boho-name" }} 
    }}"""
    
    try:
        res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(res.text)
    except Exception as e: return {"error": str(e)}

# --- PUBLISH FUNCTIONS ---
def upload_image_to_wp(filepath, wp_url, user, app_pass, alt_text):
    url = f"{wp_url}/wp-json/wp/v2/media"
    filename = os.path.basename(filepath)
    with open(filepath, 'rb') as img: media_data = img.read()
    headers = {'Content-Disposition': f'attachment; filename={filename}', 'Content-Type': 'image/webp', 'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.post(url, data=media_data, headers=headers, auth=HTTPBasicAuth(user, app_pass), verify=False)
        if r.status_code == 201:
            img_id = r.json()['id']
            requests.post(f"{url}/{img_id}", json={"alt_text": alt_text, "title": alt_text}, auth=HTTPBasicAuth(user, app_pass), verify=False)
            return img_id
        return None
    except: return None

def publish_product(title, desc, featured_id, gallery_ids, meta_desc, wp_url, ck, cs):
    wcapi = API(url=wp_url, consumer_key=ck, consumer_secret=cs, version="wc/v3", timeout=30, verify_ssl=False)
    
    # Construct Image Payload (Featured First)
    img_payload = [{"id": featured_id}] + [{"id": i} for i in gallery_ids if i != featured_id]
    
    data = {
        "name": title,
        "description": desc,
        "status": "draft",
        "images": img_payload,
        "type": "simple",
        "regular_price": "0.00",
        "meta_data": [
            {"key": "rank_math_description", "value": meta_desc},
            {"key": "rank_math_focus_keyword", "value": title}
        ]
    }
    try: return wcapi.post("products", data)
    except: return None

# --- UI ---
if not st.session_state.generated:
    st.session_state.p_name = st.text_input("Product Name", "SilberSchlinge")
    urls_input = st.text_area("Reference URLs", height=100)
    
    if st.button("🚀 Generate (Boho Style)", type="primary"):
        if not api_key: st.error("API Key Missing"); st.stop()
        
        url_list = [u.strip() for u in re.split(r'[\s,]+', urls_input) if u.strip()]
        
        with st.status("Channeling Boho Vibes...", expanded=True) as s:
            full_text = ""
            all_imgs = []
            
            for u in url_list:
                if u.startswith('http'):
                    t, i = scrape(u)
                    full_text += t + " "
                    all_imgs.extend(i)
                    s.write(f"✅ Scraped: {u}")
            
            unique_imgs = list(set(all_imgs))
            if len(unique_imgs) < 2:
                s.write("⚠️ Searching backup images...")
                unique_imgs.extend(get_images_from_search(st.session_state.p_name + " boho jewelry"))
            
            s.write(f"📸 Analying {len(unique_imgs)} images...")
            res = ai_process(api_key, valid_model, st.session_state.p_name, full_text, unique_imgs)
            
            if "error" in res: st.error(res['error'])
            else:
                st.session_state.html_content = res['html_content']
                st.session_state.meta_desc = res.get('meta_description', '')
                
                if os.path.exists('output'): shutil.rmtree('output')
                os.makedirs('output')
                
                final_map = {}
                s.write("🖼️ Processing Images...")
                scraper_s = cloudscraper.create_scraper()
                for url, name in res.get('image_map', {}).items():
                    try:
                        r = scraper_s.get(url, timeout=10)
                        img = Image.open(BytesIO(r.content))
                        if img.width > 200:
                            if img.mode != 'RGB': img = img.convert('RGB')
                            clean_name = "".join(x for x in name if x.isalnum() or x in "-").lower().replace("webp", "")
                            fname = f"{clean_name}.webp"
                            save_path = f"output/{fname}"
                            img.save(save_path, "WEBP", quality=90)
                            final_map[save_path] = clean_name.replace("-", " ") 
                    except: pass
                
                st.session_state.image_map = final_map
                st.session_state.generated = True
                st.rerun()

else:
    # --- RESULT VIEW ---
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("1. Select Images")
        image_files = list(st.session_state.image_map.keys())
        
        # Selection State
        if 'selections' not in st.session_state:
            st.session_state.selections = {img: True for img in image_files}
            
        # Grid Checkboxes
        cols = st.columns(3)
        for idx, img_path in enumerate(image_files):
            with cols[idx % 3]:
                st.image(img_path, use_column_width=True)
                st.session_state.selections[img_path] = st.checkbox(f"Keep", value=st.session_state.selections.get(img_path, True), key=f"chk_{idx}")
        
        # Filter Selected
        final_selected = [img for img, sel in st.session_state.selections.items() if sel]
        
        st.markdown("---")
        st.subheader("2. Publish Options")
        
        # FEATURED IMAGE SELECTOR
        featured_img = st.selectbox("Select Featured Image (Main):", final_selected)
        
        # META DESC EDITOR
        meta_input = st.text_area("SEO Meta Description (RankMath):", value=st.session_state.meta_desc)
        
        if st.button("📤 Publish Draft to SwissWelle", type="primary"):
            if not (wp_url and wc_ck and wc_cs): st.error("Check Website Connection!"); st.stop()
            
            with st.spinner("Publishing..."):
                # 1. Upload Featured First
                feat_alt = st.session_state.image_map.get(featured_img, st.session_state.p_name)
                feat_id = upload_image_to_wp(featured_img, wp_url, wp_user, wp_app_pass, feat_alt)
                
                # 2. Upload Others
                gallery_ids = []
                progress = st.progress(0)
                for i, p in enumerate(final_selected):
                    if p != featured_img: # Skip if already uploaded as featured
                        alt = st.session_state.image_map.get(p, st.session_state.p_name)
                        pid = upload_image_to_wp(p, wp_url, wp_user, wp_app_pass, alt)
                        if pid: gallery_ids.append(pid)
                    progress.progress((i+1)/len(final_selected))
                
                # 3. Create Product
                if feat_id:
                    res = publish_product(
                        st.session_state.p_name, 
                        st.session_state.html_content, 
                        feat_id, 
                        gallery_ids, 
                        meta_input, 
                        wp_url, wc_ck, wc_cs
                    )
                    
                    if res and res.status_code == 201:
                        st.success("✅ Published Successfully!")
                        st.markdown(f"[👉 **Edit in WordPress**]({res.json().get('permalink')})")
                        st.balloons()
                    else: st.error(f"Failed: {res.text if res else 'Unknown'}")
                else: st.error("Failed to upload featured image.")

    with c2:
        # TABS FOR PREVIEW
        tab1, tab2 = st.tabs(["👁️ Visual Preview", "📋 HTML Code"])
        
        with tab1:
            components.html(f'<div style="background:white;padding:20px;color:black;font-family:sans-serif;">{st.session_state.html_content}</div>', height=800, scrolling=True)
        
        with tab2:
            st.code(st.session_state.html_content, language='html')
            st.info("Copy this code if you want to paste manually.")

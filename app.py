import streamlit as st
from bs4 import BeautifulSoup
import google.generativeai as genai
from PIL import Image
from io import BytesIO
import json
import shutil
import os
import re
import time 
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from fake_useragent import UserAgent
from woocommerce import API
from requests.auth import HTTPBasicAuth
from duckduckgo_search import DDGS

st.set_page_config(page_title="SwissWelle V34", page_icon="🛍️", layout="wide")

# --- 1. SECURITY ---
def check_password():
    if "password_correct" not in st.session_state: st.session_state.password_correct = False
    
    def password_entered():
        if st.session_state["password"] == st.secrets["app_login_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else: st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.text_input("Enter Admin Password", type="password", on_change=password_entered, key="password")
        return False
    return True

if not check_password(): st.stop()

def get_secret(key): return st.secrets[key] if key in st.secrets else ""

# Init Secrets
default_api_key = get_secret("gemini_api_key")
default_wp_url = get_secret("wp_url")
default_wc_ck = get_secret("wc_ck")
default_wc_cs = get_secret("wc_cs")
default_wp_user = get_secret("wp_user")
default_wp_app_pass = get_secret("wp_app_pass")

# Session Reset Logic
def reset_app():
    for key in list(st.session_state.keys()):
        if key != 'password_correct': del st.session_state[key]
    st.rerun()

# Init Session
for k in ['generated', 'html_content', 'meta_desc', 'image_map', 'p_name']:
    if k not in st.session_state: st.session_state[k] = None if k == 'p_name' else ""
if 'image_map' not in st.session_state or not isinstance(st.session_state.image_map, dict):
    st.session_state.image_map = {}

# --- SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V34")
    st.caption("Selenium + Auto AI Fix")
    
    if st.button("🔄 Start New Post", type="primary"):
        reset_app()
    
    with st.expander("Settings", expanded=True):
        api_key = st.text_input("Gemini API", value=default_api_key, type="password")
        
        # AUTO MODEL DETECTOR
        valid_model = None
        if api_key:
            try:
                genai.configure(api_key=api_key)
                models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                # Priority list
                preferred = ['models/gemini-1.5-pro', 'models/gemini-1.5-flash', 'models/gemini-1.0-pro', 'models/gemini-pro']
                valid_model = next((m for p in preferred for m in models if p in m), models[0] if models else None)
                if valid_model: st.success(f"✅ AI Ready: {valid_model.split('/')[-1]}")
            except: st.error("❌ Invalid API Key")

        wp_url = st.text_input("WP URL", value=default_wp_url)
        wc_ck = st.text_input("CK", value=default_wc_ck, type="password")
        wc_cs = st.text_input("CS", value=default_wc_cs, type="password")
        wp_user = st.text_input("User", value=default_wp_user)
        wp_app_pass = st.text_input("Pass", value=default_wp_app_pass, type="password")

# --- SELENIUM SCRAPER ---
@st.cache_resource
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=chrome_options)

def clean_url(url):
    url = url.split('?')[0]
    if 'alicdn' in url:
        url = re.sub(r'_\d+x\d+\.(jpg|png|webp).*', '', url)
        if not url.endswith(('.jpg', '.png', '.webp')): url += '.jpg'
    if 'shopify' in url or 'amazon' in url: 
        return re.sub(r'_(small|thumb|medium|large|compact|\d+x\d+)', '', url).split('?')[0]
    return url

def get_images_from_search(query):
    try:
        with DDGS() as ddgs:
            return [r['image'] for r in list(ddgs.images(query, max_results=10))]
    except: return []

def scrape(url):
    try:
        driver = get_driver()
        driver.get(url)
        time.sleep(5) 
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        candidates = set()
        
        # Regex for AliExpress
        matches = re.findall(r'(https?://[^"\'\s<>]+?alicdn\.com[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp))', str(soup))
        for m in matches: candidates.add(clean_url(m))
        
        for img in soup.find_all(['img', 'a']):
            for k, v in img.attrs.items():
                if isinstance(v, str) and 'http' in v:
                    if any(ext in v.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']): 
                        candidates.add(clean_url(v))
        
        final = []
        for c in candidates:
            if any(x in c.lower() for x in ['icon', 'logo', 'avatar', 'gif', 'svg', 'blank', 'loading']): continue
            if c.startswith('http'): final.append(c)
            
        return soup.get_text(separator=' ', strip=True)[:30000], list(set(final))
    except Exception as e:
        print(f"Scrape Error: {e}")
        return "", []

def ai_process(key, model_name, p_name, text, imgs):
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""Role: Senior German Copywriter for 'swisswelle.ch'.
        Tone: Boho-Chic, Free-spirited, Artistic.
        Product: {p_name}
        
        TASKS:
        1. Write HTML description (h2, h3, ul, p). NO Em-Dashes.
        2. Write RankMath SEO Meta Description (German).
        3. Select 15-20 BEST images. Rename with German keywords (no extensions).
        
        Images found: {len(imgs)}
        List: {imgs[:400]}
        Context: {text[:50000]}
        
        JSON OUTPUT: {{ "html_content": "...", "meta_description": "...", "image_map": {{ "original_url": "german-name" }} }}"""
        
        res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(res.text)
    except Exception as e: return {"error": str(e)}

# --- UPLOAD & PUBLISH ---
def upload_image(url, wp_url, user, password, alt):
    try:
        img_data = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).content
        filename = f"{alt.replace(' ', '-').lower()}.webp"
        
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        headers = {'Content-Disposition': f'attachment; filename={filename}', 'Content-Type': 'image/webp'}
        r = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password))
        
        if r.status_code == 201:
            pid = r.json()['id']
            requests.post(f"{api_url}/{pid}", json={"alt_text": alt, "title": alt}, auth=HTTPBasicAuth(user, password))
            return pid
    except: pass
    return None

def publish(title, desc, meta, feat_id, gallery_ids, wp_url, ck, cs):
    wcapi = API(url=wp_url, consumer_key=ck, consumer_secret=cs, version="wc/v3", timeout=60)
    images = [{"id": feat_id}] + [{"id": i} for i in gallery_ids if i != feat_id]
    data = {
        "name": title, "description": desc, "status": "draft", "images": images,
        "type": "simple", "regular_price": "0.00",
        "meta_data": [
            {"key": "rank_math_description", "value": meta},
            {"key": "rank_math_focus_keyword", "value": title}
        ]
    }
    return wcapi.post("products", data)

# --- UI ---
if not st.session_state.generated:
    st.session_state.p_name = st.text_input("Product Name", "Boho Ring")
    urls_input = st.text_area("AliExpress/Amazon URLs", height=100)
    
    if st.button("🚀 Generate (Selenium + AI)", type="primary"):
        if not api_key: st.error("No API Key"); st.stop()
        if not valid_model: st.error("No valid AI model found for this key!"); st.stop()
        
        with st.status("Running Selenium Browser...", expanded=True) as s:
            full_text = ""
            all_imgs = []
            urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
            
            for u in urls:
                t, i = scrape(u)
                full_text += t
                all_imgs.extend(i)
                s.write(f"✅ Scraped: {len(i)} images found")
            
            unique_imgs = list(set(all_imgs))
            # Fallback search if Selenium fails
            if len(unique_imgs) < 3:
                s.write("⚠️ Low images? Searching web backup...")
                unique_imgs.extend(get_images_from_search(st.session_state.p_name + " boho jewelry"))
            
            s.write(f"🧠 AI Processing with {valid_model}...")
            res = ai_process(api_key, valid_model, st.session_state.p_name, full_text, unique_imgs)
            
            if "error" in res: st.error(res['error'])
            else:
                st.session_state.html_content = res['html_content']
                st.session_state.meta_desc = res.get('meta_description', '')
                st.session_state.image_map = res.get('image_map', {})
                st.session_state.generated = True
                st.rerun()

else:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Select Images")
        img_urls = list(st.session_state.image_map.keys())
        
        if 'selections' not in st.session_state:
            st.session_state.selections = {u: True for u in img_urls}
            
        cols = st.columns(3)
        for i, u in enumerate(img_urls):
            with cols[i%3]:
                st.image(u)
                st.session_state.selections[u] = st.checkbox("Keep", value=st.session_state.selections.get(u, True), key=f"c{i}")
        
        final_imgs = [u for u, s in st.session_state.selections.items() if s]
        
        st.markdown("---")
        feat_img = st.selectbox("Featured Image", final_imgs) if final_imgs else None
        
        if st.button("📤 Publish Draft"):
            with st.spinner("Uploading..."):
                alt_text = st.session_state.image_map.get(feat_img, st.session_state.p_name)
                feat_id = upload_image(feat_img, wp_url, wp_user, wp_app_pass, alt_text)
                
                gallery_ids = []
                bar = st.progress(0)
                for i, u in enumerate(final_imgs):
                    if u != feat_img:
                        alt = st.session_state.image_map.get(u, st.session_state.p_name)
                        pid = upload_image(u, wp_url, wp_user, wp_app_pass, alt)
                        if pid: gallery_ids.append(pid)
                    bar.progress((i+1)/len(final_imgs))
                
                res = publish(st.session_state.p_name, st.session_state.html_content, st.session_state.meta_desc, feat_id, gallery_ids, wp_url, wc_ck, wc_cs)
                
                if res and res.status_code == 201:
                    st.success("✅ Done!")
                    st.markdown(f"[View Draft]({res.json().get('permalink')})")
                    if st.button("🔄 Start New Post (Reset)"): reset_app()
                else: st.error(f"Failed: {res.text if res else 'Unknown'}")

    with c2:
        st.subheader("Preview")
        components.html(f"{st.session_state.html_content}", height=600, scrolling=True)

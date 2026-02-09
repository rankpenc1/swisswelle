import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
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

st.set_page_config(page_title="SwissWelle V67", page_icon="🎯", layout="wide")

# --- CONFIG ---
def get_secret(key): return st.secrets.get(key, "")

default_gemini_key = get_secret("gemini_api_key")
default_groq_key = get_secret("groq_api_key")
default_wp_url = get_secret("wp_url")
default_wc_ck = get_secret("wc_ck")
default_wc_cs = get_secret("wc_cs")
default_wp_user = get_secret("wp_user")
default_wp_app_pass = get_secret("wp_app_pass")

def reset_app():
    st.session_state.clear()
    st.rerun()

# State
if 'generated' not in st.session_state: st.session_state.generated = False
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'final_images' not in st.session_state: st.session_state.final_images = []
if 'p_name' not in st.session_state: st.session_state.p_name = ""

# --- SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V67")
    st.caption("Num Select + Selenium Scraper")
    if st.button("🔄 Start New Post", type="primary"): reset_app()
    
    with st.expander("🧠 AI Settings", expanded=True):
        ai_provider = st.radio("Provider:", ["Groq", "Gemini"], index=0)
        
        api_key = ""
        model_id = ""

        if ai_provider == "Groq":
            api_key = st.text_input("Groq Key", value=default_groq_key, type="password")
            model_id = "llama-3.3-70b-versatile"
            
        elif ai_provider == "Gemini":
            api_key = st.text_input("Gemini Key", value=default_gemini_key, type="password")
            model_id = "gemini-pro"

    with st.expander("Website Config", expanded=False):
        wp_url = st.text_input("WP URL", value=default_wp_url)
        wc_ck = st.text_input("CK", value=default_wc_ck, type="password")
        wc_cs = st.text_input("CS", value=default_wc_cs, type="password")
        wp_user = st.text_input("User", value=default_wp_user)
        wp_app_pass = st.text_input("Pass", value=default_wp_app_pass, type="password")

# --- SCRAPER (SELENIUM) ---
@st.cache_resource
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def clean_url(url):
    url = url.split('?')[0]
    url = re.sub(r'_\.(webp|avif)$', '', url)
    url = re.sub(r'\.jpg_.*$', '.jpg', url)
    if not url.endswith(('.jpg', '.png', '.webp', '.jpeg')):
        if 'alicdn' in url: url += '.jpg'
    return url

def scrape(url):
    driver = get_driver()
    candidates = set()
    title = ""
    try:
        driver.get(url)
        time.sleep(3) # Wait for JS
        
        title = driver.title.split('|')[0].strip()
        page_source = driver.page_source
        
        # 1. JSON Hunt
        json_matches = re.findall(r'imagePathList"?\s*[:=]\s*\[(.*?)\]', page_source)
        for match in json_matches:
            urls = re.findall(r'"(https?://[^"]+)"', match)
            for u in urls: candidates.add(clean_url(u))
            
        # 2. Regex Hunt
        raw_matches = re.findall(r'(https?://[^"\s\'>]+?\.alicdn\.com/[^"\s\'>]+?\.(?:jpg|jpeg|png|webp))', page_source)
        for m in raw_matches:
            if '32x32' not in m and '50x50' not in m: candidates.add(clean_url(m))
            
    except Exception as e:
        print(f"Scrape Error: {e}")
        
    return title, list(candidates)

# --- AI & UPLOAD ---

def extract_json(text):
    if not text: return None
    text = re.sub(r'```json', '', text).replace('```', '')
    try: return json.loads(text)
    except:
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match: return json.loads(match.group())
        except: pass
    return None

def ai_process(provider, key, model, p_name):
    instruction = """Role: Senior German Copywriter for 'swisswelle.ch'. Tone: Boho-Chic. 
    TASKS: 
    1. Write an engaging HTML description (h2, h3, ul, p).
    2. Write a RankMath SEO Meta Description (German).
    Output JSON ONLY: { "html_content": "...", "meta_description": "..." }"""
    
    prompt = f"Product Name: {p_name}\n\n{instruction}"

    try:
        raw_response = ""
        if provider == "Groq":
            client = Groq(api_key=key)
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            raw_response = completion.choices[0].message.content
        elif provider == "Gemini":
            genai.configure(api_key=key)
            try:
                mod = genai.GenerativeModel("gemini-pro")
                res = mod.generate_content(prompt)
                raw_response = res.text
            except Exception as e: return {"error": str(e)}

        return extract_json(raw_response)
    except Exception as e: return {"error": str(e)}

def upload_to_wp(item, wp_url, user, password, p_name):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        # CLEAN FILENAME (No Numbers)
        safe_name = re.sub(r'[^a-zA-Z0-9]', '-', p_name[:20].lower())
        filename = f"{safe_name}-{int(time.time())}.jpg"
        
        if item['type'] == 'file':
            img_data = item['data'].getvalue()
        else:
            r = requests.get(item['data'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code != 200: return None, "DL Fail"
            img_data = r.content

        headers = {'Content-Disposition': f'attachment; filename={filename}','Content-Type': 'image/jpeg'}
        r = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password), verify=False)
        
        if r.status_code == 201:
            pid = r.json()['id']
            requests.post(f"{api_url}/{pid}", json={"alt_text": p_name, "title": p_name}, auth=HTTPBasicAuth(user, password), verify=False)
            return pid, None
        return None, r.text[:100]
    except Exception as e: return None, str(e)

def publish_product(title, desc, meta, feat_id, gallery_ids, wp_url, ck, cs):
    try:
        # Construct Image List: Featured First, then Gallery
        img_payload = [{"id": feat_id}] + [{"id": i} for i in gallery_ids if i != feat_id]
        
        data = {
            "name": title, "description": desc, "status": "draft", "type": "simple", "regular_price": "0.00",
            "images": img_payload,
            "meta_data": [{"key": "rank_math_description", "value": meta}, {"key": "rank_math_focus_keyword", "value": title}]
        }
        r = requests.post(f"{wp_url}/wp-json/wc/v3/products", auth=HTTPBasicAuth(ck, cs), json=data, verify=False)
        return r
    except Exception as e: return str(e)

# --- UI ---
if not st.session_state.generated:
    st.subheader("1. Product & Images")
    
    col_input, col_load = st.columns([2, 1])
    with col_input:
        url_input = st.text_input("AliExpress URL (Scrape Images)")
        p_name = st.text_input("Product Name", st.session_state.p_name)
    
    with col_load:
        st.write("")
        st.write("")
        if st.button("🔍 Scrape URL", type="primary"):
            if url_input:
                with st.spinner("Scraping with Selenium..."):
                    title, imgs = scrape(url_input)
                    if title: st.session_state.p_name = title
                    if imgs: 
                        st.session_state.final_images = [{'type': 'url', 'data': u} for u in imgs]
                        st.success(f"Found {len(imgs)} images!")
                    else: st.error("No images found (Site might be blocked).")
                st.rerun()

    # Upload Tab
    upl = st.file_uploader("Or Upload Manually", accept_multiple_files=True, type=['jpg','png','webp','jpeg'])
    if upl:
        # Add uploads to the list if not already there
        current_files = [x['data'].name for x in st.session_state.final_images if x['type'] == 'file']
        for f in upl:
            if f.name not in current_files:
                st.session_state.final_images.append({'type': 'file', 'data': f})

    # IMAGE PREVIEW GRID (BEFORE GENERATION)
    if st.session_state.final_images:
        st.divider()
        st.write(f"**Total Images: {len(st.session_state.final_images)}**")
        cols = st.columns(6)
        for i, item in enumerate(st.session_state.final_images):
            with cols[i % 6]:
                if item['type'] == 'file': st.image(item['data'], use_container_width=True)
                else: st.image(item['data'], use_container_width=True)
                # Remove Button
                if st.button(f"❌ {i+1}", key=f"del_{i}"):
                    st.session_state.final_images.pop(i)
                    st.rerun()

    st.divider()
    if st.button("📝 Generate Content", type="primary"):
        if not api_key: st.error("API Key Missing"); st.stop()
        if not st.session_state.p_name: st.error("Name Missing"); st.stop()
        
        with st.status("Writing..."):
            res = ai_process(ai_provider, api_key, model_id, st.session_state.p_name)
            if "error" in res: st.error(res['error'])
            else:
                st.session_state.html_content = res.get('html_content', '')
                st.session_state.meta_desc = res.get('meta_description', '')
                if st.session_state.html_content:
                    st.session_state.generated = True
                    st.rerun()

else:
    # --- PUBLISH SCREEN ---
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("🖼️ Select Featured Image")
        
        img_count = len(st.session_state.final_images)
        if img_count > 0:
            # 1. IMAGE NUMBERING DISPLAY
            cols = st.columns(4)
            for i, item in enumerate(st.session_state.final_images):
                with cols[i % 4]:
                    if item['type'] == 'file': st.image(item['data'], use_container_width=True)
                    else: st.image(item['data'], use_container_width=True)
                    st.caption(f"Image {i+1}") # Number Display
            
            st.divider()
            
            # 2. FEATURED IMAGE SELECTOR
            # Allow user to choose number (1 to N)
            options = list(range(1, img_count + 1))
            feat_num = st.selectbox("⭐ Select Featured Image Number", options, index=0)
            
            # 3. GALLERY SELECTION
            gallery_nums = st.multiselect("Select Gallery Images", options, default=options)
            
            if st.button("📤 Upload & Publish", type="primary"):
                # Logic: Isolate Featured vs Gallery
                feat_img = st.session_state.final_images[feat_num - 1]
                gallery_imgs = [st.session_state.final_images[i-1] for i in gallery_nums if i != feat_num]
                
                status = st.empty()
                progress = st.progress(0)
                
                # Upload Featured
                status.text(f"Uploading Featured Image ({feat_num})...")
                feat_id, err = upload_to_wp(feat_img, wp_url, wp_user, wp_app_pass, st.session_state.p_name)
                
                if not feat_id:
                    st.error(f"Featured Image Failed: {err}")
                    st.stop()
                
                # Upload Gallery
                gallery_ids = []
                total = len(gallery_imgs)
                for idx, img in enumerate(gallery_imgs):
                    status.text(f"Uploading Gallery {idx+1}/{total}...")
                    pid, err = upload_to_wp(img, wp_url, wp_user, wp_app_pass, st.session_state.p_name)
                    if pid: gallery_ids.append(pid)
                    progress.progress((idx+1)/total)
                
                # Publish
                status.text("Publishing to WordPress...")
                res = publish_product(
                    st.session_state.p_name,
                    st.session_state.html_content,
                    st.session_state.meta_desc,
                    feat_id, gallery_ids, wp_url, wc_ck, wc_cs
                )
                
                if isinstance(res, str): st.error(res)
                elif res.status_code == 201:
                    st.balloons()
                    st.success("✅ Done!")
                    st.markdown(f"[👉 Edit Post]({res.json().get('permalink')})")
                    if st.button("New"): reset_app()
                else: st.error(f"Error: {res.text}")

    with c2:
        st.subheader("📝 Content")
        # White Background Fix
        html_view = f"""<div style="background:white;color:black;padding:20px;">{st.session_state.html_content}</div>"""
        components.html(html_view, height=800, scrolling=True)

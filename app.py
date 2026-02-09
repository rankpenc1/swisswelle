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
from duckduckgo_search import DDGS
from PIL import Image
import io

st.set_page_config(page_title="SwissWelle V64", page_icon="🔙", layout="wide")

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
    st.title("🌿 SwissWelle V64")
    st.caption("Back to Basics + Upload")
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
            # Using the oldest stable model to avoid 404
            model_id = "gemini-1.5-flash" 

    with st.expander("Website Config", expanded=False):
        wp_url = st.text_input("WP URL", value=default_wp_url)
        wc_ck = st.text_input("CK", value=default_wc_ck, type="password")
        wc_cs = st.text_input("CS", value=default_wc_cs, type="password")
        wp_user = st.text_input("User", value=default_wp_user)
        wp_app_pass = st.text_input("Pass", value=default_wp_app_pass, type="password")

# --- FUNCTIONS ---

def get_page_title(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            if soup.title: return soup.title.string.split('|')[0].strip()
    except: pass
    return None

def clean_url(url):
    url = url.split('?')[0]
    url = re.sub(r'_\.(webp|avif)$', '', url)
    url = re.sub(r'\.jpg_.*$', '.jpg', url)
    if not url.endswith(('.jpg', '.png', '.webp', '.jpeg')):
        if 'alicdn' in url: url += '.jpg'
    return url

def scrape_images(url):
    candidates = set()
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            # Regex for Ali
            raw_matches = re.findall(r'(https?://[^"\s\'>]+?\.alicdn\.com/[^"\s\'>]+?\.(?:jpg|jpeg|png|webp))', r.text)
            for m in raw_matches:
                if '32x32' not in m and '50x50' not in m: candidates.add(clean_url(m))
    except: pass
    return list(candidates)

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
    2. Write RankMath SEO Meta Description.
    Output JSON ONLY: { "html_content": "...", "meta_description": "..." }"""
    
    prompt = f"Product: {p_name}\n\n{instruction}"

    try:
        if provider == "Groq":
            client = Groq(api_key=key)
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return extract_json(completion.choices[0].message.content)

        elif provider == "Gemini":
            genai.configure(api_key=key)
            # Try primary then fallback
            try:
                mod = genai.GenerativeModel("gemini-1.5-flash")
                res = mod.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
                return extract_json(res.text)
            except:
                mod = genai.GenerativeModel("gemini-pro")
                res = mod.generate_content(prompt)
                return extract_json(res.text)

    except Exception as e: return {"error": str(e)}

def upload_wp(item, wp_url, user, password, p_name):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        filename = f"img-{int(time.time())}.jpg"
        
        if item['type'] == 'file':
            img_data = item['data'].getvalue()
            filename = item['data'].name
        else:
            r = requests.get(item['data'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if r.status_code != 200: return None
            img_data = r.content

        headers = {'Content-Disposition': f'attachment; filename={filename}','Content-Type': 'image/jpeg'}
        r = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password), verify=False)
        
        if r.status_code == 201:
            pid = r.json()['id']
            requests.post(f"{api_url}/{pid}", json={"alt_text": p_name, "title": p_name}, auth=HTTPBasicAuth(user, password), verify=False)
            return pid
    except: pass
    return None

def publish(title, desc, meta, ids, wp_url, ck, cs):
    try:
        data = {
            "name": title, "description": desc, "status": "draft", "type": "simple",
            "images": [{"id": i} for i in ids],
            "meta_data": [{"key": "rank_math_description", "value": meta}, {"key": "rank_math_focus_keyword", "value": title}]
        }
        return requests.post(f"{wp_url}/wp-json/wc/v3/products", auth=HTTPBasicAuth(ck, cs), json=data, verify=False)
    except Exception as e: return str(e)

# --- UI ---
if not st.session_state.generated:
    st.subheader("1. Product Info")
    # Auto-detect logic within the input flow
    url_input = st.text_input("AliExpress URL (Optional - for Auto Title & Images)")
    p_name = st.text_input("Product Name", st.session_state.p_name)
    
    # Logic to fetch title if URL changes
    if url_input and not p_name:
        t = get_page_title(url_input)
        if t: 
            p_name = t
            st.info(f"Auto-detected: {t}")

    st.subheader("2. Images")
    tab1, tab2 = st.tabs(["🔗 From URL (Auto)", "📂 Upload Manually"])
    
    collected_images = []
    
    with tab1:
        if url_input:
            scraped = scrape_images(url_input)
            if scraped:
                st.success(f"Found {len(scraped)} images from URL")
                for s in scraped: collected_images.append({'type': 'url', 'data': s})
            else:
                st.warning("No images found in URL (Blocked?). Please upload manually below.")
    
    with tab2:
        upl = st.file_uploader("Upload Files", accept_multiple_files=True, type=['jpg','png','webp','jpeg'])
        if upl:
            for f in upl: collected_images.append({'type': 'file', 'data': f})

    if st.button("🚀 Generate", type="primary"):
        if not api_key: st.error("No API Key"); st.stop()
        if not p_name: st.error("No Product Name"); st.stop()
        
        st.session_state.p_name = p_name
        st.session_state.final_images = collected_images
        
        with st.status("Writing..."):
            res = ai_process(ai_provider, api_key, model_id, p_name)
            if "error" in res:
                st.error(res['error'])
            else:
                st.session_state.html_content = res.get('html_content', '')
                st.session_state.meta_desc = res.get('meta_description', '')
                if st.session_state.html_content:
                    st.session_state.generated = True
                    st.rerun()

else:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Select Images")
        # Selection Logic
        final_selection = []
        cols = st.columns(3)
        for i, item in enumerate(st.session_state.final_images):
            with cols[i%3]:
                if item['type'] == 'file': st.image(item['data'], use_container_width=True)
                else: st.image(item['data'], use_container_width=True)
                if st.checkbox("Keep", value=True, key=f"c{i}"):
                    final_selection.append(item)
        
        if st.button("📤 Publish"):
            ids = []
            bar = st.progress(0)
            for i, item in enumerate(final_selection):
                pid = upload_wp(item, wp_url, wp_user, wp_app_pass, st.session_state.p_name)
                if pid: ids.append(pid)
                bar.progress((i+1)/len(final_selection))
            
            if ids:
                res = publish(st.session_state.p_name, st.session_state.html_content, st.session_state.meta_desc, ids, wp_url, wc_ck, wc_cs)
                if isinstance(res, str): st.error(res)
                elif res.status_code == 201:
                    st.success("Published!")
                    st.markdown(f"[Link]({res.json().get('permalink')})")
                    if st.button("New"): reset_app()
                else: st.error(res.text)
            else: st.error("Upload failed")

    with c2:
        st.subheader("Content")
        components.html(st.session_state.html_content, height=600, scrolling=True)
        st.text_area("Code", st.session_state.html_content)

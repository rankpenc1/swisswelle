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

st.set_page_config(page_title="SwissWelle V60", page_icon="📂", layout="wide")

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

# Init Secrets (AgentRouter Removed)
default_gemini_key = get_secret("gemini_api_key")
default_groq_key = get_secret("groq_api_key")
default_wp_url = get_secret("wp_url")
default_wc_ck = get_secret("wc_ck")
default_wc_cs = get_secret("wc_cs")
default_wp_user = get_secret("wp_user")
default_wp_app_pass = get_secret("wp_app_pass")

def reset_app():
    for key in list(st.session_state.keys()):
        if key != 'password_correct': del st.session_state[key]
    st.rerun()

# Session State Init
for k in ['generated', 'html_content', 'meta_desc', 'image_map', 'p_name', 'uploaded_files_cache']:
    if k not in st.session_state: st.session_state[k] = None if k == 'p_name' else ""
if 'image_map' not in st.session_state or not isinstance(st.session_state.image_map, dict):
    st.session_state.image_map = {} # Stores URLs
if 'uploaded_files_cache' not in st.session_state or not isinstance(st.session_state.uploaded_files_cache, list):
    st.session_state.uploaded_files_cache = [] # Stores Uploaded Bytes

# --- SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V60")
    st.caption("Upload & Publish")
    if st.button("🔄 Start New Post", type="primary"): reset_app()
    
    with st.expander("🧠 AI Brain Settings", expanded=True):
        ai_provider = st.radio("Select AI Provider:", ["Groq", "Gemini"], index=0)
        
        api_key = ""
        valid_model = ""

        if ai_provider == "Gemini":
            api_key = st.text_input("Gemini Key", value=default_gemini_key, type="password")
            valid_model = "gemini-1.5-flash" # Will fallback to pro if fails
            
        elif ai_provider == "Groq":
            api_key = st.text_input("Groq Key", value=default_groq_key, type="password")
            valid_model = "llama-3.3-70b-versatile"

    with st.expander("Website Config", expanded=False):
        wp_url = st.text_input("WP URL", value=default_wp_url)
        wc_ck = st.text_input("CK", value=default_wc_ck, type="password")
        wc_cs = st.text_input("CS", value=default_wc_cs, type="password")
        wp_user = st.text_input("User", value=default_wp_user)
        wp_app_pass = st.text_input("Pass", value=default_wp_app_pass, type="password")

# --- CORE FUNCTIONS ---

def extract_json_safely(text):
    if not text: return None
    text = re.sub(r'```json', '', text)
    text = re.sub(r'```', '', text)
    try: return json.loads(text)
    except:
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match: return json.loads(match.group())
        except: pass
    return None

def ai_process(provider, key, model_id, p_name, text):
    # Context now relies mostly on Product Name since images are manual
    instruction = """Role: Senior German Copywriter for 'swisswelle.ch'. Tone: Boho-Chic. TASKS: 1. Write HTML description (h2, h3, ul, p). 2. Write RankMath SEO Meta Description."""
    data_context = f"Product: {p_name}\nContext: {text[:2000]}"
    output_format = """JSON OUTPUT ONLY: { "html_content": "...", "meta_description": "..." }"""
    final_prompt = f"{instruction}\n{data_context}\n{output_format}"

    raw_response = ""
    try:
        if provider == "Gemini":
            genai.configure(api_key=key)
            try:
                # Try Flash
                model = genai.GenerativeModel("gemini-1.5-flash")
                res = model.generate_content(final_prompt, generation_config={"response_mime_type": "application/json"})
                raw_response = res.text
            except:
                try:
                    # Fallback to Pro
                    model = genai.GenerativeModel("gemini-pro")
                    res = model.generate_content(final_prompt)
                    raw_response = res.text
                except Exception as e: return {"error": f"Gemini Error: {str(e)}"}

        elif provider == "Groq":
            client = Groq(api_key=key)
            response = client.chat.completions.create(
                model=model_id, 
                messages=[{"role": "user", "content": final_prompt}],
                response_format={ 'type': 'json_object' }
            )
            raw_response = response.choices[0].message.content

        parsed = extract_json_safely(raw_response)
        if parsed: return parsed
        else: return {"error": f"JSON Parse Failed. Raw: {raw_response[:500]}"}

    except Exception as e: return {"error": f"AI Error: {str(e)}"}

# --- UPLOAD TO WORDPRESS ---
def upload_media(file_obj, filename, wp_url, user, password, alt):
    try:
        # Determine if it's bytes (upload) or string (url)
        if isinstance(file_obj, str): # URL
            img_data = requests.get(file_obj, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).content
            fname = f"{alt[:10].replace(' ', '-').lower()}-{int(time.time())}.webp"
        else: # File Object
            img_data = file_obj.getvalue()
            fname = file_obj.name
            
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        headers = {
            'Content-Disposition': f'attachment; filename={fname}',
            'Content-Type': 'image/jpeg' # Defaulting to jpeg/webp logic handles most
        }
        
        r = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password), verify=False)
        
        if r.status_code == 201:
            pid = r.json()['id']
            # Set Alt Text
            requests.post(f"{api_url}/{pid}", json={"alt_text": alt, "title": alt}, auth=HTTPBasicAuth(user, password), verify=False)
            return pid, None
        return None, f"Status {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return None, str(e)

def publish(title, desc, meta, feat_id, gallery_ids, wp_url, ck, cs):
    try:
        wcapi = API(url=wp_url, consumer_key=ck, consumer_secret=cs, version="wc/v3", timeout=60, verify_ssl=False)
        images = [{"id": feat_id}] + [{"id": i} for i in gallery_ids if i != feat_id]
        data = {
            "name": title, "description": desc, "status": "draft", "images": images,
            "type": "simple", "regular_price": "0.00",
            "meta_data": [{"key": "rank_math_description", "value": meta}, {"key": "rank_math_focus_keyword", "value": title}]
        }
        return wcapi.post("products", data)
    except Exception as e: return f"Publish Error: {str(e)}"

# --- UI ---
if not st.session_state.generated:
    st.session_state.p_name = st.text_input("Product Name", st.session_state.p_name if st.session_state.p_name else "")
    
    # 1. FILE UPLOADER
    uploaded_files = st.file_uploader("📂 Upload Images (Bulk)", accept_multiple_files=True, type=['png', 'jpg', 'jpeg', 'webp'])
    
    # 2. MANUAL URLS
    manual_urls = st.text_area("🔗 Paste Image URLs (Optional)", height=70, placeholder="https://example.com/image1.jpg")
    
    if st.button("🚀 Generate Content", type="primary"):
        if not api_key: st.error("No API Key"); st.stop()
        if not st.session_state.p_name: st.error("Please enter Product Name"); st.stop()
        if not uploaded_files and not manual_urls.strip(): st.error("Please upload images or paste URLs"); st.stop()
        
        with st.status(f"Processing...", expanded=True) as s:
            # Store inputs in session state for the next step
            st.session_state.uploaded_files_cache = uploaded_files
            
            # Parse URLs
            url_list = [u.strip() for u in manual_urls.split('\n') if u.strip()]
            for u in url_list: st.session_state.image_map[u] = "url"
            
            s.write(f"📸 Received {len(uploaded_files)} files and {len(url_list)} URLs")
            s.write(f"🧠 {ai_provider} is writing...")
            
            # Call AI
            res = ai_process(ai_provider, api_key, valid_model, st.session_state.p_name, f"Product: {st.session_state.p_name}")
            
            if "error" in res: 
                st.error(res['error'])
            else:
                st.session_state.html_content = res.get('html_content', '')
                st.session_state.meta_desc = res.get('meta_description', '')
                st.session_state.generated = True
                st.rerun()

else:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Select Images to Publish")
        
        # Merge sources for selection
        # 1. Uploaded Files
        all_items = [] # (type, data, display_key)
        
        for f in st.session_state.uploaded_files_cache:
            all_items.append(('file', f, f.name))
            
        # 2. URLs
        for u in st.session_state.image_map.keys():
            all_items.append(('url', u, u))
            
        # Selection UI
        if 'selections' not in st.session_state: st.session_state.selections = {}
        
        # Display Grid
        cols = st.columns(3)
        valid_selections = []
        
        for i, (type_, data, key) in enumerate(all_items):
            with cols[i % 3]:
                if type_ == 'file':
                    st.image(data, use_container_width=True)
                else:
                    st.image(data, use_container_width=True)
                
                # Checkbox
                chk_key = f"chk_{i}"
                if st.checkbox("Select", value=True, key=chk_key):
                    valid_selections.append((type_, data))

        st.markdown("---")
        
        if valid_selections:
            # Featured Image Logic - Just pick the first selected for simplicity or add a selector
            st.write(f"✅ {len(valid_selections)} images selected for upload.")
            
            if st.button("📤 Publish to WordPress"):
                with st.spinner("Uploading images... This may take time."):
                    gallery_ids = []
                    feat_id = None
                    
                    progress_bar = st.progress(0)
                    
                    for idx, (type_, data) in enumerate(valid_selections):
                        # Upload
                        pid, err = upload_media(data, st.session_state.p_name, wp_url, wp_user, wp_app_pass, st.session_state.p_name)
                        
                        if pid:
                            gallery_ids.append(pid)
                            if idx == 0: feat_id = pid # First image is featured
                        else:
                            st.error(f"Failed to upload image {idx+1}: {err}")
                        
                        progress_bar.progress((idx + 1) / len(valid_selections))
                    
                    if feat_id:
                        res = publish(st.session_state.p_name, st.session_state.html_content, st.session_state.meta_desc, feat_id, gallery_ids, wp_url, wc_ck, wc_cs)
                        
                        if isinstance(res, str): st.error(res)
                        elif res.status_code == 201:
                            st.success("✅ Product Published Successfully!")
                            st.markdown(f"[👉 **Edit in WordPress**]({res.json().get('permalink')})")
                            if st.button("Start New"): reset_app()
                        else: st.error(f"Publish Failed: {res.text}")
                    else:
                        st.error("No images could be uploaded. Check WordPress credentials.")

    with c2:
        tab1, tab2 = st.tabs(["👁️ Visual Preview", "📋 HTML Code"])
        with tab1:
            if st.session_state.html_content:
                components.html(f"""<div style="background-color: white; color: black; padding: 20px; font-family: sans-serif;">{st.session_state.html_content}</div>""", height=800, scrolling=True)
        with tab2: st.text_area("Copy Code", value=st.session_state.html_content, height=800)

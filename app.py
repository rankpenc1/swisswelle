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

st.set_page_config(page_title="SwissWelle V65", page_icon="✨", layout="wide")

# --- 1. CONFIG & SECRETS ---
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

# Init Session State
if 'generated' not in st.session_state: st.session_state.generated = False
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'final_images' not in st.session_state: st.session_state.final_images = []
if 'p_name' not in st.session_state: st.session_state.p_name = ""

# --- SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V65")
    st.caption("Fixed UI & Upload")
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
            # Trying explicit model path to fix 404
            model_id = "models/gemini-1.5-flash" 

    with st.expander("Website Config", expanded=False):
        wp_url = st.text_input("WP URL", value=default_wp_url)
        wc_ck = st.text_input("CK", value=default_wc_ck, type="password")
        wc_cs = st.text_input("CS", value=default_wc_cs, type="password")
        wp_user = st.text_input("User", value=default_wp_user)
        wp_app_pass = st.text_input("Pass", value=default_wp_app_pass, type="password")

# --- FUNCTIONS ---

def extract_json(text):
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

def ai_process(provider, key, model, p_name):
    instruction = """Role: Senior German Copywriter for 'swisswelle.ch'. Tone: Boho-Chic. 
    TASKS: 
    1. Write an engaging HTML description (h2, h3, ul, p) for the product.
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
                gen_model = genai.GenerativeModel(model)
                response = gen_model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
                raw_response = response.text
            except Exception as e:
                # Fallback to older name style if V1beta fails
                try:
                    gen_model = genai.GenerativeModel("gemini-pro")
                    response = gen_model.generate_content(prompt)
                    raw_response = response.text
                except:
                    return {"error": f"Gemini Error: {str(e)}"}

        return extract_json(raw_response)

    except Exception as e:
        return {"error": f"Connection Error: {str(e)}"}

def upload_to_wp(item, wp_url, user, password, p_name):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        safe_name = re.sub(r'[^a-zA-Z0-9]', '-', p_name[:15])
        filename = f"{safe_name}-{int(time.time())}.jpg"
        
        # Determine Data Source
        if item['type'] == 'file':
            img_data = item['data'].getvalue()
            filename = item['data'].name
        else: # URL
            r = requests.get(item['data'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code != 200: return None, "Download Error"
            img_data = r.content

        headers = {
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': 'image/jpeg'
        }

        # 1. Upload File
        r = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password), verify=False)
        
        if r.status_code == 201:
            pid = r.json()['id']
            # 2. Update Alt Text
            requests.post(f"{api_url}/{pid}", json={"alt_text": p_name, "title": p_name}, auth=HTTPBasicAuth(user, password), verify=False)
            return pid, None
        
        return None, f"WP {r.status_code}: {r.text[:100]}"
        
    except Exception as e:
        return None, str(e)

def publish_product(title, desc, meta, image_ids, wp_url, ck, cs):
    try:
        data = {
            "name": title,
            "description": desc,
            "status": "draft",
            "type": "simple",
            "regular_price": "0.00",
            "images": [{"id": i} for i in image_ids],
            "meta_data": [
                {"key": "rank_math_description", "value": meta},
                {"key": "rank_math_focus_keyword", "value": title}
            ]
        }
        
        r = requests.post(
            f"{wp_url}/wp-json/wc/v3/products",
            auth=HTTPBasicAuth(ck, cs),
            json=data,
            verify=False
        )
        return r
    except Exception as e:
        return str(e)

# --- UI LOGIC ---

if not st.session_state.generated:
    st.subheader("1. Product Info")
    p_name = st.text_input("Product Name", st.session_state.p_name)
    
    st.subheader("2. Images")
    # TABS FOR UPLOAD VS URL
    tab1, tab2 = st.tabs(["📂 Upload (Recommended)", "🔗 From URL (If Scraper Works)"])
    
    files = []
    
    with tab1:
        upl = st.file_uploader("Drop images here", accept_multiple_files=True, type=['jpg','png','webp','jpeg', 'avif'])
        if upl: 
            st.info(f"✅ {len(upl)} files ready to upload")
            for f in upl: files.append({'type': 'file', 'data': f})
            
    with tab2:
        url_input = st.text_input("AliExpress URL (Optional auto-fetch)")
        if url_input:
            st.warning("⚠️ Scraper might fail due to AliExpress blocks. Use Upload tab if 0 images found.")
            # Simple regex scrape attempt
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                r = requests.get(url_input, headers=headers, timeout=5)
                matches = re.findall(r'(https?://[^"\s\'>]+?\.alicdn\.com/[^"\s\'>]+?\.(?:jpg|jpeg|png|webp))', r.text)
                found_urls = list(set(matches))
                if found_urls:
                    st.success(f"Found {len(found_urls)} images via URL")
                    for u in found_urls: files.append({'type': 'url', 'data': u})
                else:
                    st.error("No images found in URL. Please upload manually.")
            except: pass

    if st.button("🚀 Generate Description", type="primary"):
        if not api_key: st.error("Missing API Key"); st.stop()
        if not p_name: st.error("Missing Product Name"); st.stop()
        if not files: st.error("No images provided. Please Upload images first."); st.stop()
        
        st.session_state.p_name = p_name
        st.session_state.final_images = files
        
        with st.status("Writing Content...", expanded=True):
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
                    st.error("AI returned empty content.")

else:
    # --- REVIEW & PUBLISH (V52 Style Layout) ---
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("Select Images")
        
        # Selection Logic
        if 'selections' not in st.session_state: 
            st.session_state.selections = {i: True for i in range(len(st.session_state.final_images))}

        # Image Grid
        cols = st.columns(3)
        selected_indices = []
        
        for i, item in enumerate(st.session_state.final_images):
            with cols[i%3]:
                if item['type'] == 'file': st.image(item['data'], use_container_width=True)
                else: st.image(item['data'], use_container_width=True)
                
                # Checkbox
                is_selected = st.checkbox("Keep", value=st.session_state.selections.get(i, True), key=f"sel_{i}")
                st.session_state.selections[i] = is_selected
                if is_selected: selected_indices.append(i)
        
        st.markdown("---")
        
        if st.button("📤 Publish to WordPress", type="primary"):
            if not selected_indices: st.error("Select at least one image"); st.stop()
            
            uploaded_ids = []
            progress = st.progress(0)
            status = st.empty()
            
            total = len(selected_indices)
            for idx, i in enumerate(selected_indices):
                img = st.session_state.final_images[i]
                status.text(f"Uploading image {idx+1}/{total}...")
                
                pid, err = upload_to_wp(img, wp_url, wp_user, wp_app_pass, st.session_state.p_name)
                
                if pid: uploaded_ids.append(pid)
                else: st.warning(f"Failed img {idx+1}: {err}")
                
                progress.progress((idx+1)/total)
            
            if uploaded_ids:
                status.text("Creating Product Draft...")
                res = publish_product(
                    st.session_state.p_name,
                    st.session_state.html_content,
                    st.session_state.meta_desc,
                    uploaded_ids,
                    wp_url, wc_ck, wc_cs
                )
                
                if isinstance(res, str):
                    st.error(f"Publish Error: {res}")
                elif res.status_code == 201:
                    st.balloons()
                    st.success("✅ Published Successfully!")
                    st.markdown(f"### [👉 Edit in WordPress]({res.json().get('permalink')})")
                    if st.button("Start New"): reset_app()
                else:
                    st.error(f"WP Error {res.status_code}: {res.text}")
            else:
                st.error("No images could be uploaded. Check WP Credentials.")

    with c2:
        # --- PREVIEW UI FIX ---
        st.subheader("Content Preview")
        
        if st.session_state.html_content:
            tab_v, tab_c = st.tabs(["👁️ Visual Preview", "📋 HTML Code"])
            
            with tab_v:
                # IMPORTANT: Added White Background Style so text is visible on Dark Mode
                html_preview = f"""
                <div style="background-color: white; color: black; padding: 25px; border-radius: 5px; font-family: sans-serif;">
                    {st.session_state.html_content}
                </div>
                """
                components.html(html_preview, height=800, scrolling=True)
                
            with tab_c:
                st.text_area("Raw HTML", value=st.session_state.html_content, height=800)
        else:
            st.warning("No content generated.")

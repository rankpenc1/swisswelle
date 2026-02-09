import streamlit as st
import google.generativeai as genai
from groq import Groq
import json
import re
import time 
import requests
from requests.auth import HTTPBasicAuth
from PIL import Image
import io

st.set_page_config(page_title="SwissWelle V62", page_icon="📦", layout="wide")

# --- SECRETS ---
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

# Init State
if 'generated' not in st.session_state: st.session_state.generated = False
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'final_images' not in st.session_state: st.session_state.final_images = [] # Stores (type, data) tuples

# --- SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V62")
    st.caption("Bulk Upload & Publish")
    if st.button("🔄 Start New Post", type="primary"): reset_app()
    
    with st.expander("🧠 AI Brain Settings", expanded=True):
        ai_provider = st.radio("Select AI Provider:", ["Groq", "Gemini"], index=0)
        
        api_key = ""
        model_id = ""

        if ai_provider == "Groq":
            api_key = st.text_input("Groq Key", value=default_groq_key, type="password")
            model_id = "llama-3.3-70b-versatile"
            st.caption("⚡ Super Fast (Text Only)")
            
        elif ai_provider == "Gemini":
            api_key = st.text_input("Gemini Key", value=default_gemini_key, type="password")
            model_id = "gemini-1.5-flash"
            st.caption("🖼️ Can see images")

    with st.expander("Website Config", expanded=False):
        wp_url = st.text_input("WP URL", value=default_wp_url)
        wc_ck = st.text_input("CK", value=default_wc_ck, type="password")
        wc_cs = st.text_input("CS", value=default_wc_cs, type="password")
        wp_user = st.text_input("User", value=default_wp_user)
        wp_app_pass = st.text_input("Pass", value=default_wp_app_pass, type="password")

# --- FUNCTIONS ---

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

def ai_process(provider, key, model, p_name, images_data=None):
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
            gen_model = genai.GenerativeModel(model)
            
            # If we have images and Gemini supports vision, we could pass them.
            # For stability V62, we stick to text-based generation based on Title.
            response = gen_model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            raw_response = response.text

        return extract_json(raw_response)

    except Exception as e:
        return {"error": str(e)}

def upload_media_to_wp(item, wp_url, user, password, alt_text):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        filename = f"prod-{int(time.time())}.jpg"
        
        # Prepare Data
        if item['type'] == 'file':
            # It's an UploadedFile object
            img_data = item['data'].getvalue()
            filename = item['data'].name
        else:
            # It's a URL string
            r = requests.get(item['data'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code != 200: return None, "Download failed"
            img_data = r.content
            filename = f"{alt_text[:5].strip()}-{int(time.time())}.jpg"

        headers = {
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': 'image/jpeg' 
        }

        # Upload
        r = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password), verify=False)
        
        if r.status_code == 201:
            pid = r.json()['id']
            # Update Alt Text
            requests.post(f"{api_url}/{pid}", json={"alt_text": alt_text, "title": alt_text}, auth=HTTPBasicAuth(user, password), verify=False)
            return pid, None
        
        return None, f"WP Error {r.status_code}: {r.text[:100]}"
        
    except Exception as e:
        return None, str(e)

def publish_product(title, desc, meta, image_ids, wp_url, ck, cs):
    try:
        wcapi = requests.post(
            f"{wp_url}/wp-json/wc/v3/products",
            auth=HTTPBasicAuth(ck, cs),
            json={
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
            },
            verify=False
        )
        return wcapi
    except Exception as e:
        return str(e)

# --- MAIN UI ---

if not st.session_state.generated:
    st.subheader("1. Product Details")
    p_name = st.text_input("Product Name", "Boho Macrame Wall Hanging")
    
    st.subheader("2. Add Images")
    
    tab1, tab2 = st.tabs(["📂 Bulk Upload", "🔗 Paste URLs"])
    
    final_img_list = []
    
    with tab1:
        uploaded_files = st.file_uploader("Drop images here (Max 200MB)", accept_multiple_files=True, type=['png', 'jpg', 'jpeg', 'webp', 'avif'])
        if uploaded_files:
            st.success(f"{len(uploaded_files)} files loaded.")
            
    with tab2:
        url_text = st.text_area("Paste Image URLs (One per line)", height=150)
    
    if st.button("🚀 Generate & Prepare", type="primary"):
        if not api_key: st.error("API Key missing"); st.stop()
        if not p_name: st.error("Product Name missing"); st.stop()
        
        # Collect Images
        collected_images = []
        if uploaded_files:
            for f in uploaded_files: collected_images.append({'type': 'file', 'data': f})
        
        if url_text:
            urls = [u.strip() for u in url_text.split('\n') if u.strip()]
            for u in urls: collected_images.append({'type': 'url', 'data': u})
            
        if not collected_images:
            st.error("Please add at least one image (Upload or URL).")
            st.stop()
            
        st.session_state.final_images = collected_images
        st.session_state.p_name = p_name
        
        with st.status("Writing Content...", expanded=True):
            res = ai_process(ai_provider, api_key, model_id, p_name)
            
            if "error" in res:
                st.error(res['error'])
            else:
                st.session_state.html_content = res.get('html_content', '')
                st.session_state.meta_desc = res.get('meta_description', '')
                st.session_state.generated = True
                st.rerun()

else:
    # --- PREVIEW & PUBLISH SCREEN ---
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("📸 Review Images")
        st.write(f"Total Images: {len(st.session_state.final_images)}")
        
        # Show a few previews
        cols = st.columns(3)
        for i, img in enumerate(st.session_state.final_images[:6]):
            with cols[i%3]:
                if img['type'] == 'file': st.image(img['data'], use_container_width=True)
                else: st.image(img['data'], use_container_width=True)
        if len(st.session_state.final_images) > 6:
            st.info(f"...and {len(st.session_state.final_images)-6} more.")

        st.divider()
        
        if st.button("📤 Upload & Publish to WordPress", type="primary"):
            if not wp_url: st.error("WP Config Missing"); st.stop()
            
            uploaded_ids = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            total = len(st.session_state.final_images)
            
            for i, img in enumerate(st.session_state.final_images):
                status_text.text(f"Uploading image {i+1}/{total}...")
                
                pid, err = upload_media_to_wp(
                    img, 
                    st.session_state.get('wp_url'), 
                    st.session_state.get('wp_user'), 
                    st.session_state.get('wp_app_pass'), 
                    st.session_state.p_name
                )
                
                if pid: uploaded_ids.append(pid)
                else: st.warning(f"Failed img {i+1}: {err}")
                
                progress_bar.progress((i + 1) / total)
            
            if uploaded_ids:
                status_text.text("Creating Product Draft...")
                res = publish_product(
                    st.session_state.p_name,
                    st.session_state.html_content,
                    st.session_state.meta_desc,
                    uploaded_ids,
                    st.session_state.get('wp_url'),
                    st.session_state.get('wc_ck'),
                    st.session_state.get('wc_cs')
                )
                
                if isinstance(res, str):
                    st.error(f"Publish Error: {res}")
                elif res.status_code == 201:
                    st.balloons()
                    st.success("✅ Product Published!")
                    st.markdown(f"### [👉 Click to Edit in WordPress]({res.json().get('permalink')})")
                    if st.button("Start New Post"): reset_app()
                else:
                    st.error(f"API Error {res.status_code}: {res.text}")
            else:
                st.error("No images uploaded successfully.")

    with c2:
        st.subheader("📝 Content Preview")
        tab_view, tab_code = st.tabs(["👁️ Visual", "💻 HTML"])
        with tab_view:
            components.html(st.session_state.html_content, height=600, scrolling=True)
        with tab_code:
            st.text_area("HTML", value=st.session_state.html_content, height=600)

import streamlit as st
import streamlit.components.v1 as components
import json
import re
import time 
import requests
from requests.auth import HTTPBasicAuth
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image
import io

st.set_page_config(page_title="SwissWelle V74", page_icon="🛡️", layout="wide")

# --- SECRETS MANAGER ---
def get_secret(key):
    return st.secrets.get(key, "")

default_sambanova_key = get_secret("sambanova_api_key")
default_openrouter_key = get_secret("openrouter_api_key")
default_groq_key = get_secret("groq_api_key")

default_wp_url = get_secret("wp_url")
default_wc_ck = get_secret("wc_ck")
default_wc_cs = get_secret("wc_cs")
default_wp_user = get_secret("wp_user")
default_wp_app_pass = get_secret("wp_app_pass")

def reset_app():
    st.session_state.clear()
    st.rerun()

if 'generated' not in st.session_state: st.session_state.generated = False
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'final_images' not in st.session_state: st.session_state.final_images = []
if 'p_name' not in st.session_state: st.session_state.p_name = ""
if 'raw_response' not in st.session_state: st.session_state.raw_response = ""

# --- SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V74")
    st.caption("Crash-Proof AI")
    if st.button("🔄 Start New Post", type="primary"): reset_app()
    
    with st.expander("🧠 AI Settings", expanded=True):
        ai_provider = st.radio("Provider:", ["SambaNova", "OpenRouter", "Groq"], index=0)
        
        api_key = ""
        model_id = ""

        if ai_provider == "SambaNova":
            api_key = st.text_input("SambaNova Key", value=default_sambanova_key, type="password")
            # UPDATED STABLE MODEL
            model_id = st.text_input("Model ID", value="Meta-Llama-3.1-8B-Instruct") 

        elif ai_provider == "OpenRouter":
            api_key = st.text_input("OpenRouter Key", value=default_openrouter_key, type="password")
            # UPDATED STABLE MODEL (Gemini Experimental Free)
            model_id = st.text_input("Model ID", value="google/gemini-2.0-flash-exp:free")

        elif ai_provider == "Groq":
            api_key = st.text_input("Groq Key", value=default_groq_key, type="password")
            model_id = st.text_input("Model ID", value="llama-3.3-70b-versatile")

    with st.expander("Website Config", expanded=False):
        wp_url = st.text_input("WP URL", value=default_wp_url)
        wc_ck = st.text_input("CK", value=default_wc_ck, type="password")
        wc_cs = st.text_input("CS", value=default_wc_cs, type="password")
        wp_user = st.text_input("User", value=default_wp_user)
        wp_app_pass = st.text_input("Pass", value=default_wp_app_pass, type="password")

# --- SCRAPER (Unchanged) ---
@st.cache_resource
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def scrape(url):
    driver = get_driver()
    candidates = set()
    title = ""
    try:
        driver.get(url)
        time.sleep(2)
        title = driver.title.split('|')[0].strip()
        if "login" in title.lower() or "security" in title.lower():
            title = "Blocked"
        
        page_source = driver.page_source
        raw_matches = re.findall(r'(https?://[^"\s\'>]+?\.alicdn\.com/[^"\s\'>]+?\.(?:jpg|jpeg|png|webp))', page_source)
        for m in raw_matches:
            m = m.split('?')[0]
            if '32x32' not in m and '50x50' not in m and 'search' not in m:
                candidates.add(m)
    except: pass
    return title, list(candidates)

# --- AI ---
def safe_json_parse(text):
    """Never returns None, always a dict"""
    if not text: return {"error": "Empty response from AI"}
    
    # Cleaning
    clean_text = re.sub(r'```json', '', text)
    clean_text = re.sub(r'```', '', clean_text).strip()
    
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        # Try finding JSON blob
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match: return json.loads(match.group())
        except: pass
        
        return {"error": "JSON Parse Failed", "raw_output": text}

def ai_process(provider, key, model, p_name):
    instruction = """Role: Senior German Copywriter for 'swisswelle.ch'. Tone: Boho-Chic. 
    TASKS: 
    1. Write an engaging HTML description (h2, h3, ul, p).
    2. Write a RankMath SEO Meta Description.
    Output JSON ONLY: { "html_content": "...", "meta_description": "..." }"""
    
    prompt = f"Product: {p_name}\n\n{instruction}"
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    
    # OpenRouter Specifics
    if provider == "OpenRouter":
        headers["HTTP-Referer"] = "https://swisswelle.streamlit.app"
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    # Provider URLs
    url = ""
    if provider == "SambaNova":
        url = "https://api.sambanova.ai/v1/chat/completions"
        # SambaNova prefers system prompt for JSON instruction
        payload['messages'].insert(0, {"role": "system", "content": "You are a JSON generator. Output only valid JSON."})
    elif provider == "OpenRouter":
        url = "https://openrouter.ai/api/v1/chat/completions"
    elif provider == "Groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload["response_format"] = {"type": "json_object"}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if r.status_code == 200:
            try:
                content = r.json()['choices'][0]['message']['content']
                st.session_state.raw_response = content # Save raw for debugging
                return safe_json_parse(content)
            except Exception as e:
                return {"error": f"Structure Error: {str(e)}", "raw": r.text}
        else:
            return {"error": f"API Error {r.status_code}: {r.text}"}
            
    except Exception as e: return {"error": f"Connection Error: {str(e)}"}

# --- UPLOAD & PUBLISH ---
def upload_wp(item, wp_url, user, password, p_name):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        safe_name = re.sub(r'[^a-zA-Z0-9]', '-', p_name[:15].lower())
        filename = f"{safe_name}-{int(time.time())}.jpg"
        
        if item['type'] == 'file':
            img_data = item['data'].getvalue()
            filename = item['data'].name
        else:
            r = requests.get(item['data'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code != 200: return None, "DL Fail"
            img_data = r.content

        headers = {'Content-Disposition': f'attachment; filename={filename}', 'Content-Type': 'image/jpeg'}
        r = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password), verify=False)
        
        if r.status_code == 201:
            pid = r.json()['id']
            requests.post(f"{api_url}/{pid}", json={"alt_text": p_name, "title": p_name}, auth=HTTPBasicAuth(user, password), verify=False)
            return pid, None
        return None, r.text[:100]
    except Exception as e: return None, str(e)

def publish_product(title, desc, meta, feat_id, gallery_ids, wp_url, ck, cs):
    try:
        img_payload = [{"id": feat_id}] + [{"id": i} for i in gallery_ids if i != feat_id]
        data = {
            "name": title, "description": desc, "status": "draft", "type": "simple",
            "images": img_payload,
            "meta_data": [{"key": "rank_math_description", "value": meta}, {"key": "rank_math_focus_keyword", "value": title}]
        }
        return requests.post(f"{wp_url}/wp-json/wc/v3/products", auth=HTTPBasicAuth(ck, cs), json=data, verify=False)
    except Exception as e: return str(e)

# --- UI ---
if not st.session_state.generated:
    st.subheader("1. Product Info")
    col1, col2 = st.columns([3, 1])
    with col1:
        p_name = st.text_input("Product Name", st.session_state.p_name)
    
    st.subheader("2. Images")
    tab1, tab2 = st.tabs(["📂 Upload (Best)", "🔗 Scrape (Try)"])
    
    with tab2:
        url_input = st.text_input("AliExpress URL")
        if st.button("🔍 Scrape URL", type="primary"):
            if url_input:
                with st.spinner("Scraping..."):
                    t, imgs = scrape(url_input)
                    if "Blocked" in t:
                        st.error("AliExpress blocked the scraper. Please use Upload tab.")
                    else:
                        if t: st.session_state.p_name = t
                        if imgs:
                            for u in imgs: st.session_state.final_images.append({'type': 'url', 'data': u})
                            st.success(f"Found {len(imgs)} images")
                            st.rerun()
                        else: st.warning("No images found.")

    with tab1:
        upl = st.file_uploader("Drop images here", accept_multiple_files=True, type=['jpg','png','webp','jpeg'])
        if upl:
            existing_names = [x['data'].name for x in st.session_state.final_images if x['type'] == 'file']
            count = 0
            for f in upl:
                if f.name not in existing_names:
                    st.session_state.final_images.append({'type': 'file', 'data': f})
                    count += 1
            if count > 0: st.success(f"Added {count} images")

    # PREVIEW
    if st.session_state.final_images:
        st.divider()
        st.write(f"**Total: {len(st.session_state.final_images)}**")
        cols = st.columns(6)
        for i, item in enumerate(st.session_state.final_images):
            with cols[i % 6]:
                if item['type'] == 'file': st.image(item['data'], use_container_width=True)
                else: st.image(item['data'], use_container_width=True)
                if st.button("❌", key=f"del_{i}"):
                    st.session_state.final_images.pop(i)
                    st.rerun()

    st.divider()
    if st.button("🚀 Generate Content", type="primary"):
        if not api_key: st.error("No API Key found in Secrets!"); st.stop()
        if not p_name: st.error("No Product Name"); st.stop()
        st.session_state.p_name = p_name
        
        with st.status(f"Thinking with {ai_provider}..."):
            res = ai_process(ai_provider, api_key, model_id, p_name)
            
            # SAFE CHECK (Fixes TypeError)
            if res and "error" in res:
                st.error(res['error'])
                if "raw_output" in res:
                    st.warning("Raw Output from AI (Parsing Failed):")
                    st.code(res['raw_output'])
            else:
                st.session_state.html_content = res.get('html_content', 'No Content')
                st.session_state.meta_desc = res.get('meta_description', '')
                st.session_state.generated = True
                st.rerun()

else:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("🖼️ Select Images")
        img_list = st.session_state.final_images
        
        if 'selections' not in st.session_state:
            st.session_state.selections = {i: True for i in range(len(img_list))}

        cols = st.columns(4)
        for i, item in enumerate(img_list):
            with cols[i % 4]:
                if item['type'] == 'file': st.image(item['data'], use_container_width=True)
                else: st.image(item['data'], use_container_width=True)
                st.session_state.selections[i] = st.checkbox(f"Keep #{i+1}", value=st.session_state.selections[i], key=f"sel_{i}")

        selected_indices = [i for i, sel in st.session_state.selections.items() if sel]
        selected_images = [img_list[i] for i in selected_indices]
        
        st.divider()
        if len(selected_images) > 0:
            feat_idx = st.selectbox("⭐ Featured Image:", range(len(selected_images)), format_func=lambda x: f"Image #{selected_indices[x]+1}")
            st.image(selected_images[feat_idx]['data'] if selected_images[feat_idx]['type'] == 'file' else selected_images[feat_idx]['data'], width=150)

            if st.button("📤 Publish", type="primary"):
                feat_img_obj = selected_images[feat_idx]
                gallery_objs = [img for i, img in enumerate(selected_images) if i != feat_idx]
                
                status = st.empty()
                prog = st.progress(0)
                
                status.text("Uploading Featured...")
                feat_id, err = upload_wp(feat_img_obj, wp_url, wp_user, wp_app_pass, st.session_state.p_name)
                if not feat_id: st.error(f"Featured Failed: {err}"); st.stop()
                
                gallery_ids = []
                total = len(gallery_objs)
                for idx, img in enumerate(gallery_objs):
                    status.text(f"Uploading Gallery {idx+1}/{total}...")
                    pid, err = upload_wp(img, wp_url, wp_user, wp_app_pass, st.session_state.p_name)
                    if pid: gallery_ids.append(pid)
                    if total > 0: prog.progress((idx+1)/total)
                
                status.text("Publishing...")
                res = publish_product(st.session_state.p_name, st.session_state.html_content, st.session_state.meta_desc, feat_id, gallery_ids, wp_url, wc_ck, wc_cs)
                
                if isinstance(res, str): st.error(res)
                elif res.status_code == 201:
                    st.balloons()
                    st.success("✅ Published!")
                    st.markdown(f"[👉 **Click to Edit**]({res.json().get('permalink')})")
                    if st.button("New Post"): reset_app()
                else: st.error(res.text)
        else: st.warning("Select images first.")

    with c2:
        st.subheader("📝 Content")
        if st.session_state.html_content:
            html_prev = f"""<div style="background:white; color:black; padding:20px; border-radius:8px;">{st.session_state.html_content}</div>"""
            components.html(html_prev, height=800, scrolling=True)
        else:
            st.warning("No content generated")

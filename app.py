import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
import google.generativeai as genai
from groq import Groq
import json
import re
import time 
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from requests.auth import HTTPBasicAuth
from duckduckgo_search import DDGS

st.set_page_config(page_title="SwissWelle V55", page_icon="🚀", layout="wide")

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
default_gemini_key = get_secret("gemini_api_key")
default_agentrouter_key = get_secret("agentrouter_api_key")
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

for k in ['generated', 'html_content', 'meta_desc', 'image_map', 'p_name', 'raw_ai_response']:
    if k not in st.session_state: st.session_state[k] = None if k == 'p_name' else ""
if 'image_map' not in st.session_state or not isinstance(st.session_state.image_map, dict):
    st.session_state.image_map = {}

# --- SIDEBAR ---
with st.sidebar:
    st.title("🌿 SwissWelle V55")
    st.caption("Raw Requests (No Library Error)")
    if st.button("🔄 Start New Post", type="primary"): reset_app()
    
    with st.expander("🧠 AI Brain Settings", expanded=True):
        ai_provider = st.radio("Select AI Provider:", ["AgentRouter", "Gemini", "Groq"], index=0)
        
        api_key = ""
        valid_model = ""

        if ai_provider == "AgentRouter":
            api_key = st.text_input("AgentRouter Token", value=default_agentrouter_key, type="password")
            valid_model = st.text_input("Model Name", value="deepseek-v3") 
            st.caption("Using Manual HTTP Request")

        elif ai_provider == "Gemini":
            api_key = st.text_input("Gemini Key", value=default_gemini_key, type="password")
            valid_model = "gemini-2.0-flash-exp"
            
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

def get_images_from_search(query):
    """Reliable Image Search via DuckDuckGo"""
    try:
        with DDGS() as ddgs:
            # We search specifically for the product name
            results = list(ddgs.images(f"{query} aliexpress product", max_results=20))
            return [r['image'] for r in results]
    except: return []

def get_page_title(url):
    """Attempt to get real product title to fix bad image search"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            if soup.title:
                t = soup.title.string
                t = re.sub(r' \| .*', '', t)
                t = re.sub(r' - .*', '', t)
                return t.strip()
    except: pass
    return None

def scrape(url, current_p_name):
    # 1. Auto-Detect Name if possible
    detected_name = get_page_title(url)
    
    # Use detected name if user field is empty or generic
    search_query = current_p_name
    if detected_name and (not current_p_name or len(current_p_name) < 3):
        search_query = detected_name
        st.session_state.p_name = detected_name
        st.toast(f"✅ Title Detected: {detected_name}")

    # 2. Search Images using the BEST available name
    st.toast(f"🔍 Searching images for: {search_query}", icon="📸")
    images = get_images_from_search(search_query)
    
    return search_query, list(set(images))

def extract_json_safely(text):
    if not text: return None
    # Strip Markdown
    text = re.sub(r'```json', '', text)
    text = re.sub(r'```', '', text)
    try:
        return json.loads(text)
    except:
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match: return json.loads(match.group())
        except: pass
    return None

def ai_process(provider, key, model_id, p_name, text, imgs):
    
    instruction = """Role: Senior German Copywriter for 'swisswelle.ch'. Tone: Boho-Chic. TASKS: 1. Write HTML description (h2, h3, ul, p). 2. Write RankMath SEO Meta Description. 3. Select 15-20 BEST images. Rename with German keywords."""
    data_context = f"Product: {p_name}\nImages found: {len(imgs)}\nList: {imgs[:400]}\nContext: {text[:50000]}"
    output_format = """JSON OUTPUT ONLY: { "html_content": "...", "meta_description": "...", "image_map": { "original_url": "german-name" } }"""
    final_prompt = f"{instruction}\n{data_context}\n{output_format}"

    raw_response = ""
    try:
        if provider == "AgentRouter":
            # --- MANUAL REQUESTS (The Fix) ---
            # No 'openai' library wrapping. Just pure JSON.
            url = "https://agentrouter.org/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": final_prompt}],
                "response_format": { "type": "json_object" }
            }
            
            r = requests.post(url, json=payload, headers=headers, timeout=120)
            
            if r.status_code == 200:
                data = r.json() # Parse JSON response
                # DIRECT DICTIONARY ACCESS - No .choices attribute
                raw_response = data['choices'][0]['message']['content']
            else:
                return {"error": f"AgentRouter HTTP Error {r.status_code}: {r.text}"}

        elif provider == "Gemini":
            genai.configure(api_key=key)
            try:
                model = genai.GenerativeModel("gemini-2.0-flash-exp")
                res = model.generate_content(final_prompt, generation_config={"response_mime_type": "application/json"})
                raw_response = res.text
            except:
                model = genai.GenerativeModel("gemini-1.5-flash")
                res = model.generate_content(final_prompt, generation_config={"response_mime_type": "application/json"})
                raw_response = res.text

        elif provider == "Groq":
            client = Groq(api_key=key)
            response = client.chat.completions.create(
                model=model_id, 
                messages=[{"role": "user", "content": final_prompt}],
                response_format={ 'type': 'json_object' }
            )
            raw_response = response.choices[0].message.content

        # Save & Parse
        st.session_state.raw_ai_response = raw_response
        parsed = extract_json_safely(raw_response)
        
        if parsed: return parsed
        else: return {"error": "JSON Parse Failed. See 'Raw AI Response' tab."}

    except Exception as e: return {"error": f"Critical Error: {str(e)}"}

# --- UPLOAD & PUBLISH ---
def upload_image(url, wp_url, user, password, alt):
    try:
        img_data = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).content
        filename = f"{alt.replace(' ', '-').lower()}.webp"
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        headers = {'Content-Disposition': f'attachment; filename={filename}', 'Content-Type': 'image/webp'}
        
        r = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password), verify=False)
        
        if r.status_code == 201:
            pid = r.json()['id']
            requests.post(f"{api_url}/{pid}", json={"alt_text": alt, "title": alt}, auth=HTTPBasicAuth(user, password), verify=False)
            return pid, None
        else:
            return None, f"Upload Failed ({r.status_code}): {r.text[:100]}"
    except Exception as e:
        return None, f"Upload Error: {str(e)}"

def publish(title, desc, meta, feat_id, gallery_ids, wp_url, ck, cs):
    try:
        wcapi = API(url=wp_url, consumer_key=ck, consumer_secret=cs, version="wc/v3", timeout=60, verify_ssl=False)
        valid_gallery = [{"id": i} for i in gallery_ids if i is not None]
        images_payload = []
        if feat_id: images_payload.append({"id": feat_id})
        images_payload.extend([img for img in valid_gallery if img['id'] != feat_id])
        
        data = {
            "name": title, "description": desc, "status": "draft", "images": images_payload,
            "type": "simple", "regular_price": "0.00",
            "meta_data": [{"key": "rank_math_description", "value": meta}, {"key": "rank_math_focus_keyword", "value": title}]
        }
        return wcapi.post("products", data)
    except Exception as e:
        return f"Publish Connection Error: {str(e)}"

# --- UI ---
if not st.session_state.generated:
    st.session_state.p_name = st.text_input("Product Name (Leave empty to Auto-Detect)", st.session_state.p_name if st.session_state.p_name else "")
    urls_input = st.text_area("AliExpress/Amazon URLs", height=100)
    
    if st.button("🚀 Generate Content", type="primary"):
        if not api_key: st.error("No API Key"); st.stop()
        
        with st.status(f"Working with {ai_provider}...", expanded=True) as s:
            urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
            
            full_text = ""
            all_imgs = []
            
            for u in urls:
                s.write(f"🔍 Analyzing URL...")
                detected_name, i = scrape(u, st.session_state.p_name)
                
                if detected_name:
                    st.session_state.p_name = detected_name
                
                full_text += f"Product: {st.session_state.p_name}. URL: {u}\n"
                all_imgs.extend(i)
            
            unique_imgs = list(set(all_imgs))
            s.write(f"📸 Total images found: {len(unique_imgs)}")
            
            if len(unique_imgs) == 0:
                st.error("❌ No images found. URL might be fully blocked or Name detection failed.")
                st.stop()
                
            s.write(f"🧠 {ai_provider} ({valid_model}) is writing...")
            
            res = ai_process(ai_provider, api_key, valid_model, st.session_state.p_name, full_text, unique_imgs)
            
            if "error" in res: 
                st.error(res['error'])
                if st.session_state.raw_ai_response:
                    with st.expander("🔴 Raw AI Response (Debug)"):
                        st.code(st.session_state.raw_ai_response)
            else:
                st.session_state.html_content = res.get('html_content', 'No content')
                st.session_state.meta_desc = res.get('meta_description', '')
                st.session_state.image_map = res.get('image_map', {})
                st.session_state.generated = True
                st.rerun()

else:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Select Images")
        img_urls = list(st.session_state.image_map.keys())
        if 'selections' not in st.session_state: st.session_state.selections = {u: True for u in img_urls}
        
        cols = st.columns(3)
        for i, u in enumerate(img_urls):
            with cols[i%3]:
                st.image(u)
                st.session_state.selections[u] = st.checkbox("Keep", value=st.session_state.selections.get(u, True), key=f"c{i}")
        
        final_imgs = [u for u, s in st.session_state.selections.items() if s]
        st.markdown("---")
        feat_img = st.selectbox("Featured Image", final_imgs) if final_imgs else None
        
        if st.button("📤 Publish Draft"):
            with st.spinner("Processing..."):
                error_log = []
                st.write("Uploading Featured Image...")
                alt = st.session_state.image_map.get(feat_img, st.session_state.p_name)
                feat_id, err = upload_image(feat_img, wp_url, wp_user, wp_app_pass, alt)
                if err: error_log.append(f"Featured: {err}")
                
                gallery_ids = []
                bar = st.progress(0)
                for i, u in enumerate(final_imgs):
                    if u != feat_img:
                        alt = st.session_state.image_map.get(u, st.session_state.p_name)
                        pid, err = upload_image(u, wp_url, wp_user, wp_app_pass, alt)
                        if pid: gallery_ids.append(pid)
                        elif err: error_log.append(f"Img {i}: {err}")
                    bar.progress((i+1)/len(final_imgs))
                
                if error_log:
                    with st.expander("⚠️ Some images failed", expanded=False): st.write(error_log)
                
                if feat_id:
                    res = publish(st.session_state.p_name, st.session_state.html_content, st.session_state.meta_desc, feat_id, gallery_ids, wp_url, wc_ck, wc_cs)
                    if isinstance(res, str): st.error(res)
                    elif res.status_code == 201:
                        st.success("✅ Published Successfully!")
                        st.markdown(f"[👉 **Edit in WordPress**]({res.json().get('permalink')})")
                        st.balloons()
                        if st.button("🔄 Start New Post"): reset_app()
                    else: st.error(f"Publish Failed: {res.text}")
                else: st.error(f"❌ Featured image failed.")

    with c2:
        tab1, tab2 = st.tabs(["👁️ Visual Preview", "📋 HTML Code", "🐛 Raw AI Response"])
        with tab1:
            if st.session_state.html_content:
                components.html(f"""<div style="background-color: white; color: black; padding: 20px; font-family: sans-serif;">{st.session_state.html_content}</div>""", height=800, scrolling=True)
            else: st.warning("No content.")
        with tab2: st.text_area("Copy Code", value=st.session_state.html_content, height=800)
        with tab3: st.text(st.session_state.get('raw_ai_response', 'No data'))

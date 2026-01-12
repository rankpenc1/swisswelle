# @title ৩৮. সুইসওয়েলে V28 (এরর ফ্রি + সুপার ফাস্ট)
import subprocess
import sys
import time # <--- FIXED: Added globally for Colab
import os
import re

# 1. Install Libraries
print("⚙️ সিস্টেম রেডি করা হচ্ছে... (একটু ধৈর্য ধরুন)")
subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "google-generativeai", "streamlit", "beautifulsoup4", "Pillow", "requests", "fake-useragent", "cloudscraper", "woocommerce"])

# 2. Write App File
app_code = r'''
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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="SwissWelle V28", page_icon="🇨🇭", layout="wide")

# Session State
if 'generated' not in st.session_state: st.session_state.generated = False
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'image_map' not in st.session_state: st.session_state.image_map = {}
if 'p_name' not in st.session_state: st.session_state.p_name = ""

# --- SIDEBAR ---
with st.sidebar:
    st.title("🇨🇭 SwissWelle V28")
    
    with st.expander("1. AI Settings", expanded=True):
        api_key = st.text_input("Gemini API Key", type="password")
        valid_model = None
        if api_key:
            try:
                genai.configure(api_key=api_key)
                models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                preferred = ['models/gemini-1.5-pro', 'models/gemini-1.5-flash', 'models/gemini-pro']
                valid_model = next((m for p in preferred for m in models if p in m), models[0] if models else None)
                if valid_model: st.success(f"✅ Brain: {valid_model.split('/')[-1]}")
            except: pass

    with st.expander("2. Website Connection", expanded=True):
        wp_url = st.text_input("Website URL", value="https://swisswelle.ch")
        wc_ck = st.text_input("Consumer Key (CK)", type="password")
        wc_cs = st.text_input("Consumer Secret (CS)", type="password")
        
        st.info("WP Admin (For Images):")
        wp_user = st.text_input("Username")
        wp_app_pass = st.text_input("App Password", type="password")
        
        if st.button("🔌 Test Connection"):
            if not (wp_url and wc_ck and wc_cs):
                st.error("❌ Fill all fields!")
            else:
                try:
                    wcapi = API(url=wp_url, consumer_key=wc_ck, consumer_secret=wc_cs, version="wc/v3", timeout=15)
                    r = wcapi.get("products", params={"per_page": 1})
                    if r.status_code == 200: st.success("✅ WooCommerce Connected!")
                    else: st.error(f"❌ WC Error: {r.status_code}")
                    
                    if wp_user and wp_app_pass:
                        r2 = requests.get(f"{wp_url}/wp-json/wp/v2/users/me", auth=HTTPBasicAuth(wp_user, wp_app_pass), verify=False)
                        if r2.status_code == 200: st.success("✅ Image Upload Auth OK!")
                        else: st.error(f"❌ Image Auth Error: {r2.status_code}")
                except Exception as e: st.error(f"Error: {e}")

# --- LOGIC ---
def clean_url(url):
    url = re.sub(r'\?v=.*', '', url)
    if 'aliexpress' in url: url = re.sub(r'_\d+x\d+\.(jpg|png|webp).*', '.\g<1>', url)
    if 'shopify' in url or 'amazon' in url: return re.sub(r'_(small|thumb|medium|large|compact|\d+x\d+)', '', url).split('?')[0]
    return url

def get_images(soup, url):
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
                if any(ext in v.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    candidates.add(clean_url(v))
    final = []
    for c in candidates:
        if any(x in c.lower() for x in ['icon', 'logo', 'avatar', 'gif', 'svg', 'blank', 'star', 'review', 'pixel']): continue
        if c.startswith('//'): c = 'https:' + c
        if c.startswith('http'): final.append(c)
    return list(set(final))

def scrape(url):
    try:
        scraper = cloudscraper.create_scraper()
        time.sleep(2)
        r = scraper.get(url, timeout=20)
        soup = BeautifulSoup(r.content, 'html.parser')
        for s in soup(["script", "style", "nav", "footer"]): s.extract()
        return soup.get_text(separator=' ', strip=True)[:30000], get_images(BeautifulSoup(r.content, 'html.parser'), url)
    except: return "", []

def ai_process(key, model_name, p_name, text, imgs):
    genai.configure(api_key=key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""Role: Expert German SEO Copywriter for 'swisswelle.ch'.
Task: Write a high-converting product description.

RULES:
1. Language: German (Human, Natural).
2. NO Em-Dashes. Short Sentences (<20 words). Short Paragraphs (<50 words).
3. Format: HTML (h2, h3, ul, p).

IMAGES TASK:
- Found {len(imgs)} candidates.
- Select 15-20 BEST images.
- Rename with German LSI keywords (NO EXTENSIONS).

CANDIDATE IMAGES LIST:
{imgs[:400]}

Input Product: {p_name}
Context: {text[:50000]}

Output JSON: {{ "html_content": "...", "image_map": {{ "original_url": "german-keyword-name" }} }}"""
    
    try:
        res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(res.text)
    except Exception as e: return {"error": str(e)}

# --- UPLOAD FUNCTION ---
def upload_image_to_wp(filepath, wp_url, user, app_pass, alt_text):
    import requests
    from requests.auth import HTTPBasicAuth
    
    url = f"{wp_url}/wp-json/wp/v2/media"
    filename = os.path.basename(filepath)
    with open(filepath, 'rb') as img: media_data = img.read()
    
    headers = {'Content-Disposition': f'attachment; filename={filename}', 'Content-Type': 'image/webp', 'User-Agent': 'Mozilla/5.0'}
    
    try:
        r = requests.post(url, data=media_data, headers=headers, auth=HTTPBasicAuth(user, app_pass), verify=False)
        if r.status_code == 201:
            img_id = r.json()['id']
            # Update ALT
            requests.post(f"{url}/{img_id}", json={"alt_text": alt_text, "title": alt_text}, auth=HTTPBasicAuth(user, app_pass), verify=False)
            return img_id
        else: return None
    except: return None

def publish_product(title, desc, img_ids, wp_url, ck, cs):
    from woocommerce import API
    wcapi = API(url=wp_url, consumer_key=ck, consumer_secret=cs, version="wc/v3", timeout=30, verify_ssl=False)
    data = {"name": title, "description": desc, "status": "draft", "images": [{"id": i_id} for i_id in img_ids], "type": "simple", "regular_price": "0.00"}
    try: return wcapi.post("products", data)
    except: return None

# --- UI ---
st.title("🇩🇪 SwissWelle V28 (Final)")

if not st.session_state.generated:
    st.session_state.p_name = st.text_input("Product Name", "SilberSchlinge")
    urls_input = st.text_area("Reference URLs", height=100)
    
    if st.button("🚀 Analyze & Generate", type="primary"):
        if not api_key: st.error("Need API Key"); st.stop()
        if not valid_model: st.error("No valid model"); st.stop()
        
        url_list = [u.strip() for u in re.split(r'[\s,]+', urls_input) if u.strip()]
        
        with st.status("Processing...", expanded=True) as s:
            full_text = ""
            all_imgs = []
            scraper_session = cloudscraper.create_scraper()
            
            for u in url_list:
                if u.startswith('http'):
                    t, i = scrape(u)
                    full_text += t + " "
                    all_imgs.extend(i)
                    s.write(f"✅ Scraped: {u}")
            
            unique_imgs = list(set(all_imgs))
            s.write(f"📸 Found {len(unique_imgs)} candidates...")
            
            res = ai_process(api_key, valid_model, st.session_state.p_name, full_text, unique_imgs)
            
            if "error" in res: st.error(res['error'])
            else:
                st.session_state.html_content = res['html_content']
                if os.path.exists('output'): shutil.rmtree('output')
                os.makedirs('output')
                
                final_map = {}
                s.write("🖼️ Optimizing Images...")
                for url, name in res.get('image_map', {}).items():
                    try:
                        r = scraper_session.get(url, timeout=10)
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
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("1. Review Images")
        select_all = st.checkbox("Select All", value=True)
        image_files = list(st.session_state.image_map.keys())
        if 'selections' not in st.session_state: st.session_state.selections = {img: True for img in image_files}
        if select_all:
             for img in image_files: st.session_state.selections[img] = True
        
        cols = st.columns(3)
        for idx, img_path in enumerate(image_files):
            with cols[idx % 3]:
                st.image(img_path, use_column_width=True)
                st.session_state.selections[img_path] = st.checkbox(f"#{idx+1}", value=st.session_state.selections.get(img_path, True), key=f"chk_{idx}")
        
        selected_files = [img for img, sel in st.session_state.selections.items() if sel]
        st.info(f"Publishing {len(selected_files)} images.")

        st.markdown("---")
        if st.button("📤 Publish to Website", type="primary"):
            if not (wp_url and wc_ck and wc_cs and wp_user and wp_app_pass):
                st.error("Missing Details in Sidebar!")
            else:
                with st.spinner("Uploading..."):
                    ids = []
                    bar = st.progress(0)
                    for i, p in enumerate(selected_files):
                        alt = st.session_state.image_map.get(p, st.session_state.p_name)
                        pid = upload_image_to_wp(p, wp_url, wp_user, wp_app_pass, alt)
                        if pid: ids.append(pid)
                        bar.progress((i+1)/len(selected_files))
                    
                    res = publish_product(st.session_state.p_name, st.session_state.html_content, ids, wp_url, wc_ck, wc_cs)
                    if res and res.status_code == 201:
                        st.success("✅ Success! Product Drafted.")
                        st.markdown(f"[👉 View Draft]({res.json().get('permalink')})")
                        st.balloons()
                    else: st.error(f"Failed: {res.text if res else 'Unknown Error'}")

    with c2:
        st.subheader("2. Preview")
        components.html(f'<div style="background:white;padding:20px;color:black;">{st.session_state.html_content}</div>', height=800, scrolling=True)
'''

with open("app.py", "w", encoding='utf-8') as f:
    f.write(code)

# 3. Start Tunnel
print("🚀 অ্যাপ চালু হচ্ছে...")
subprocess.Popen(["streamlit", "run", "app.py", "--server.port=8501"])
time.sleep(3)
if not os.path.exists("cloudflared-linux-amd64"):
    subprocess.call(["wget", "-q", "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"])
    subprocess.call(["chmod", "+x", "cloudflared-linux-amd64"])
with open("tunnel.log", "w") as f:
    subprocess.Popen(["./cloudflared-linux-amd64", "tunnel", "--url", "http://localhost:8501"], stdout=f, stderr=f)
time.sleep(5)
found = False
for i in range(30):
    try:
        with open("tunnel.log", "r") as f:
            match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', f.read())
            if match:
                print(f"\n👇 নিচের লিংকে ক্লিক করুন:\n👉  {match.group(0)}  👈\n")
                found = True
                break
    except: pass
    time.sleep(2)
if not found: print("❌ লিংক পাওয়া যায়নি। দয়া করে আবার প্লে বাটন চাপুন।")
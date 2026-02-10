import streamlit as st
import streamlit.components.v1 as components
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

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="SwissWelle V-Final",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CUSTOM CSS FOR MODERN UI ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; }
    .stTextInput>div>div>input { border-radius: 8px; }
    div[data-testid="stImage"] { border-radius: 10px; overflow: hidden; border: 1px solid #333; }
    .img-label { text-align: center; font-weight: bold; margin-top: 5px; color: #00ff00; }
</style>
""", unsafe_allow_html=True)

# --- SECRETS ---
def get_secret(key): return st.secrets.get(key, "")

# --- SESSION STATE INIT ---
if 'final_images' not in st.session_state: st.session_state.final_images = []
if 'p_name' not in st.session_state: st.session_state.p_name = ""
if 'html_content' not in st.session_state: st.session_state.html_content = ""
if 'meta_desc' not in st.session_state: st.session_state.meta_desc = ""
if 'generated' not in st.session_state: st.session_state.generated = False

# --- FUNCTIONS ---

# 1. Scraper (Selenium based for AliExpress)
@st.cache_resource
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def scrape_images(url):
    driver = get_driver()
    candidates = set()
    title = ""
    try:
        driver.get(url)
        time.sleep(2.5)
        title = driver.title.split('|')[0].strip()
        if "login" in title.lower() or "security" in title.lower(): title = ""
        
        page_source = driver.page_source
        # Regex for AliExpress & General
        matches = re.findall(r'(https?://[^"\s\'>]+?\.alicdn\.com/[^"\s\'>]+?\.(?:jpg|jpeg|png|webp))', page_source)
        for m in matches:
            m = m.split('?')[0] # Clean params
            if '32x32' not in m and '50x50' not in m and 'search' not in m:
                candidates.add(m)
    except: pass
    return title, list(candidates)

# 2. AI Content Generator (German + Boho + SEO)
def generate_content(provider, api_key, p_name):
    # German & Boho Context Prompt
    prompt = f"""
    You are a Senior German Copywriter for 'SwissWelle.ch', a brand focusing on Boho-Chic lifestyle products.
    
    PRODUCT: {p_name}
    
    TASKS:
    1. Write a Product Title (German, SEO optimized).
    2. Write a RankMath SEO Meta Description (German, compelling, max 160 chars).
    3. Write a full HTML Product Description (German). 
       - Use <h2> for main headings.
       - Use <ul> for features.
       - Tone: Emotional, Artistic, Boho, High-quality.
       - Do NOT use <html>, <head>, or <body> tags. Just the inner content.
    
    OUTPUT FORMAT (Strict JSON):
    {{
        "seo_title": "...",
        "meta_description": "...",
        "html_content": "..."
    }}
    """
    
    try:
        if provider == "Groq":
            client = Groq(api_key=api_key)
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
            
        elif provider == "Gemini":
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash") # Using 1.5-flash as it's stable
            response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
            
    except Exception as e:
        return {"error": str(e)}

# 3. WordPress Uploader
def upload_to_wp(item, p_name, wp_url, user, password):
    try:
        api_url = f"{wp_url}/wp-json/wp/v2/media"
        # Create SEO Friendly German Filename
        clean_name = re.sub(r'[^a-zA-Z0-9]', '-', p_name).lower()
        filename = f"{clean_name}-{int(time.time())}.jpg"
        
        # Get Image Data
        if item['type'] == 'file':
            img_byte_arr = io.BytesIO()
            image = Image.open(item['data'])
            image = image.convert('RGB') # Convert all to JPG
            image.save(img_byte_arr, format='JPEG', quality=85)
            img_data = img_byte_arr.getvalue()
        else:
            r = requests.get(item['data'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code != 200: return None
            img_data = r.content

        # Upload
        headers = {
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': 'image/jpeg'
        }
        res = requests.post(api_url, data=img_data, headers=headers, auth=HTTPBasicAuth(user, password))
        
        if res.status_code == 201:
            pid = res.json()['id']
            # SEO: Update Alt Text & Title (German)
            update_data = {
                "alt_text": p_name,
                "title": p_name,
                "caption": p_name,
                "description": p_name
            }
            requests.post(f"{api_url}/{pid}", json=update_data, auth=HTTPBasicAuth(user, password))
            return pid
            
    except: return None
    return None

def publish_product(p_data, image_ids, feat_id, wp_url, ck, cs):
    # Construct Image Payload (Featured first)
    # Filter gallery images (exclude featured ID from gallery list to avoid dupes if logic fails, though list comp handles it)
    final_images = [{"id": feat_id}] + [{"id": i} for i in image_ids if i != feat_id]
    
    payload = {
        "name": p_data['seo_title'],
        "description": p_data['html_content'],
        "status": "draft",
        "type": "simple",
        "images": final_images,
        "meta_data": [
            {"key": "rank_math_title", "value": p_data['seo_title']},
            {"key": "rank_math_description", "value": p_data['meta_description']},
            {"key": "rank_math_focus_keyword", "value": p_data['seo_title']}
        ]
    }
    
    try:
        res = requests.post(
            f"{wp_url}/wp-json/wc/v3/products",
            auth=HTTPBasicAuth(ck, cs),
            json=payload
        )
        return res
    except Exception as e: return str(e)


# --- SIDEBAR UI ---
with st.sidebar:
    st.title("🌿 SwissWelle Admin")
    st.caption("Boho & German SEO Suite")
    
    if st.button("🔄 Reset / New Post", type="primary"):
        st.session_state.clear()
        st.rerun()
    
    with st.expander("⚙️ AI Settings", expanded=True):
        provider = st.radio("Select Brain:", ["Groq", "Gemini"])
        if provider == "Groq":
            api_key = st.text_input("Groq API Key", value=get_secret("groq_api_key"), type="password")
        else:
            api_key = st.text_input("Gemini API Key", value=get_secret("gemini_api_key"), type="password")

    with st.expander("🔌 Website Config", expanded=False):
        wp_url = st.text_input("WP URL", value=get_secret("wp_url"))
        wp_user = st.text_input("User", value=get_secret("wp_user"))
        wp_pass = st.text_input("Pass", value=get_secret("wp_app_pass"), type="password")

# --- MAIN UI ---

# SECTION 1: INPUTS
st.subheader("1. Product Data Source")
col1, col2 = st.columns([1, 1])

with col1:
    # 1.A URL Scrape
    url_input = st.text_input("🔗 Scrape from URL (AliExpress)")
    if st.button("🔍 Scrape Images"):
        if url_input:
            with st.spinner("Scraping..."):
                t, imgs = scrape_images(url_input)
                if t: st.session_state.p_name = t
                if imgs:
                    for i in imgs: st.session_state.final_images.append({'type': 'url', 'data': i})
                    st.success(f"Found {len(imgs)} images!")
                else: st.error("No images found. Try upload.")

with col2:
    # 1.B Bulk Upload
    upl_files = st.file_uploader("📂 Bulk Upload Images", accept_multiple_files=True)
    if upl_files:
        existing = [x['data'].name for x in st.session_state.final_images if x['type'] == 'file']
        count = 0
        for f in upl_files:
            if f.name not in existing:
                st.session_state.final_images.append({'type': 'file', 'data': f})
                count += 1
        if count > 0: st.success(f"Added {count} files")

# 1.C Bulk URL Input
with st.expander("🔗 Paste Bulk Image URLs (Optional)"):
    bulk_urls = st.text_area("One URL per line")
    if st.button("Add URLs"):
        if bulk_urls:
            urls = [u.strip() for u in bulk_urls.split('\n') if u.strip()]
            for u in urls:
                st.session_state.final_images.append({'type': 'url', 'data': u})
            st.success(f"Added {len(urls)} links")

# SECTION 2: IMAGE MANAGEMENT (GRID + NUMBERS)
st.divider()
st.subheader("2. Image Manager")
p_name_input = st.text_input("Product Name (Required)", value=st.session_state.p_name)
st.session_state.p_name = p_name_input

if st.session_state.final_images:
    st.info(f"Total Images: {len(st.session_state.final_images)}")
    
    # Custom Grid for Image Management
    cols = st.columns(6)
    for i, item in enumerate(st.session_state.final_images):
        with cols[i % 6]:
            # Display Image
            if item['type'] == 'file': 
                st.image(item['data'], use_container_width=True)
            else: 
                st.image(item['data'], use_container_width=True)
            
            # Number Label
            st.markdown(f"<div class='img-label'>#{i+1}</div>", unsafe_allow_html=True)
            
            # Delete Button
            if st.button(f"🗑️ Remove", key=f"del_{i}"):
                st.session_state.final_images.pop(i)
                st.rerun()

    st.divider()
    
    # SECTION 3: GENERATE & PUBLISH
    col_gen, col_pub = st.columns([1, 1])
    
    with col_gen:
        st.subheader("3. Generate Content (German/Boho)")
        if st.button("🚀 Generate AI Content", type="primary"):
            if not api_key or not st.session_state.p_name:
                st.error("Missing API Key or Product Name")
            else:
                with st.status("Thinking..."):
                    res = generate_content(provider, api_key, st.session_state.p_name)
                    if "error" in res:
                        st.error(res['error'])
                    else:
                        st.session_state.html_content = res.get('html_content', '')
                        st.session_state.meta_desc = res.get('meta_description', '')
                        st.session_state.seo_title = res.get('seo_title', st.session_state.p_name)
                        st.session_state.generated = True
                        st.rerun()

    with col_pub:
        st.subheader("4. Publish")
        if st.session_state.generated:
            # Featured Image Selector by Number
            total_imgs = len(st.session_state.final_images)
            feat_num = st.number_input("⭐ Enter Featured Image Number:", min_value=1, max_value=total_imgs, value=1)
            
            if st.button("📤 Upload & Publish to Site"):
                feat_idx = feat_num - 1
                feat_item = st.session_state.final_images[feat_idx]
                gallery_items = [x for i, x in enumerate(st.session_state.final_images) if i != feat_idx]
                
                status_box = st.status("Processing Uploads...")
                
                # Upload Featured
                status_box.write("Uploading Featured Image...")
                feat_id = upload_to_wp(feat_item, st.session_state.seo_title, get_secret("wp_url"), get_secret("wp_user"), get_secret("wp_app_pass"))
                
                if not feat_id:
                    status_box.update(label="Failed!", state="error")
                    st.error("Featured Image Upload Failed")
                else:
                    # Upload Gallery
                    gallery_ids = []
                    for idx, img in enumerate(gallery_items):
                        status_box.write(f"Uploading Gallery {idx+1}/{len(gallery_items)}...")
                        pid = upload_to_wp(img, st.session_state.seo_title, get_secret("wp_url"), get_secret("wp_user"), get_secret("wp_app_pass"))
                        if pid: gallery_ids.append(pid)
                    
                    # Publish Product
                    status_box.write("Creating Draft...")
                    p_data = {
                        "seo_title": st.session_state.seo_title,
                        "html_content": st.session_state.html_content,
                        "meta_description": st.session_state.meta_desc
                    }
                    
                    res = publish_product(p_data, gallery_ids, feat_id, get_secret("wp_url"), get_secret("wc_ck"), get_secret("wc_cs"))
                    
                    if hasattr(res, 'status_code') and res.status_code == 201:
                        status_box.update(label="Success!", state="complete")
                        st.balloons()
                        st.success("✅ Product Published Successfully!")
                        st.markdown(f"[👉 **Edit in WordPress**]({res.json().get('permalink')})")
                    else:
                        status_box.update(label="Error!", state="error")
                        st.error(f"Publish Failed: {res.text if hasattr(res, 'text') else res}")

# SECTION 4: PREVIEW
if st.session_state.generated:
    st.divider()
    st.subheader("📝 Content Preview")
    st.text_input("SEO Title", value=st.session_state.seo_title)
    st.text_area("Meta Description", value=st.session_state.meta_desc)
    components.html(f"""
        <div style="font-family: sans-serif; background: white; color: black; padding: 20px; border-radius: 8px;">
            {st.session_state.html_content}
        </div>
    """, height=600, scrolling=True)

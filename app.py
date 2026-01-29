import streamlit as st
import streamlit.components.v1 as components  # <--- FIXED: এই লাইনটি মিসিং ছিল
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

st.set_page_config(page_title="SwissWelle V35", page_icon="🛍️", layout="wide")

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
    st.title("🌿 SwissWelle V35")
    st.caption("Selenium + Auto AI + Preview Fix")
    
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
        Product

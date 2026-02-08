import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
import google.generativeai as genai
from groq import Groq
from io import BytesIO
import json, os, re, time, requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from woocommerce import API
from requests.auth import HTTPBasicAuth
from duckduckgo_search import DDGS

# ===============================
# BASIC CONFIG
# ===============================
st.set_page_config(page_title="SwissWelle V51", page_icon="🔥", layout="wide")

# ===============================
# SECURITY
# ===============================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    def password_entered():
        if st.session_state["password"] == st.secrets["app_login_password"]:
            st.session_state.password_correct = True
            del st.session_state["password"]
        else:
            st.session_state.password_correct = False

    if not st.session_state.password_correct:
        st.text_input("Admin Password", type="password",
                      on_change=password_entered, key="password")
        return False
    return True

if not check_password():
    st.stop()

def secret(k): return st.secrets[k] if k in st.secrets else ""

# ===============================
# SECRETS
# ===============================
default_gemini_key = secret("gemini_api_key")
default_agentrouter_key = secret("agentrouter_api_key")
default_groq_key = secret("groq_api_key")

default_wp_url = secret("wp_url")
default_wc_ck = secret("wc_ck")
default_wc_cs = secret("wc_cs")
default_wp_user = secret("wp_user")
default_wp_app_pass = secret("wp_app_pass")

# ===============================
# SESSION RESET
# ===============================
def reset_app():
    for k in list(st.session_state.keys()):
        if k != "password_correct":
            del st.session_state[k]
    st.rerun()

for k in ["generated", "html_content", "meta_desc", "image_map", "p_name"]:
    if k not in st.session_state:
        st.session_state[k] = "" if k != "p_name" else None

if "image_map" not in st.session_state:
    st.session_state.image_map = {}

# ===============================
# SIDEBAR
# ===============================
with st.sidebar:
    st.title("🌿 SwissWelle V51")
    st.caption("AliExpress + AgentRouter FIX")

    if st.button("🔄 New Post"):
        reset_app()

    with st.expander("🧠 AI Settings", expanded=True):
        ai_provider = st.radio("Provider", ["AgentRouter", "Gemini", "Groq"], index=0)

        api_key = ""
        model_id = ""

        if ai_provider == "AgentRouter":
            api_key = st.text_input("AgentRouter Key", default_agentrouter_key, type="password")
            model_id = st.text_input("Model", "deepseek-v3")
        elif ai_provider == "Gemini":
            api_key = st.text_input("Gemini Key", default_gemini_key, type="password")
            model_id = "gemini-1.5-flash"
        else:
            api_key = st.text_input("Groq Key", default_groq_key, type="password")
            model_id = "llama-3.3-70b-versatile"

    with st.expander("Website", expanded=False):
        wp_url = st.text_input("WP URL", default_wp_url)
        wc_ck = st.text_input("WC CK", default_wc_ck, type="password")
        wc_cs = st.text_input("WC CS", default_wc_cs, type="password")
        wp_user = st.text_input("WP User", default_wp_user)
        wp_app_pass = st.text_input("WP App Pass", default_wp_app_pass, type="password")

# ===============================
# SELENIUM DRIVER
# ===============================
@st.cache_resource
def get_driver():
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"
    )
    return webdriver.Chrome(options=opts)

# ===============================
# URL CLEAN
# ===============================
def clean_url(u):
    u = u.split("?")[0]
    m = re.search(r"(\.jpg|\.jpeg|\.png|\.webp)", u, re.I)
    return u[:m.end()] if m else u

# ===============================
# ALIEXPRESS IMAGE EXTRACTION
# ===============================
def extract_aliexpress_images(html):
    images = set()

    # grab all JS JSON blocks
    scripts = re.findall(r"{.*?}", html, re.DOTALL)

    for block in scripts:
        if "imagePathList" in block or "skuPropertyImagePath" in block:
            try:
                data = json.loads(block)
            except:
                continue

            # gallery
            img_module = data.get("imageModule", {})
            for img in img_module.get("imagePathList", []):
                images.add(clean_url("https:" + img if img.startswith("//") else img))

            # variations
            sku = data.get("skuModule", {})
            for prop in sku.get("productSKUPropertyList", []):
                for val in prop.get("propertyValueList", []):
                    pimg = val.get("skuPropertyImagePath")
                    if pimg:
                        images.add(clean_url("https:" + pimg if pimg.startswith("//") else pimg))

    return list(images)

# ===============================
# SCRAPER
# ===============================
def scrape(url, fallback):
    driver = get_driver()
    driver.get(url)
    time.sleep(6)
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    imgs = extract_aliexpress_images(html)

    if len(imgs) < 3:
        with DDGS() as ddgs:
            imgs += [r["image"] for r in ddgs.images(fallback, max_results=10)]

    text = soup.get_text(" ", strip=True)[:30000]
    return text, list(set(imgs))

# ===============================
# JSON FORCE PARSER
# ===============================
def force_json(txt):
    try:
        return json.loads(txt)
    except:
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except:
                pass
    return None

# ===============================
# AI PROCESSOR
# ===============================
def ai_process(provider, key, model, name, text, images):
    prompt = f"""
You are a senior German copywriter for swisswelle.ch.
Tone: Boho Chic.
Return ONLY valid JSON.

Product: {name}
Images: {images}

TASK:
1. Write HTML description (h2,h3,ul,p)
2. Write RankMath meta description
3. Select 15–20 best images and rename in German

FORMAT:
{{
  "html_content": "...",
  "meta_description": "...",
  "image_map": {{ "url": "german-name" }}
}}
"""

    if provider == "AgentRouter":
        r = requests.post(
            "https://agentrouter.org/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        raw = r.json()["choices"][0]["message"]["content"]

    elif provider == "Gemini":
        genai.configure(api_key=key)
        model = genai.GenerativeModel(model)
        raw = model.generate_content(prompt).text

    else:
        client = Groq(api_key=key)
        raw = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message.content

    parsed = force_json(raw)
    if not parsed:
        return {"error": "JSON parse failed"}
    return parsed

# ===============================
# UI – MAIN
# ===============================
if not st.session_state.generated:
    st.session_state.p_name = st.text_input("Product Name", "Boho Ring")
    urls = st.text_area("AliExpress URLs (one per line)", height=120)

    if st.button("🚀 Generate"):
        with st.status("Working...", expanded=True):
            text, imgs = "", []
            for u in urls.splitlines():
                if u.strip():
                    t, i = scrape(u.strip(), st.session_state.p_name)
                    text += t
                    imgs += i

            res = ai_process(ai_provider, api_key, model_id,
                             st.session_state.p_name, text, list(set(imgs)))

            if "error" in res:
                st.error(res["error"])
            else:
                st.session_state.html_content = res["html_content"]
                st.session_state.meta_desc = res["meta_description"]
                st.session_state.image_map = res["image_map"]
                st.session_state.generated = True
                st.rerun()

else:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Images")
        selections = {}
        for i, (u, alt) in enumerate(st.session_state.image_map.items()):
            st.image(u)
            selections[u] = st.checkbox("Use", True, key=f"img{i}")

    with c2:
        components.html(
            f"<div style='background:#fff;color:#000;padding:20px'>{st.session_state.html_content}</div>",
            height=800,
        )

import os
import base64
import re
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import mysql.connector
from playwright.sync_api import sync_playwright, TimeoutError
from urllib.parse import urlparse, urljoin
import time
import validators

app = Flask(__name__)
CORS(app)

# Koneksi ke database MySQL
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="webscr"
    )

# Buat folder untuk menyimpan gambar jika belum ada
IMAGE_DIR = "static/images"
if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)

# Fungsi untuk membersihkan text
def sanitize_text(text):
    if not text:
        return ""
    # Hapus karakter khusus dan trim whitespace
    return re.sub(r'[\r\n\t]+', ' ', text).strip()

# Fungsi untuk validasi URL
def is_valid_url(url):
    return validators.url(url)

# Fungsi untuk scraping data dari Airline Hydraulics
def scrape_airlinehyd(url, max_retries=2):
    retry_count = 0
    
    while retry_count <= max_retries:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Set timeout lebih lama
                page.set_default_timeout(30000)
                
                # Navigasi ke URL
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                
                # Tunggu halaman dimuat sepenuhnya
                page.wait_for_load_state("networkidle", timeout=30000)
                
                # Logging untuk debugging
                print(f"Scraping URL: {url}")
                
                # Coba beberapa XPath alternatif untuk judul
                title_selectors = [
                    "//h1",
                    "//h1[contains(@class, 'ItemDetailPage')]",
                    "//div[contains(@class, 'ItemDetailPage')]//h1",
                    "//div[contains(@class, 'product-title')]",
                    "//div[contains(@class, 'product-name')]//h1",
                    "//div[contains(@class, 'title')]",
                    "//span[contains(@class, 'title')]"
                ]
                
                title = None
                for selector in title_selectors:
                    try:
                        title_element = page.query_selector(selector)
                        if title_element:
                            title = title_element.text_content().strip()
                            print(f"Found title using {selector}: {title}")
                            break
                    except Exception as e:
                        print(f"Error with selector {selector}: {str(e)}")
                
                # Gunakan XPath yang baru untuk mengambil deskripsi
                desc_selector = "//div[@class='ItemDetailsBase__DivDetails-sc-1p4a5ao-0 dFnNJH']"  # XPath yang diperbarui
                description = None
                try:
                    desc_element = page.query_selector(desc_selector)
                    if desc_element:
                        description = desc_element.text_content().strip()
                        print(f"Found description using {desc_selector}: {description[:50]}...")
                except Exception as e:
                    print(f"Error with selector {desc_selector}: {str(e)}")
                
                # Ambil data stok menggunakan XPath baru
                stock_selector = "//div[@class='modal__CloseDiv-sc-msivc2-0 exnHdS']"
                stock = None
                try:
                    stock_element = page.query_selector(stock_selector)
                    if stock_element:
                        stock = stock_element.text_content().strip()
                        print(f"Found stock using {stock_selector}: {stock}")
                except Exception as e:
                    print(f"Error with selector {stock_selector}: {str(e)}")
                
                # Coba beberapa XPath alternatif untuk harga
                price_selectors = [
                    "//div[contains(@class, 'ItemDetailPage__DivPurchaseInfo')]",
                    "//div[contains(@class, 'ItemDetailPage__DivPriceInfo')]",
                    "//div[contains(@class, 'price')]",
                    "//span[contains(@class, 'price')]",
                    "//div[contains(@id, 'price')]",
                    "//span[contains(@id, 'price')]",
                    "//div[contains(@class, 'product-price')]",
                    "//p[@class='itemDetailPage__Pprice-sc-a657c5-9 eMZXEP']"  # XPath baru
                ]
                
                price = None
                for selector in price_selectors:
                    try:
                        price_element = page.query_selector(selector)
                        if price_element:
                            price = price_element.text_content().strip()
                            print(f"Found price using {selector}: {price}")
                            break
                    except Exception as e:
                        print(f"Error with selector {selector}: {str(e)}")
                
                # Cari gambar pertama dengan atribut title
                image_element = page.query_selector("img[title]")

                if image_element:
                    title = image_element.get_attribute("title")
                    print(f"Found image with title: {title}")

                    # Coba beberapa atribut berbeda untuk URL gambar
                    image_url = None
                    for attr in ["src", "data-src", "data-lazy-src", "data-original"]:
                        img_url = image_element.get_attribute(attr)
                        if img_url and not img_url.startswith("data:"):
                            image_url = img_url
                            print(f"Found image URL using {attr}: {image_url[:50]}...")

                    # Jika tidak ada URL gambar, tangkap screenshot
                    if not image_url:
                        print("No image found, capturing screenshot")
                        timestamp = int(time.time())
                        screenshot_path = f"{IMAGE_DIR}/screenshot_{timestamp}.png"
                        page.screenshot(path=screenshot_path)
                        image_url = f"/static/images/screenshot_{timestamp}.png"
                else:
                    print("No image with title found, capturing screenshot")
                    timestamp = int(time.time())
                    screenshot_path = f"{IMAGE_DIR}/screenshot_{timestamp}.png"
                    page.screenshot(path=screenshot_path)
                    image_url = f"/static/images/screenshot_{timestamp}.png"
                
                # Jika URL gambar relatif, ubah menjadi URL absolut
                if image_url and not image_url.startswith(("http", "/static")):
                    parsed_url = urlparse(url)
                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                    image_url = urljoin(base_url, image_url)
                
                # Sanitasi data
                title = sanitize_text(title) or "Product Title Not Found"
                description = sanitize_text(description) or "No description available"
                price = sanitize_text(price) or "Price not available"
                stock = sanitize_text(stock) or "Stock not available"
                image_url = image_url or ""
                
                # Simpan ke database dengan koneksi baru untuk menghindari koneksi terputus
                db = get_db_connection()
                cursor = db.cursor(dictionary=True)
                cursor.execute(
                    """
                    INSERT INTO products (name, description, price, stock, img_url)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (title, description, price, stock, image_url)
                )
                db.commit()
                cursor.close()
                db.close()
                
                browser.close()
                return {"name": title, "description": description, "price": price, "stock": stock, "img_url": image_url}
                
        except TimeoutError as e:
            print(f"Timeout error, retrying ({retry_count+1}/{max_retries}): {str(e)}")
            retry_count += 1
            time.sleep(2)  # Tunggu beberapa detik sebelum mencoba lagi
            
        except Exception as e:
            print(f"Error during scraping: {str(e)}")
            if 'browser' in locals():
                browser.close()
            
            # Coba lagi jika masih ada percobaan tersisa
            if retry_count < max_retries:
                retry_count += 1
                print(f"Retrying ({retry_count}/{max_retries})...")
                time.sleep(2)
            else:
                raise e
    
    # Jika semua percobaan gagal
    raise Exception("Failed to scrape after maximum retries")

# API untuk scraping
@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        data = request.json
        url = data.get("url")
        
        if not url:
            return jsonify({"error": "URL tidak diberikan"}), 400
        
        # Validasi URL
        if not is_valid_url(url):
            return jsonify({"error": "URL tidak valid"}), 400
        
        result = scrape_airlinehyd(url)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route utama
@app.route('/')
def home():
    return render_template('index.html')

# API untuk mengambil data produk dari database
@app.route('/products', methods=['GET'])
def get_products():
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT name, price, stock, description, img_url FROM products ORDER BY id DESC")
        products = cursor.fetchall()
        cursor.close()
        db.close()
        print("Products fetched:", products)  # Debugging: Menampilkan data produk
        return jsonify({"success": True, "products": products})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)

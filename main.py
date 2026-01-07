import os
import json
import requests
from bs4 import BeautifulSoup
import hashlib
import firebase_admin
from firebase_admin import credentials, firestore, messaging

# 1. Firebase Bağlantısı
if "FIREBASE_KEY" in os.environ:
    key_dict = json.loads(os.environ["FIREBASE_KEY"])
    cred = credentials.Certificate(key_dict)
else:
    cred = credentials.Certificate("serviceAccountKey.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()


def scrape_aski():
    print("ASKI kontrol ediliyor (Basit Arama Modu)...")
    url = "https://www.aski.gov.tr/tr/Kesinti.aspx"

    try:
        response = requests.get(url, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        boxes = soup.find_all('div', class_='featured-box')
    except Exception as e:
        print(f"Hata: {e}")
        return

    for box in boxes:
        content = box.find('div', class_='box-content')
        if not content: continue

        district = content.find('h4').text.strip() if content.find('h4') else ""
        p_tag = content.find('p')
        if not p_tag: continue

        # Tüm metni al (küçük harfe çevirerek arama kolaylığı sağla)
        full_text = p_tag.get_text(" ", strip=True).lower()

        if "etkilenen yerler:" in full_text:
            # Sadece "Etkilenen Yerler:"den sonrasını alalım
            raw_data = full_text.split("etkilenen yerler:")[1].strip()

            # Benzersiz ID: Bu duyuru daha önce işlendi mi?
            outage_id = hashlib.md5(f"{district}-{raw_data}".encode()).hexdigest()

            if not db.collection('sent_notifications').document(outage_id).get().exists:
                process_notifications(outage_id, district, raw_data)


def process_notifications(outage_id, district, aski_text):
    print(f"Yeni Kesinti Analizi: {district}")
    users = db.collection('users').stream()

    for user in users:
        data = user.to_dict()
        # Kullanıcının seçtiği mahalle ismi (Örn: "Karapürçek")
        neighborhood = data.get('selected_neighborhood', '').lower()
        fcm_token = data.get('fcm_token')

        if not fcm_token or not neighborhood: continue

        # KRİTİK KONTROL: Mahalle ismi metnin içinde geçiyor mu?
        if neighborhood in aski_text:
            send_push(
                fcm_token,
                f"Su Kesintisi: {district}",
                f"{neighborhood.capitalize()} bölgesi için yeni bir kesinti duyurusu var."
            )

    # Tekrar bildirim gitmemesi için ID'yi kaydet
    db.collection('sent_notifications').document(outage_id).set({'sent_at': firestore.SERVER_TIMESTAMP})


def send_push(token, title, body):
    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=token
        )
        messaging.send(message)
        print(f"Bildirim gönderildi -> {token[:10]}...")
    except Exception as e:
        print(f"Push hatası: {e}")


if __name__ == "__main__":
    scrape_aski()
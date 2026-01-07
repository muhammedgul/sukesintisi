import requests
from bs4 import BeautifulSoup
import hashlib
from firebase_admin import credentials, firestore, messaging, initialize_app
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# GitHub Actions ortamında mıyız kontrol et
if "FIREBASE_KEY" in os.environ:
    # GitHub Secrets'tan gelen stringi JSON'a çevir
    key_dict = json.loads(os.environ["FIREBASE_KEY"])
    cred = credentials.Certificate(key_dict)
else:
    # Kendi bilgisayarında çalıştırırken
    cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(cred)
db = firestore.client()

def scrape_aski():
    url = "https://www.aski.gov.tr/tr/Kesinti.aspx"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Her bir kesinti kutusunu bul
    items = soup.find_all('div', class_='featured-box')

    for item in items:
        # İlçe bilgisini al (Örn: ALTINDAĞ)
        district = item.find('h4').text.strip()

        # Paragraf içindeki metni al
        p_tag = item.find('p')
        full_text = p_tag.get_text(separator="|").strip()

        if "Etkilenen Yerler:" in full_text:
            parts = full_text.split("Etkilenen Yerler:")
            raw_neighborhoods = parts[1].replace('|', '').strip()

            # Mahalleleri listeye çevir (Virgül ve noktaya göre temizle)
            neighborhood_list = [n.strip().replace('.', '') for n in raw_neighborhoods.replace(',', ' ').split()]

            # Benzersiz bir ID oluştur (Tekrar bildirimi önlemek için)
            # İlçe + Mahalleler + Tarih bilgisinden bir hash oluşturuyoruz
            outage_id = hashlib.md5(f"{district}-{raw_neighborhoods}".encode()).hexdigest()

            check_and_notify(outage_id, district, neighborhood_list, raw_neighborhoods)


def check_and_notify(outage_id, district, neighborhoods, original_text):
    # Bu kesinti daha önce gönderildi mi?
    sent_ref = db.collection('sent_notifications').document(outage_id)
    if sent_ref.get().exists:
        return  # Zaten gönderilmiş, atla

    # Bu ilçeyi veya mahalleyi takip eden kullanıcıları bul
    # Firestore'da 'subscriptions' koleksiyonunda kullanıcıların seçtiği mahalleler var
    users_ref = db.collection('users')

    # Not: Firestore "array_contains_any" kullanarak 10 mahalleye kadar tek sorguda bulabilir
    # Ama biz her kullanıcı için eşleşme var mı diye kontrol edeceğiz (ya da basit bir döngü)
    all_users = users_ref.stream()

    for user in all_users:
        user_data = user.to_dict()
        user_neighborhood = user_data.get('selected_neighborhood')  # Örn: "Karapürçek"

        # Eğer kullanıcının mahallesi listede geçiyorsa push at
        if user_neighborhood in neighborhoods:
            send_push_notification(
                user_data.get('fcm_token'),
                f"Su Kesintisi: {district}",
                f"{user_neighborhood} mahallesini etkileyen bir kesinti duyuruldu."
            )

    # Bildirim bitti, ID'yi kaydet
    sent_ref.set({'sent_at': firestore.SERVER_TIMESTAMP})


def send_push_notification(token, title, body):
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        token=token
    )
    messaging.send(message)
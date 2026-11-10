<div align="center">

# Klinik Muhakeme ve Ayırıcı Tanı Kokpiti

**Yerel LLM destekli, hekim incelemesi için yapılandırılmış klinik karar taslağı**

FastAPI · Next.js · TypeScript · SQLite · Ollama

</div>

> [!WARNING]
> **Bu proje klinik kullanım için doğrulanmış bir tıbbi cihaz veya üretim
> sistemi değildir.** Araştırma, yazılım geliştirme ve kontrollü teknik
> değerlendirme amacıyla hazırlanmış bir prototiptir. LLM çıktıları yanlış,
> eksik veya yanıltıcı olabilir. Sistem teşhis koymaz, tedavi kararı vermez ve
> hekim değerlendirmesinin, kurum protokollerinin ya da acil bakımın yerini
> alamaz. **Gerçek hasta verisi girmeyin.** Bu projeyi internete, hastane ağına
> veya gerçek klinik iş akışına açmayın.

## Proje hakkında

Kokpit; hekim tarafından girilen anamnez, vital bulgular, doğrulanmış hasta
güvenlik bilgileri ve yüklenen dış rapor metninden bir **ayırıcı tanı taslağı**
oluşturur. Yerel Ollama modeli yapılandırılmış bir klinik karar üretir; backend
bu çıktıyı SQLite ilaç güvenliği kurallarıyla tekrar denetler. Hekim, uygun
durumda tanı taslağını ve reçeteyi düzenleyip onaylayabilir. Onay kaydı
SHA-256 hash zinciriyle ilişkilendirilir.

Sistem yerel çalışacak şekilde tasarlanmıştır; ancak “yerel” olması tek başına
veri gizliliği, güvenlik, klinik doğruluk veya mevzuata uygunluk sağlamaz.

## İçindekiler

- [Öne çıkanlar](#öne-çıkanlar)
- [Kapsam ve sınırlar](#kapsam-ve-sınırlar)
- [Mimari](#mimari)
- [Gereksinimler](#gereksinimler)
- [Hızlı başlangıç](#hızlı-başlangıç)
- [Yapılandırma](#yapılandırma)
- [Kullanım akışı](#kullanım-akışı)
- [API başvurusu](#api-başvurusu)
- [Veri ve güvenlik](#veri-ve-güvenlik)
- [GitHub’a yayınlama kontrolü](#githuba-yayınlama-kontrolü)
- [Testler](#testler)
- [Sorun giderme](#sorun-giderme)
- [Proje dizinleri](#proje-dizinleri)

## Öne çıkanlar

- **Yapılandırılmış klinik çıktı:** Ollama yerel API’si, Pydantic JSON Schema
  çıktısı ve `temperature=0.0` ile çağrılır.
- **İki aşamalı karar görünümü:** `NEEDS_TESTS` durumunda test/eksik bilgi
  gösterilir ve reçete kapalı kalır; `READY_FOR_PRESCRIPTION` durumunda
  güvenlik filtresinden geçmiş düzenlenebilir taslak gösterilir.
- **Deterministik ilaç kontrolleri:** SQLite kurallarıyla alerji grubu, böbrek
  fonksiyonu/eGFR, gebelik ve günlük doz sınırları kontrol edilir. Tanınmayan
  ilaçlar varsayılan olarak güvenli kabul edilmez.
- **Dış belge okuma:** PDF, UTF-8 TXT, PNG ve JPEG işlenir. Taranmış PDF/görsel
  için Tesseract OCR yerel olarak çalıştırılır.
- **Denetlenebilir onay:** İnceleme süresi, seçilen tanı ve reçete onayı audit
  tablosuna yazılır; her hash önceki kaydın hash’ine bağlanır.
- **İstek korelasyonu:** HTTP yanıtları `X-Request-ID` taşır; bu kimlik
  backend loglarında hata aşamasını bulmaya yardımcı olur.
- **Tek komutla başlatma:** Proje kökündeki `start.py`, Python/npm
  bağımlılıklarını, Ollama’yı, backend’i ve frontend’i yönetir.

## Kapsam ve sınırlar

Mevcut sürümde:

- e-Nabız, HBYS, reçete/eczane, laboratuvar veya görüntüleme sistemiyle gerçek
  entegrasyon **yoktur**.
- “Testleri İste” işlevi yalnızca yerel bir test istem taslağını panoya
  kopyalar; hastane bilgi sistemine emir göndermez.
- Hekim sicil ve diploma numarası alanları kimlik doğrulaması değildir. API’de
  kullanıcı hesabı, yetkilendirme veya hekim kimlik doğrulaması bulunmaz.
- İlaç güvenlik kuralları kapsamlı bir ilaç etkileşimi, doz ayarlama veya
  klinik rehber sistemi değildir.
- Hash zinciri kayıt değişikliğini fark etmeye yardımcı olur; imzalı veya
  değiştirilemez saklama, veritabanı erişim kontrolü ya da yedekleme sağlamaz.
- Başarılı analiz veya test sonucu klinik doğrulama, regülasyon onayı ya da
  üretime hazır olma anlamına gelmez.

## Mimari

```text
Tarayıcı
  │
  ├── Next.js kokpiti (127.0.0.1:3000)
  │      └── /api/v1/clinical/* rewrite
  │
  └── FastAPI (127.0.0.1:8000)
         ├── Pydantic istek/yanıt doğrulaması
         ├── Ollama yerel API (127.0.0.1:11434)
         ├── Klinik ve ilaç güvenliği filtresi
         ├── SQLite WAL veritabanı
         └── SHA-256 onay denetim zinciri
```

### Analiz akışı

1. Kokpit, anamnez metni ile hekim tarafından doğrulanmış hasta bilgilerini ve
   vital bulguları toplar. PDF/TXT/görsel raporlar yüklenirse içerikleri yerel
   olarak çıkarılır ve vaka bağlamına eklenir.
2. FastAPI isteği Pydantic şemalarıyla doğrular. Eksik/uyumsuz alanlar
   reddedilir.
3. Backend, vaka bağlamını `OLLAMA_MODEL` ile seçilen Ollama modeline
   yapılandırılmış JSON çıktısı bekleyerek gönderir.
4. Model çıktısı Pydantic şemasına göre doğrulanır. Geçersiz model yanıtı,
   bağlantı hatası veya zaman aşımı analiz hatası olarak döndürülür; geçerli
   analiz yokken reçete onayı oluşturulmaz.
5. Güvenlik filtresi ilaç önerilerini SQLite kurallarıyla denetler. Uygun
   olmayan ilaç kaldırılabilir; eksik hasta bilgisi, kritik bulgu veya güvenlik
   engeli analizi `NEEDS_TESTS` durumuna alabilir.
6. İstek ve sonuç SQLite’a kaydedilir. Belge metninin kendisi analiz girdisi
   JSON’una kaydedilmez; belge metni için SHA-256 özeti ve karakter sayısı
   tutulur. Ancak hasta bağlamı ve model çıktısı veritabanında bulunduğundan
   veritabanı hassas veri içerebilir.
7. Hekim onayında backend seçilen tanıyı, klinik durumu ve düzenlenmiş
   reçeteyi tekrar denetler; izin verilen onayı hash zincirine ekler.

### Klinik durumlar

| Durum | Uygulamadaki anlamı | Kokpitte görünen |
|---|---|---|
| `NEEDS_TESTS` | Test, gerekli bilgi veya klinik engel çözülmemiştir. | Ayırıcı tanı, red flag’ler, eksikler ve istenen testler. Reçete gösterilmez ve hekim onayı kabul edilmez. |
| `READY_FOR_PRESCRIPTION` | Model gerekli değerlendirme verisinin mevcut olduğunu belirtmiştir. | Güvenlik kontrolleri, tanı seçimi ve düzenlenebilir reçete taslağı. Onay yine hekim kararı ve backend güvenlik kontrollerine bağlıdır. |

`READY_FOR_PRESCRIPTION`, ilacın klinik olarak doğru ya da hasta için uygun
olduğunu kanıtlamaz.

### Güvenlik filtresi özeti

- İlaç eşleştirmesi ATC kodu, bilinen etken madde/ticari ad eşanlamları ve
  normalize edilmiş veritabanı adlarıyla yapılır.
- Veritabanında bulunmayan bilinen seed ilaçları için kod içi seed kuralları
  kullanılır. Eşleşmeyen/kuralı olmayan ilaçlar güvenli varsayılmaz ve
  onaylanmaz.
- Alerji grubu ve penisilin-sefalosporin çapraz reaksiyon uyarısı kontrol
  edilir.
- eGFR, kuraldaki ilaç eşiği ve ACE/ARB özel uyarı mantığına göre değerlendirilir.
  ACE inhibitörleri/ARB’ler yalnızca eGFR `< 60` olduğu için otomatik
  engellenmez; eGFR `< 30` olduğunda yüksek riskli izlem/hekim değerlendirmesi
  uyarısı üretilir. Diğer ilaç kuralları ayrıca uygulanır.
- Gebelik kategorisi, maksimum günlük doz, gerekli hasta güvenlik bilgileri,
  vital eksikleri ve red flag’ler de kararın reçete için açık kalıp
  kalamayacağını etkiler.

Bu kurallar klinik rehber değildir; kaynak koddaki kurallar ve seed verileri
[`backend/app/engine/safety_filter.py`](backend/app/engine/safety_filter.py) ile
[`backend/app/database.py`](backend/app/database.py) içindedir.

## Gereksinimler

| Bileşen | Gereksinim |
|---|---|
| Python | 3.10 veya üzeri |
| Node.js ve npm | Next.js 16 ile uyumlu güncel bir LTS sürümü |
| Ollama | Kurulu ve `127.0.0.1:11434` üzerinden erişilebilir |
| Model | Yapılandırılan Ollama modelini çalıştıracak disk ve sistem belleği |
| OCR (isteğe bağlı) | Taranmış belge/görsel için Tesseract ve `tur`, `eng` dil verileri |

`start.py` varsayılan olarak `qwen2.5:7b-instruct` modelini seçer ve Ollama
model listesinde bulamazsa indirmeyi dener. İlk çalıştırmada Python/npm
paketleri ve model indirilebileceğinden internet bağlantısı ve yeterli disk
alanı gerekir. Donanım gereksinimi seçilen model boyutuna göre değişir.

## Hızlı başlangıç

### Windows

1. GitHub deposu oluşturulduktan sonra depo sayfasındaki **Code → HTTPS**
   adresini kullanarak depoyu bilgisayarınıza klonlayın ve proje klasörüne
   geçin. Klonlama komutunda kendi GitHub depo adresinizi kullanın.

2. `backend\.env` dosyasını oluşturun. En azından model adını açıkça belirleyin:

   ```dotenv
   OLLAMA_MODEL=qwen2.5:7b-instruct
   OLLAMA_TIMEOUT_SECONDS=300
   LOG_LEVEL=INFO
   ```

3. Proje kökünde sistemi başlatın:

   ```powershell
   python start.py
   ```

4. Açın:
   - Kokpit: <http://127.0.0.1:3000>
   - FastAPI / Swagger: <http://127.0.0.1:8000/docs>
   - OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

5. Kapatmak için başlangıç terminalinde `Ctrl+C` tuşlarına basın.

`start.py` ayrıca `--dev` seçeneğini destekler:

```powershell
python start.py --dev
```

Bu seçenek frontend’i Next.js geliştirme sunucusuyla açar; backend ve
Ollama’nın başlatılma akışı aynıdır.

### Linux / macOS

Python 3 komutunuz `python3` ise proje kökünde:

```bash
python3 start.py
```

Geliştirme modu:

```bash
python3 start.py --dev
```

### Başlatıcı neler yapar?

`start.py` Python 3.10+, Node.js/npm ve `ollama` komutlarını arar; backend
virtualenv’ini yoksa oluşturur; backend ve frontend bağımlılık kurulumlarını
çalıştırır; yapılandırılmış modeli Ollama’da kontrol eder, gerekirse indirir;
sonra backend’i ve frontend’i başlatıp hazır olmalarını bekler. Normal modda
frontend production build alır. 8000 veya 3000 portu doluysa başlangıç durur.

Başlatıcı bağımlılık kurulum komutlarını her çalıştırmada yeniden çalıştırır.
Kurulum, yeni bağımlılıklar ve model indirme işlemleri internet gerektirebilir.
Ollama zaten çalışıyorsa yeniden başlatılmaz; betik kendi başlattığı servis
süreçlerini `Ctrl+C` sırasında kapatır.

## Yapılandırma

### Backend: `backend/.env`

Dosyayı kendiniz oluşturun ve Git’e eklemeyin.

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `OLLAMA_MODEL` | Analyzer: `qwen2.5:3b-instruct`; `start.py`: `qwen2.5:7b-instruct` | **Öneri:** her iki varsayılanın farklı olmasını önlemek için açıkça ayarlayın. Model Ollama’da kurulu olmalıdır. |
| `OLLAMA_TIMEOUT_SECONDS` | `300` | Tek Ollama çıkarımı için pozitif saniye değeri. |
| `LOG_LEVEL` | `INFO` | Python log seviyesi. |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001` | İzin verilen origin’ler; virgülle ayrılır. Wildcard ve path içeren değerler reddedilir. |
| `CLINICAL_DB_PATH` | `clinical.db` | SQLite dosyası. Göreli yol `backend/` klasörüne göre değerlendirilir; varsayılan dosya `backend/clinical.db` olur. |
| `TESSERACT_CMD` | Sistem `PATH` değeri | Tesseract çalıştırılabilir dosyasının tam yolu; yalnızca OCR için gerekir. |

Örnek `backend/.env`:

```dotenv
OLLAMA_MODEL=qwen2.5:7b-instruct
OLLAMA_TIMEOUT_SECONDS=300
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
CLINICAL_DB_PATH=clinical.db
```

Modeli değiştirirken indirilen model adıyla `.env` değerinin aynı olduğundan
emin olun. Örneğin:

```bash
ollama pull qwen2.5:7b-instruct
```

Ardından backend’i yeniden başlatın.

### Frontend backend adresi

`frontend/next.config.mjs`, `/api/v1/clinical/*` isteklerini Next.js sunucu
tarafından backend’e yönlendirir. Varsayılan:

```text
http://127.0.0.1:8000
```

Backend başka bir adreste çalışıyorsa frontend sürecinde
`BACKEND_INTERNAL_URL` tanımlayın. Örneğin `frontend/.env.local`:

```dotenv
BACKEND_INTERNAL_URL=http://127.0.0.1:8000
```

Frontend ve backend’i farklı makinelerde çalıştırmak ağ erişimi, güvenlik duvarı
ve güvenli taşıma ayarları gerektirir. Uygulama varsayılan olarak loopback
adreslerine bağlanır; bu varsayılanı gelişigüzel değiştirmeyin.

## Kullanım akışı

1. **Anamnez girin.** Şikayet, öykü ve klinik notlar alanı zorunludur.
2. **Dış belge ekleyin (isteğe bağlı).** PDF, TXT, PNG veya JPEG seçin. Dosya
   backend tarafından bellekte işlenir; metin çıkarma başarılı olursa özet ve
   karakter sayısı kokpitte görünür.
3. **Hasta güvenlik bilgilerini ve vitalleri doğrulayın.** Yaş, cinsiyet, kilo,
   gebelik durumu, eGFR, alerji öyküsü ve ölçülmüş vital alanları
   reçete değerlendirmesi için kullanılır. Belgedeki bir bilgi kendiliğinden
   doğrulanmış sayılmaz.
4. **Klinik muhakemeyi başlatın.** Bekleme süresi model, donanım ve vaka
   uzunluğuna bağlıdır. Sonuçta durum, özet, ayırıcı tanı, olası red flag’ler
   ve güvenlik değerlendirmeleri gösterilir.
5. **Sonuca göre ilerleyin.**
   - `NEEDS_TESTS`: Ekrandaki eksik bilgileri/testleri inceleyin. Test istemi
     yalnızca panoya kopyalanan bir taslaktır.
   - `READY_FOR_PRESCRIPTION`: Tanıyı seçin, reçete taslağını inceleyip
     gerekirse düzenleyin; hekim sicil/diploma alanlarını doldurun.
6. **Hekim onayı.** Backend güvenlik kurallarını tekrar uygular; kabul edilen
   onayı, süreyi ve reçete değişikliğini audit kaydına ekler. Arayüz audit
   hash’ini gösterir ve epikriz metnini panoya kopyalamayı dener.

### Klavye kısayolları

| Tuş | İşlev |
|---|---|
| `1`, `2`, `3` | Mevcut ayırıcı tanılardan ilgili sıradakini seçer. |
| `Space` veya `Enter` | Odak bir form alanında/butonda değilken, onay koşulları sağlanıyorsa seçili tanı ve reçete onayını başlatır. |

Form alanı yazılırken kısayollar çalışmaz. `Space`/`Enter` tek başına klinik
onay oluşturmaz: analiz durumu, seçili tanı, hasta verileri ve hekim alanları
gibi uygulama kontrolleri yine geçerlidir.

## API başvurusu

API, `http://127.0.0.1:8000` üzerinde çalışır. Swagger arayüzü:
<http://127.0.0.1:8000/docs>. Tam istek/yanıt JSON Schema’ları için bu arayüz
ve [`backend/app/schemas.py`](backend/app/schemas.py) kaynak dosyası
yetkili referanstır.

| Metot | Yol | Girdi | İşlem |
|---|---|---|---|
| `POST` | `/api/v1/clinical/upload-context` | `multipart/form-data`; her dosya `files` alanında | PDF/TXT/görsel metnini çıkarır ve belge metadata’sını döndürür. |
| `POST` | `/api/v1/clinical/analyze` | `AnalyzeRequestPayload` JSON | İsteği doğrular, Ollama analizi yapar, ilaç güvenlik filtresini uygular ve oturumu SQLite’a kaydeder. |
| `POST` | `/api/v1/clinical/approve` | `DoctorApprovalRequest` JSON | Oturum/tanı/reçeteyi doğrular ve geçerli onayı audit zincirine yazar. |
| `GET` | `/api/v1/clinical/diagnostics` | İstek gövdesi yok | Ollama erişimi/model listesini ve SQLite ilaç kuralı sayısını kontrol eder. Hasta vaka verisi göndermez. |

### Analiz isteği alanları

`POST /api/v1/clinical/analyze` için üst düzey gövde aşağıdaki alanlardan
oluşur:

| Alan | Tür / kısıt | İçerik |
|---|---|---|
| `session_id` | Metin, 1–128 karakter | Benzersiz analiz oturumu. Tekrar kullanılırsa `409` döner. |
| `patient_context` | Nesne | Hasta hash’i, yaş, cinsiyet, kilo, gebelik, eGFR, alerji ve kronik durum bilgileri. |
| `vitals` | Nesne | Ateş, sistolik/diyastolik basınç, nabız ve SpO₂; değer aralıkları Pydantic tarafından doğrulanır. |
| `chief_complaint` | Metin, 3–2000 karakter | Anamnez ve başvuru şikayeti. |
| `lab_results` | Liste; varsayılan boş | Kod, değer, birim, referans aralığı ve `LOW`/`NORMAL`/`HIGH`/`CRITICAL` bayrağı. |
| `clinical_context` | Metin; en fazla 30.000 karakter | Upload endpoint’inden çıkarılan belge bağlamı. |

`patient_context` içindeki alanlar:

| Alan | Tür / sınır | Açıklama |
|---|---|---|
| `patient_tc_hash` | 64 karakterlik metin | Ham kimlik numarası yerine istemcinin gönderdiği hash alanı. Hash kullanımı hasta verisini kendiliğinden anonimleştirmez. |
| `age` | `null` veya 0–130 tam sayı | Hasta yaşı. |
| `sex` | `null`, `M` veya `F` | Şemada tanımlı biyolojik cinsiyet enum’u. |
| `weight_kg` | `null` veya 1’den büyük, en fazla 300 sayı | Kilogram cinsinden ağırlık. |
| `pregnancy_status` | `null` veya boolean | Gebelik durumu; bilinmiyorsa `null`. |
| `egfr_ml_min` | `null` veya 0–200 sayı | mL/dk cinsinden eGFR. |
| `known_allergies` | Metin listesi | Bilinen alerjiler; her madde ayrı eleman olmalıdır. |
| `allergy_history_reviewed` | Boolean | Alerji öyküsünün sorgulanıp sorgulanmadığı. |
| `chronic_conditions` | Metin listesi | Bilinen kronik durumlar. |

`vitals` içindeki tüm ölçümler nullable’dır; fakat reçete uygunluğu için
eksiklikler analiz sonucunu engelleyebilir:

| Alan | Şema aralığı | Birim |
|---|---:|---|
| `temperature_c` | 30–45 | °C |
| `bp_systolic` | 40–300 | mmHg |
| `bp_diastolic` | 20–200 | mmHg |
| `heart_rate_bpm` | 20–260 | atım/dk |
| `spo2_percent` | 50–100 | % |

Hasta nesnesindeki alerji öyküsü sorgulama durumu ile gebelik/eGFR gibi
bilgilerin eksik olması reçete önerisini kapatabilir. Şema geçerli girişleri
otomatik olarak klinik açıdan doğru yapmaz; verileri yetkili sağlık
profesyoneli doğrulamalıdır.

Analiz yanıtı; `session_id`, `processing_time_ms`, `safety_badges` ve
`clinical_decision` alanlarını içerir. Klinik karar nesnesinde klinik durum ve
özet, sıralı ayırıcı tanılar, istenen testler, eksik bilgiler, klinik
engeller, red flag’ler, önerilen iş akışı ve reçete taslağı bulunur. Enum’lar,
alan sınırları ve alt nesnelerin tam yapısı için OpenAPI şeması esas alın.

### Belge yükleme sınırları

| Sınır | Değer |
|---|---:|
| Desteklenen türler | PDF, UTF-8 TXT, PNG, JPEG |
| Dosya sayısı | İstek başına en fazla 8 |
| Dosya boyutu | Dosya başına en fazla 15 MiB |
| PDF sayfa sayısı | PDF başına en fazla 30 |
| Çıkarılmış bağlam | Toplam en fazla 30.000 karakter |
| OCR sayfa zaman aşımı | 12 saniye |

Parola korumalı/bozuk PDF reddedilir. Görsel OCR ve metinsiz PDF sayfalarının
OCR’ı için Tesseract ile `tur` ve `eng` dil verileri gerekir. OCR metni hatalı
olabileceğinden kaynak belgeyle karşılaştırılmalıdır.

### Onay isteği alanları

`POST /api/v1/clinical/approve` alanları:

| Alan | Açıklama |
|---|---|
| `session_id` | Daha önce başarıyla analiz edilmiş oturum. |
| `doctor_id`, `doctor_diploma_no` | Audit kaydına yazılan değerler; kimlik doğrulaması yapmaz. |
| `selected_diagnosis_rank` | Analizdeki `1`, `2` veya `3` tanı sırası. |
| `approval_action` | `APPROVED_AS_IS`, `MODIFIED_AND_APPROVED` veya `REJECTED`. |
| `modified_prescription` | Değiştirilmiş onayda reçete listesi; diğer akışlarda şemaya göre `null` olmalıdır. |
| `review_duration_ms` | Arayüzün ölçtüğü inceleme süresi (ms). |

`NEEDS_TESTS` oturumunda onay verilemez. Değiştirilmiş reçete de backend’de
tekrar ilaç güvenlik filtresinden geçer.

Başarılı onay yanıtı `session_id`, `audit_id`, `record_hash`, `prev_hash` ve
`approved_at` alanlarını döndürür. `record_hash`, kanonikleştirilmiş onay
detaylarının SHA-256 özetidir; bağımsız imza veya dış zaman damgası değildir.

### Tanılama yanıtı

`GET /api/v1/clinical/diagnostics`, yapılandırılmış model adını, Ollama API
erişimini, kurulu model adlarını, Ollama timeout ayarını, SQLite erişimini ve
seed/kural tablosundaki ilaç kaydı sayısını döndürür. Bu endpoint servis
durumunu ölçer; modelin klinik doğruluğunu veya API’nin güvenli olduğunu
doğrulamaz.

Hasta verisi göndermeyen tanılama isteği:

```bash
curl http://127.0.0.1:8000/api/v1/clinical/diagnostics
```

Tarayıcı kokpitindeki hata panelinde de aynı kontrolü **Sistem tanılamasını
çalıştır** düğmesiyle başlatabilirsiniz.

### Hata kodları ve istek kimliği

| HTTP | Genel anlam |
|---:|---|
| `404` | Onay için belirtilen klinik oturum bulunamadı. |
| `409` | Yinelenen oturum veya audit/veritabanı çakışması. |
| `413` | Belge veya çıkarılmış metin boyut sınırı aşıldı. |
| `422` | Pydantic doğrulama, dosya biçimi veya klinik onay kuralı hatası. |
| `503` | Ollama erişilemiyor, zaman aşımına uğradı ya da kullanılabilir yapılandırılmış çıktı üretemedi. |
| `500` | Beklenmeyen uygulama/veritabanı hatası. |

HTTP yanıtlarında `X-Request-ID` bulunur. Hata panelinde bu kimlik, hata
aşaması ve tanılama özeti gösterilebilir. Backend terminalindeki aynı kimlikle
logları eşleştirin. Log veya hata raporlarını paylaşmadan önce hasta verisi,
kimlik bilgisi ve sır içermediğini kontrol edin.

## Veri ve güvenlik

- SQLite WAL veritabanı varsayılan olarak `backend/clinical.db` konumundadır.
  `clinical_sessions`, `doctor_approvals_audit` ve `drug_safety_rules`
  tabloları başlangıçta oluşturulur; ilaç kuralları seed edilir.
- `clinical_sessions` analiz oturumunu, hasta hash’ini, saklanan girdi/çıktı
  JSON’unu, model adını ve işlem süresini tutar. `doctor_approvals_audit`
  seçilen tanı, hekim alanları, aksiyon, süre, önceki hash, geçerli hash ve
  zamanı tutar. `drug_safety_rules` ilaç/ATC, alerji grubu, eGFR eşiği, azami
  doz ve gebelik kategorisi kurallarını tutar.
- Analiz oturumu ve model çıktısı veritabanında saklanır. Girdi kaydında
  belge metninin tamamı yerine belge hash’i/karakter sayısı kullanılır; bu,
  diğer hasta alanlarının veya model çıktısının hassasiyetini ortadan kaldırmaz.
- Yüklenen dosyalar kalıcı dosyaya yazılmadan bellekte işlenir. Çıkarılan
  metin analiz isteğinde Ollama’ya gönderilir.
- Ollama varsayılan olarak loopback arayüzünde çağrılır. Model, prompt ve
  inference donanımı yerel Ollama kurulumunuza bağlıdır.
- CORS allowlist’i tarayıcı kaynaklarını sınırlar; **kimlik doğrulama veya
  erişim kontrolü değildir**.
- Onay zincirinde her kayıt önceki kayıt hash’ini taşır. Veritabanı dosyasına
  erişebilen biri veriyi değiştirebilir; harici imza veya append-only saklama
  yoktur. `verify_audit_chain` yardımcı işlevi vardır, ancak HTTP doğrulama
  endpoint’i yoktur.
- Sunucuya veya internete açmadan önce kimlik doğrulama/yetkilendirme, TLS,
  depolama şifrelemesi, erişim denetimi, yedekleme/geri yükleme, log ve veri
  saklama politikası, güvenlik incelemesi, klinik validasyon ve ilgili mevzuat
  değerlendirmesi gerekir.
- Gerçek hasta verisini, `.env` dosyalarını, veritabanını ve logları GitHub’a
  yüklemeyin. Paylaşım öncesi `git status` ve staged dosyaları gözden geçirin.

## GitHub’a yayınlama kontrolü

İlk push öncesinde proje kökünde şu kontrolleri yapın:

```bash
git status --short
git check-ignore -v backend/.env backend/clinical.db backend/.venv frontend/node_modules
```

`.env`, SQLite veritabanı, Python sanal ortamı ve `node_modules` depoya
eklenmemelidir. `git status` içinde istemeden eklenmiş dosya görürseniz push
öncesi staging’den çıkarın; gizli bilgileri sonradan commit geçmişinden
silmenin tek başına yeterli olmayabileceğini unutmayın.

Depoda şu anda `LICENSE` dosyası yoksa, GitHub’da herkese açık yayınlamadan
önce proje için uygun lisansı belirleyip lisans dosyasını ayrıca ekleyin.
Lisans eklenmemiş bir depoda başkalarının kodu yeniden kullanma hakları
kendiliğinden tanımlanmış olmaz.

## Testler

### Frontend TypeScript kontrolü

```bash
cd frontend
npm install
npm run lint
```

`lint` script’i `tsc --noEmit` çalıştırır.

### Frontend production derlemesi

```bash
cd frontend
npm run build
```

### Backend testleri

Önce `backend/requirements.txt` bağımlılıklarını kurun, sonra proje kökünden:

**Windows PowerShell**

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**Linux / macOS**

```bash
cd backend
./.venv/bin/python -m unittest discover -s tests -v
```

Testlerin geçmesi yalnızca test kapsamındaki yazılım davranışını doğrular;
klinik performans, ilaç kurallarının yeterliliği veya üretim güvenliği
doğrulanmış sayılmaz.

## Sorun giderme

### Uygulama açılmıyor veya port kullanımda

- `start.py` Python 3.10+, Node.js, npm ve Ollama komutlarını bulmalıdır.
- Backend `127.0.0.1:8000`, frontend `127.0.0.1:3000` kullanır. Başka bir
  uygulama bu portlardan birini kullanıyorsa onu kapatın.
- Başlatma terminalindeki ilk hata mesajını inceleyin; başlangıç betiği servis
  süreçlerinden biri beklenmedik biçimde kapanırsa bunu bildirir.

### Ollama bağlantısı yok

Ollama uygulamasının/servisinin çalıştığını kontrol edin, ardından kokpit hata
panelinden **Sistem tanılamasını çalıştır** seçeneğini kullanın. API tanılaması
doğrudan şu adreste de görülebilir:

```text
http://127.0.0.1:8000/api/v1/clinical/diagnostics
```

`ollama_reachable` alanı `false` ise Ollama `127.0.0.1:11434` üzerinde yanıt
vermiyor olabilir.

### Model kurulu değil veya beklenen model kullanılmıyor

```bash
ollama list
ollama pull qwen2.5:7b-instruct
```

`backend/.env` içindeki `OLLAMA_MODEL` adını kurulu modelle eşleştirin.
`clinical_analyzer.py` varsayılanı `qwen2.5:3b-instruct`, başlangıç betiğinin
varsayılanı `qwen2.5:7b-instruct` olduğundan modeli `.env` içinde açıkça
tanımlayın. Ayar değişikliğinden sonra backend’i yeniden başlatın.

### İstek zaman aşımına uğruyor

Model boyutu, donanım ve girdi uzunluğu çıkarım süresini etkiler. Önce
Ollama’nın ve modelin hazır olduğunu doğrulayın. Gerekirse `OLLAMA_MODEL` için
donanımınıza uygun bir model seçin veya `OLLAMA_TIMEOUT_SECONDS` değerini
artırın. Next.js rewrite timeout’u 630 saniyedir; backend’deki iki aşamalı
çıkarım akışının toplam süresi bu proxy sınırını aşarsa tarayıcı isteği yine
başarısız olabilir.

### `NEEDS_TESTS` görünüyor

Bu, API/uygulama hatası olmak zorunda değildir. Eksik hasta güvenlik bilgisi,
vital, test veya klinik engel bulunabilir. Ekrandaki maddeleri inceleyip yalnız
hekim tarafından doğrulanan bilgileri tamamlayın. Sistem eksik veriyi normal
kabul etmemeli; bu durumda reçete onayı kapalı kalır.

### Belge yükleme veya OCR başarısız

- Dosya türü, dosya başına 15 MiB, en fazla 8 dosya ve PDF başına 30 sayfa
  sınırlarını kontrol edin.
- TXT dosyasının UTF-8 olduğundan emin olun.
- Taranmış PDF ve görsellerde Tesseract ile `tur` ve `eng` dil paketlerinin
  kurulu olduğunu doğrulayın; gerekirse `TESSERACT_CMD` ayarlayın.
- OCR sonucunu orijinal dosyayla karşılaştırın; OCR hataları klinik bilgi
  kaybına veya yanlış metne neden olabilir.

### HTTP 500 veya analiz hatası

Kokpitte **Sistem tanılamasını çalıştır** düğmesine basın ve hata panelindeki
`request_id` değerini backend terminal loglarında bulun. Logdaki `stage`
alanı, hatanın analiz, Ollama, güvenlik filtresi veya veritabanı aşamasından
hangisinde olduğunu gösterir. Hata raporunu paylaşmadan önce vaka metnini,
hasta bilgilerini ve kimlik bilgilerini çıkarın.

## Proje dizinleri

```text
.
├── README.md
├── ARCHITECTURE.md
├── start.py
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                    FastAPI uygulaması ve HTTP uçları
│   │   ├── schemas.py                 Pydantic istek/yanıt şemaları
│   │   ├── database.py                SQLite WAL, tablolar ve ilaç seed verileri
│   │   └── engine/
│   │       ├── clinical_analyzer.py   Ollama çıkarımı ve çıktı doğrulama
│   │       ├── safety_filter.py       Deterministik ilaç güvenlik filtresi
│   │       ├── audit_logger.py        Onay hash zinciri
│   │       └── document_ingestion.py  PDF/TXT/görsel metin çıkarımı ve OCR
│   └── tests/                         Backend unittest testleri
└── frontend/
    ├── package.json
    └── src/
        ├── app/page.tsx               Doktor değerlendirme kokpiti
        └── lib/
            ├── clinical-api.ts        Tipli frontend API istemcisi
            └── epicrisis.ts           Epikriz metni biçimlendiricisi
```

Tasarımın ek açıklamaları için [`ARCHITECTURE.md`](ARCHITECTURE.md) dosyasına
bakın.

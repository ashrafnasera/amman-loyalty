from werkzeug.security import generate_password_hash

from db import row, run, transaction
from loyalty import now

CATEGORIES = [
    ('مقاهي','#8763d2'), ('مطاعم','#ec785e'), ('كتب','#3d81d9'),
    ('رياضة','#25876d'), ('متاجر','#bc7a30'),
]
PLACES = [
    (0,'قهوة اللويبدة','جبل اللويبدة، شارع الباعونية',31.9566,35.9251,'قهوة مختصة ومخبوزات يومية في قلب اللويبدة.','إضافة مجانية مع القهوة الباردة','قهوة لاتيه'),
    (1,'زعتر البلد','وسط البلد، شارع الملك فيصل',31.9522,35.9331,'فطور أردني ومناقيش طازجة من الفرن.','خصم على وجبة الفطور','منقوشة زعتر'),
    (2,'رفّ وورق','جبل عمّان، شارع الرينبو',31.9499,35.9262,'كتب عربية وإنجليزية وركن للقراءة.','خصم 10٪ على الروايات','قسيمة كتب'),
    (3,'خطوة أكتف','الشميساني، شارع الثقافة',31.9757,35.9036,'حصص لياقة جماعية وتدريب شخصي.','حصة تجريبية بسعر خاص','حصة لياقة'),
    (4,'سوق الحارة','جبل عمّان، الدوار الأول',31.9509,35.9247,'منتجات محلية وحِرف من صناع أردنيين.','خصم على هدايا الموسم','قسيمة شراء'),
    (0,'بنّ الدوار','جبل عمّان، الدوار الثالث',31.9537,35.9093,'محمصة صغيرة تقدّم حبوباً بتوليفات موسمية.','خصم على أكياس البن','كوب قهوة اليوم'),
    (1,'سفرة جفرا','وسط البلد، شارع الأمير محمد',31.9515,35.9355,'مطبخ منزلي بطبخات أردنية متجددة.','مقبلات مع كل وجبة','طبق حمّص'),
    (2,'فصل جديد','جبل اللويبدة، دوار باريس',31.9560,35.9261,'مكتبة مستقلة تركز على المؤلفين المحليين.','عرض على الكتب المستعملة','كتاب من الرف المختار'),
    (3,'نَفَس ستوديو','عبدون، شارع القاهرة',31.9425,35.8917,'ستوديو يوغا وبيلاتس بحصص لجميع المستويات.','خصم على أول اشتراك','حصة يوغا'),
    (4,'زينة البيت','الصويفية، شارع الوكالات',31.9565,35.8666,'إكسسوارات وقطع منزلية من مشاغل محلية.','خصم على الأدوات الخزفية','قسيمة متجر'),
    (0,'كوب جبل','جبل الحسين، شارع خالد بن الوليد',31.9664,35.9210,'مقهى هادئ للشغل واللقاءات السريعة.','كوكيز مع القهوة الصباحية','إسبريسو'),
    (1,'مونة ومائدة','عبدون، دوار عبدون',31.9409,35.9002,'مطبخ شرقي يقدم وجبات موسمية طازجة.','عرض غداء أيام الأسبوع','حلو اليوم'),
    (2,'مكتبة الفهرس','الجامعة الأردنية، شارع الملكة رانيا',32.0131,35.8713,'مراجع جامعية وقرطاسية للطلاب.','خصم على دفاتر الجامعة','دفتر ملاحظات'),
    (0,'قهوة المحاضرة','الجبيهة، شارع الجامعة',32.0164,35.8702,'قهوة سريعة ومقاعد للدراسة والعمل.','سعر خاص للطلاب','قهوة مثلّجة'),
    (1,'لقمة الجامعة','الجبيهة، قرب بوابة الجامعة',32.0108,35.8735,'سندويشات ووجبات خفيفة قرب الجامعة.','عرض على وجبة الطالب','سندويشة'),
    (4,'دار البنفسج','العبدلي، البوليفارد',31.9638,35.9082,'شموع وعطور وهدايا مصنوعة يدوياً.','خصم على الأطقم الصغيرة','شمعة صغيرة'),
]


def seed():
    with transaction():
        if row("SELECT 1 FROM users WHERE email='customer@darb.test'"):
            return
        password = generate_password_hash('DarbDemo2026!')
        for name,email,role in [('ليان حداد','customer','customer'),('مالك التميمي','merchant','merchant'),
                                ('فريق درب','admin','admin'),('سارة العجلوني','sara','merchant')]:
            run('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)', (name,email+'@darb.test',password,role))
        ids = [run('INSERT INTO categories(name,color) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET color=excluded.color RETURNING id', c).fetchone()[0] for c in CATEGORIES]
        stores = []
        for i, (category,name,address,lat,lng,description,offer,reward) in enumerate(PLACES):
            owner = row('SELECT id FROM users WHERE email=?', ('merchant@darb.test' if i < 8 else 'sara@darb.test',))[0]
            bid = run("""INSERT INTO businesses(owner_id,category_id,name,description,address,latitude,longitude,rate,status)
                         VALUES(?,?,?,?,?,?,?,?,'approved')""", (owner,ids[category],name,description,address,lat,lng,10+(i%3)*5)).lastrowid
            stores.append(bid)
            run('INSERT INTO offers(business_id,title,description) VALUES(?,?,?)', (bid,offer,'اسأل فريق المتجر عن توفر العرض عند زيارتك.'))
            run('INSERT INTO rewards(business_id,title,cost) VALUES(?,?,?)', (bid,reward,40+i*5))
        run("""INSERT INTO businesses(owner_id,category_id,name,description,address,latitude,longitude,rate)
               VALUES(?,?,?,?,?,?,?,?)""", (owner,ids[0],'قهوة الساحة','مقهى محلي قيد التسجيل.','تلاع العلي',31.9933,35.8632,10))
        for title,description,indexes,goal,bonus in [
            ('تحدّي شارع الجامعة','جرّب ثلاثة أماكن حول الجامعة الأردنية ووثّق مشترياتك.',[12,13,14],3,180),
            ('جولة جبل عمّان','استكشف محلات جبل عمّان واجمع نقاط إضافية من زيارتين.',[2,4,5],2,100),
            ('جولة اللويبدة والبلد','اكتشف المقاهي والمكتبات والأسواق الشعبية.',[0,1,6,7],3,150),
        ]:
            cid = run('INSERT INTO challenges(title,description,starts_at,ends_at,goal,bonus) VALUES(?,?,?,?,?,?)',
                      (title,description,now()-86400,now()+86400*60,goal,bonus)).lastrowid
            for i in indexes:
                run('INSERT INTO challenge_businesses VALUES(?,?)',(cid,stores[i]))

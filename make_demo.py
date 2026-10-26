"""Generate an optional reproducible, synthetic showcase collection. Run once: python make_demo.py"""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageFilter
import random,sqlite3,uuid,cv2,numpy as np
from datetime import datetime,timezone
import app
ROOT=Path(__file__).parent
OUT=ROOT/'demo';OUT.mkdir(exist_ok=True)
random.seed(23)
fontpath='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
boldpath='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
def font(sz,bold=False):
    try:return ImageFont.truetype(boldpath if bold else fontpath,sz)
    except:return ImageFont.load_default()

objects=[('Field guide','Books & documents','Library · Shelf 2','#315844','#f2ead6','FIELD\nGUIDE','NATURE STUDIES'),('Network handbook','Books & documents','IT Lab · Cabinet 1','#bb654b','#f7e6d6','NETWORK\nHANDBOOK','SYSTEMS & INFRASTRUCTURE'),('Lab equipment log','Equipment','Lab 1 · Drawer 3','#355f83','#e7f0ed','EQUIPMENT\nREGISTER','2026 / LABORATORY')]
images=[]
for idx,(name,cat,loc,bg,fg,title,sub) in enumerate(objects):
    im=Image.new('RGB',(510,690),bg);d=ImageDraw.Draw(im)
    d.rectangle((24,24,486,666),outline=fg,width=3)
    d.text((52,54),'STILLROOM   /   ARCHIVE',font=font(15,True),fill=fg)
    d.line((52,91,458,91),fill=fg,width=2)
    for i in range(11):
        x=52+(i%4)*97;y=145+(i//4)*83
        d.ellipse((x,y,x+35+(i%3)*9,y+35+(i%3)*9),outline=fg,width=3)
    # asymmetrical details give ORB distinct, textured keypoints
    for j in range(70):
        x=random.randint(48,456);y=random.randint(118,423)
        d.line((x,y,x+random.randint(3,25),y+random.randint(1,13)),fill=fg,width=random.randint(1,3))
    d.rectangle((43,455,467,628),fill=fg)
    for line_no,txt in enumerate(title.split('\n')):
        d.text((58,465+line_no*55),txt,font=font(36,True),fill=bg)
    d.text((57,635),sub,font=font(16,True),fill=fg)
    path=OUT/f'reference_{idx+1}.jpg';im.save(path,quality=93)
    images.append(im)
    with app.connection() as db:
        exists=db.execute('SELECT id FROM items WHERE name=?',(name,)).fetchone()
        if not exists:
            ident='demo'+str(idx+1)
            filename=ident+'.jpg';im.save(app.UPLOADS/filename,quality=92)
            db.execute('INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?)',(ident,name,cat,loc,'Synthetic demo record · replace with your own photographed object for real use.',filename,datetime.now(timezone.utc).isoformat()))
scene=Image.new('RGB',(1420,930),'#d9d2c1');d=ImageDraw.Draw(scene)
for x in range(0,1420,45):d.line((x,0,x,930),fill='#d0c8b5',width=1)
for y in range(0,930,45):d.line((0,y,1420,y),fill='#d0c8b5',width=1)
scene_cv=cv2.cvtColor(np.array(scene),cv2.COLOR_RGB2BGR)
positions=[np.float32([[80,80],[490,110],[460,680],[100,670]]),np.float32([[570,70],[1040,105],[1030,775],[590,745]]),np.float32([[1050,210],[1330,195],[1320,685],[1040,715]])]
for im,quad in zip(images,positions):
    source=cv2.cvtColor(np.array(im),cv2.COLOR_RGB2BGR)
    h,w=source.shape[:2]
    M=cv2.getPerspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]),quad)
    warped=cv2.warpPerspective(source,M,(1420,930))
    mask=cv2.warpPerspective(np.ones((h,w),dtype=np.uint8)*255,M,(1420,930))
    scene_cv[mask>0]=warped[mask>0]
cv2.imwrite(str(OUT/'sample_scene.jpg'),scene_cv,[int(cv2.IMWRITE_JPEG_QUALITY),92])
Image.fromarray(cv2.cvtColor(scene_cv,cv2.COLOR_BGR2RGB)).resize((850,557)).save(ROOT/'static'/'hero.jpg',quality=88)
print('Demo created: 3 registered items + demo/sample_scene.jpg')

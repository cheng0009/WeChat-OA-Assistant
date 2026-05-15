"""Find the sticker/image toggle in the editor page."""
import glob, re

files = sorted(glob.glob("data/wechat_debug/*.html"))
for f in files:
    name = f.split("\\")[-1]
    if "home" in name:
        continue
    with open(f, encoding="utf-8") as fh:
        html = fh.read()
    print(f"\n=== {name} ===")
    
    # Find tabs or toggle elements
    for m in re.finditer(r'<div[^>]*class="[^"]*(?:tab|toggle|switch|mode)[^"]*"[^>]*>', html):
        print(f"Toggle/tab: {m.group()[:200]}")
    
    # Find any element containing both 贴图 and 图片 
    for m in re.finditer(r'[^<>]*贴图[^<>]*', html):
        ctx = html[max(0,m.start()-50):m.end()+50]
        print(f"贴图 context: {ctx}")
    
    # Find isTietu usage in the editor page
    for m in re.finditer(r'isTietu[^;]{0,100}', html):
        print(f"isTietu: {m.group()}")

    # Look for creation buttons or new-creation menu
    for m in re.finditer(r'new-creation__menu[^>]*>', html):
        start = m.start()
        end = min(len(html), start + 2000)
        print(f"Creation menu: {html[start:end]}")

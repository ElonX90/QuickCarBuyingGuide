"""Collect public monthly ranking evidence; never edit reviewed scores."""
import concurrent.futures, hashlib, json, re, urllib.request
from pathlib import Path
URL="https://www.autohome.com.cn/rank/1-1-0-0_9000-x-x-x/2026-09.html"
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=18) as r:
        data=r.read()
    return data
html=get(URL).decode("utf-8")
data=json.loads(re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',html,re.S).group(1))
p=data["props"]["pageProps"]
print("SOURCE_DATE",json.dumps(p["initialValues"],ensure_ascii=False))
print("SOURCE_SCOPE",p["saleranktip"])
print("PAGINATION",json.dumps({k:v for k,v in p["listRes"].items() if k in ["pagecount","pageindex","pagesize"]}))
for row in p["listRes"]["list"]:
    print("SALES_ROW",json.dumps({k:row.get(k) for k in ["rankNum","seriesid","seriesname","salecount","brandid","energytype"]},ensure_ascii=False))
urls=[u for u in re.findall(r'<script[^>]+src=["\x27]([^"\x27]+)',html) if "/chunks/" in u]
def probe(url):
    try:
        body=get("https:"+url if url.startswith("//") else url).decode("utf-8")
        hit=re.search(r"19859[:(]",body)
        if hit:
            fragment=body[hit.start():hit.start()+14000]
            # Record public API facts, not the third-party JavaScript source.
            strings=re.findall(r'["\x27]([^"\x27\s]{5,250})["\x27]',fragment)
            print("API_PATHS",json.dumps([x for x in strings if "rank" in x.lower() or "http" in x.lower()],ensure_ascii=False))
            fg=re.search(r"Fg:(?:\(\)=>|function\(\)\{return )([\w$]+)",fragment)
            print("FG_EXPORT",fg.group(1) if fg else "not found")
            if fg:
                name=fg.group(1)
                where=re.search(r"(?:let|var|const|,)"+re.escape(name)+r"=",fragment)
                if where:
                    window=fragment[where.start():where.start()+900]
                    print("FG_LITERALS",json.dumps(re.findall(r'["\x27]([^"\x27]+)["\x27]',window),ensure_ascii=False))
            print("ASSET_FINGERPRINT",hashlib.sha256(body.encode()).hexdigest())
        hosts=set(re.findall(r"https?://[a-zA-Z0-9.-]+",body))
        hosts={h for h in hosts if "autohome" in h or "autoimg" in h}
        if hosts:
            print("PUBLIC_API_HOSTS",json.dumps(sorted(hosts)))
    except Exception as e:
        print("ASSET_READ_FAILED",url.rsplit("/",1)[-1],type(e).__name__)
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(probe,urls))

# The browser bundle exposes this public getList route and its fixed query parameters.
import urllib.parse
params={"typeid":"1","subranktypeid":1,"levelid":"0","price":"0-9000","date":"2026-09","pagesize":50,"pageindex":1,"cityid":0,"provinceid":0}
url="https://car-web-api.autohome.com.cn/car/rank/getList?channel=0&model=1&pm=1&"+urllib.parse.urlencode(params)
obj=json.loads(get(url))
print("PUBLIC_LIST_RECEIPT",json.dumps({"url":url,"response":obj},ensure_ascii=False))

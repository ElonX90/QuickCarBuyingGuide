"""Read a fixed public monthly cohort without changing reviewed scores."""
import hashlib,json,urllib.request,urllib.parse
URL="https://www.autohome.com.cn/rank/1-1-0-0_9000-x-x-x/2026-09.html"
PARAMS={"typeid":"1","subranktypeid":1,"levelid":"0","price":"0-9000","date":"2026-09","pagesize":50,"cityid":0,"provinceid":0}
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Referer":URL})
    with urllib.request.urlopen(req,timeout=25) as r:
        body=r.read()
    return body
def lists(obj):
    if isinstance(obj,list):
        if obj and isinstance(obj[0],dict) and "seriesid" in obj[0] and "salecount" in obj[0]:
            yield obj
        for v in obj:
            yield from lists(v)
    elif isinstance(obj,dict):
        for v in obj.values():
            yield from lists(v)
rows=[]
for page in [1,2]:
    params=dict(PARAMS,pageindex=page)
    url="https://car-web-api.autohome.com.cn/car/rank/getList?channel=0&model=1&pm=1&"+urllib.parse.urlencode(params)
    body=get(url)
    obj=json.loads(body)
    print("FETCH_RECEIPT",json.dumps({"url":url,"sha256":hashlib.sha256(body).hexdigest(),"keys":list(obj)}))
    found=list(lists(obj))
    if not found:
        print("SOURCE_RESPONSE",json.dumps(obj,ensure_ascii=False)[:1200])
        raise RuntimeError("No sales rows found")
    current=found[0]
    print("PAGE_COUNT",page,len(current))
    for row in current:
        print("SALES_ROW",json.dumps({k:row.get(k) for k in ["rankNum","rank","seriesid","seriesname","salecount","brandid","brandname","energytype"]},ensure_ascii=False))
    rows+=current
print("SOURCE_COUNTS",len(rows),len({str(x["seriesid"]) for x in rows}))

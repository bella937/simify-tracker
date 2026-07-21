#!/usr/bin/env python3
"""Source NEW on-pattern channels via YouTube search (retuned niches), keep
nano-micro (<=40K) actives (posted <8mo), grab latest video for the Discovery
embed, and MERGE into docs/data/prospects.json (preserving existing entries)."""
import os,sys,json,time,re,datetime,urllib.parse,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT=os.path.join(ROOT,"docs","data","prospects.json")
CRE=os.path.join(ROOT,"docs","data","creators.json")
API="https://www.googleapis.com/youtube/v3"
MIN_SUBS,MAX_SUBS,MONTHS=1000,40000,8.0
# On-pattern query pool (nano-micro, female-led / couple, slow + solo travel).
# Each ISO week we rotate an 8-query window through the pool + rotate the region
# order, so the scheduled job works the whole space over time instead of
# re-hitting the same searches (dedup still prevents re-adding known channels).
NICHE_POOL=[
    "solo female van life","solo female van life uk","wild camping solo female","solo female hiking vlog",
    "solo female backpacking","budget solo female travel","solo female adventure vlog","solo female motorhome",
    "campervan life couple","couple van life travel","sailing couple liveaboard","liveaboard sailing life",
    "couple road trip vlog","overlanding couple travel","couple slow travel vlog","van build couple",
    "slow living travel vlog","aesthetic slow travel","slow travel europe vlog","off grid living woman",
    "tiny living van woman","female solo camping","solo female train travel europe","cosy lifestyle travel vlog",
]
REGION_POOL=["GB","US","AU","CA","NZ"]
WEEK=datetime.date.today().isocalendar()[1]
_W=8; _start=(WEEK*_W)%len(NICHE_POOL)
NICHES=[NICHE_POOL[(_start+i)%len(NICHE_POOL)] for i in range(_W)]
_r=WEEK%len(REGION_POOL); REGIONS=REGION_POOL[_r:]+REGION_POOL[:_r]
print(f"ISO week {WEEK}: niches {NICHES} | regions {REGIONS}")
def key():
    k=os.environ.get("YOUTUBE_API_KEY")
    if k: return k.strip()
    envp=os.path.join(ROOT,"workers",".env")
    if os.path.exists(envp):
        for line in open(envp):
            if line.strip().startswith("YOUTUBE_API_KEY"): return line.split("=",1)[1].strip().strip('"').strip("'")
    sys.exit("no key")
K=key()
def api(path,**p):
    p["key"]=K
    with urllib.request.urlopen(API+"/"+path+"?"+urllib.parse.urlencode(p),timeout=30) as r: return json.load(r)
def months(iso):
    try:
        d=datetime.datetime.fromisoformat(str(iso).replace("Z","+00:00"))
        if d.tzinfo is None: d=d.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc)-d).days/30.44
    except: return None

# --- contact extraction: pull a business email creators publish in plain text
# in their channel About / video descriptions (NOT the CAPTCHA-gated About email).
EMAIL_RE=re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
LINK_RE=re.compile(r'https?://(?:www\.)?(?:linktr\.ee|beacons\.ai|linkin\.bio|solo\.to|komi\.io|stan\.store|milkshake\.app)/[^\s)\]]+',re.I)
BIZ_HINT=re.compile(r'(business|enquir|inquir|contact|collab|partnership|\bemail\b|work with|sponsor|📩|✉)',re.I)
_IMG_EXT=("png","jpg","jpeg","gif","webp","svg","bmp","ico")
_BAD_DOM=("example.","sentry.","wixpress.","email.com","domain.com","yourbrand.","youremail.")
def _valid_email(e):
    dom=e.rsplit("@",1)[-1].lower()
    if dom.rsplit(".",1)[-1] in _IMG_EXT: return False           # e.g. logo@2x.png
    if any(b in dom for b in _BAD_DOM): return False             # placeholders
    return True
def extract_contact(*texts):
    """Return (best_email, link) from the given text blobs. Prefers an email that
    sits right after a business/contact cue; falls back to the first valid one."""
    blob="\n".join(t for t in texts if t)
    emails=[e.rstrip(".") for e in EMAIL_RE.findall(blob) if _valid_email(e.rstrip("."))]
    best=""
    for e in emails:
        i=blob.find(e)
        if i>=0 and BIZ_HINT.search(blob[max(0,i-80):i]): best=e; break
    if not best and emails: best=emails[0]
    lm=LINK_RE.search(blob)
    return best, (lm.group(0) if lm else "")
# existing (preserve) + roster handles (dedup)
existing=json.load(open(OUT)); have={p["handle"].lower() for p in existing["prospects"]}
try:
    ros=json.load(open(CRE)); ros=ros.get("creators",ros)
    for c in ros: have.add(str(c.get("handle","")).lower())
except: pass

# --- backfill: fill emails on existing prospects that don't have one yet
# (cheap: one channels.list per 50, description only — no per-channel calls).
need={p["channelId"]:p for p in existing["prospects"] if p.get("channelId") and not p.get("email")}
if need:
    filled=0; nids=list(need)
    for batch in [nids[i:i+50] for i in range(0,len(nids),50)]:
        try: d=api("channels",part="snippet",id=",".join(batch))
        except Exception as e: print("  ! backfill channels:",e); continue
        for it in d.get("items",[]):
            em,site=extract_contact(it.get("snippet",{}).get("description",""))
            p=need.get(it["id"])
            if not p: continue
            if em: p["email"]=em; filled+=1
            if site and not p.get("site"): p["site"]=site
        time.sleep(0.1)
    print(f"  backfilled {filled} email(s) onto {len(need)} email-less prospects")

found_ids={}
for i,niche in enumerate(NICHES):
    region=REGIONS[i%len(REGIONS)]
    try:
        s=api("search",part="snippet",type="channel",q=niche,regionCode=region,relevanceLanguage="en",maxResults=20)
        for it in s.get("items",[]):
            cid=it["snippet"].get("channelId") or it.get("id",{}).get("channelId")
            if cid: found_ids[cid]=niche
        print(f"  search '{niche}' [{region}] -> {len(s.get('items',[]))} channels (total unique {len(found_ids)})")
        time.sleep(0.1)
    except Exception as e: print(f"  ! search '{niche}': {e}")
ids=list(found_ids)
kept=[]
for batch in [ids[i:i+50] for i in range(0,len(ids),50)]:
    try: d=api("channels",part="snippet,statistics,contentDetails",id=",".join(batch))
    except Exception as e: print("  ! channels:",e); continue
    for it in d.get("items",[]):
        subs=int(it.get("statistics",{}).get("subscriberCount",0) or 0)
        if it.get("statistics",{}).get("hiddenSubscriberCount"): continue
        if subs<MIN_SUBS or subs>MAX_SUBS: continue
        handle=it["snippet"].get("customUrl","") or ""
        if handle and not handle.startswith("@"): handle="@"+handle
        if not handle or handle.lower() in have: continue
        up=it["contentDetails"]["relatedPlaylists"]["uploads"]
        try: pl=api("playlistItems",part="contentDetails,snippet",playlistId=up,maxResults=1)
        except: continue
        pit=(pl.get("items") or [{}])[0]
        vid=pit.get("contentDetails",{}).get("videoId","")
        pub=(pit.get("contentDetails",{}).get("videoPublishedAt") or pit.get("snippet",{}).get("publishedAt") or "")[:10]
        m=months(pub)
        if m is None or m>MONTHS: continue
        have.add(handle.lower())
        email,site=extract_contact(it["snippet"].get("description",""),
                                   pit.get("snippet",{}).get("description",""))
        why=f"Sourced ({found_ids[it['id']]}) - {subs:,} subs, active."
        why+=" Email on file." if email else (f" No public email - see {site}" if site else " No public email in About/video.")
        kept.append({"name":it["snippet"]["title"],"handle":handle,"channelId":it["id"],"subs":subs,
                     "niche":found_ids[it["id"]],"market":(it["snippet"].get("country") or ""),
                     "videoId":vid,"lastUpload":pub,"email":email,"site":site,"why":why})
    time.sleep(0.1)
kept.sort(key=lambda p:p["lastUpload"],reverse=True)
existing["prospects"]=existing["prospects"]+kept
existing["generated"]=datetime.date.today().isoformat()
existing["source"]="on-pattern batch + sourced via retuned YouTube search (source_prospects.py)"
json.dump(existing,open(OUT,"w"),ensure_ascii=False,indent=2)
print(f"\nDone. +{len(kept)} new on-pattern leads (<=40K, <8mo). Total prospects: {len(existing['prospects'])}.")

#!/usr/bin/env python3
"""Source NEW on-pattern channels via YouTube search (retuned niches), keep
nano-micro (<=40K) actives (posted <8mo), grab latest video for the Discovery
embed, and MERGE into docs/data/prospects.json (preserving existing entries)."""
import os,sys,json,time,datetime,urllib.parse,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT=os.path.join(ROOT,"docs","data","prospects.json")
CRE=os.path.join(ROOT,"docs","data","creators.json")
API="https://www.googleapis.com/youtube/v3"
MIN_SUBS,MAX_SUBS,MONTHS=1000,40000,8.0
NICHES=["solo female van life","solo female travel vlog","wild camping solo female",
        "solo female hiking vlog","van life couple","sailing couple liveaboard",
        "digital nomad woman","aesthetic slow travel vlog"]
REGIONS=["GB","US","AU","CA"]
def key():
    for line in open(os.path.join(ROOT,"workers",".env")):
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
# existing (preserve) + roster handles (dedup)
existing=json.load(open(OUT)); have={p["handle"].lower() for p in existing["prospects"]}
try:
    ros=json.load(open(CRE)); ros=ros.get("creators",ros)
    for c in ros: have.add(str(c.get("handle","")).lower())
except: pass
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
        kept.append({"name":it["snippet"]["title"],"handle":handle,"channelId":it["id"],"subs":subs,
                     "niche":found_ids[it["id"]],"market":(it["snippet"].get("country") or ""),
                     "videoId":vid,"lastUpload":pub,"email":"","why":f"Sourced ({found_ids[it['id']]}) - {subs:,} subs, active."})
    time.sleep(0.1)
kept.sort(key=lambda p:p["lastUpload"],reverse=True)
existing["prospects"]=existing["prospects"]+kept
existing["generated"]=datetime.date.today().isoformat()
existing["source"]="on-pattern batch + sourced via retuned YouTube search (source_prospects.py)"
json.dump(existing,open(OUT,"w"),ensure_ascii=False,indent=2)
print(f"\nDone. +{len(kept)} new on-pattern leads (<=40K, <8mo). Total prospects: {len(existing['prospects'])}.")
